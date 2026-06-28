"""Pure Recommendation builder (issue #80, PRD §14.2 / §9.3 / §13).

The execution-layer face of the techtrade pipeline: turns a **paper-filled
:class:`~openbb_techtrade.models.TradePlan`** (realized entry from #78, levels + size
from #76, votes from #74, orders from #77) into a fully-populated
:class:`~openbb_techtrade.models.Recommendation` -- action / conviction, entry / stop /
target + stop-gaps + R:R + ATR, sizing / risk fields, and a **deterministic, non-LLM**
``reasoning`` / ``top_factors`` / ``caveats`` narrative that traces back to the signal's
votes. No orders, no fills, no network, no LLM.

The builder is **pure, offline, and deterministic** (design §1, L7): it depends on
``models`` (+ stdlib ``decimal``) and ``confluence.conviction_for`` only (the L3 reuse
note -- one source of truth for the ``0.7 / 0.4`` edges); it consumes a paper-filled
``TradePlan`` and **never** recomputes votes (#74), levels / sizing (#76), or fills (#78).
Every number is carried through from upstream; this module only *derives* gaps / ratios
(§2) and *renders* prose (§4). Same plan in => identical ``Recommendation`` (string-stable)
out, unit-testable without ``openbb.build()``.

Sibling of :mod:`~openbb_techtrade.execution.broker` (#78 owns ``broker.py`` /
``simulate.py``); together they realize the PRD §9.1 ``engine/execution.py`` pact -- the
broker/fill half landed in #78, this Recommendation-builder half is #80 (Q-F).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from openbb_techtrade.engine.confluence import conviction_for
from openbb_techtrade.models import (
    Fill,
    IndicatorVote,
    Recommendation,
    TradePlan,
)

#: Near-zero contribution threshold for :func:`_top_factors` drop (design Q-B).
_EPSILON: float = 1e-9

#: Per-direction action map (design L2).
_ACTIONS: dict[str, str] = {"long": "BUY", "short": "SELL_SHORT", "flat": "HOLD/FLAT"}

#: Per-direction lead word for the reasoning lead (design §4.1).
_LEAD_WORD: dict[str, str] = {"long": "Long", "short": "Short", "flat": "Hold"}

#: Canonical family ordering -- drives clause order in reasoning (§4.1) and the
#: family tie-break in :func:`_top_factors` (design Q-B).
_FAMILY_ORDER: tuple[str, ...] = ("trend", "momentum", "volatility", "volume")

#: Inverse lookup for the family tie-break key.
_FAMILY_RANK: dict[str, int] = {name: index for index, name in enumerate(_FAMILY_ORDER)}

#: Strength bucket prefix (design §4.1) keyed by ``_strength_bucket`` output.
_STRENGTH_PREFIX: dict[str, str] = {"strong": "strongly ", "mid": "", "weak": "weakly "}

#: Per-family polarity word lookups (design §4.1).
_TREND_POLARITY: dict[int, str] = {1: "positive", -1: "negative", 0: "mixed"}
_MOMENTUM_POLARITY: dict[int, str] = {1: "confirming", -1: "diverging", 0: "neutral"}
_VOLATILITY_POLARITY: dict[int, str] = {1: "breakout", -1: "range-bound", 0: "neutral"}
_VOLUME_POLARITY: dict[int, str] = {1: "confirming", -1: "diverging", 0: "neutral"}


@dataclass(frozen=True)
class RecommendationConfig:
    """Pure-data builder config: top-K, borderline band, and abstract notional (design §0.2).

    Frozen + hashable so the same config instance can be reused across many builds without
    aliasing surprises. ``account_size`` is the **abstract** notional behind Q-E E3 -- the
    field is a fraction, not a dollar amount, so no personal-dollar leak even at the default
    ``Decimal("100000")``.

    Parameters
    ----------
    top_k : int, optional
        Maximum ``top_factors`` to emit. Defaults to ``3`` (matches the PRD §9.3 example
        length).
    borderline_delta : float, optional
        Width of the borderline conviction band above ``EntryExitRule.entry_threshold``;
        a non-flat ``|score|`` in ``[threshold, threshold + delta)`` fires the borderline
        caveat (Q-C trigger #5). Defaults to ``0.10``.
    account_size : Decimal, optional
        Abstract notional for the Q-E E3 risk fraction
        ``(position_size * risk_per_share) / account_size``. Defaults to
        ``Decimal("100000")`` -- matches the #76 / #77 sizing default so a builder run with
        the default config reconciles with the #77 inline plan.
    epsilon : float, optional
        Drop-threshold for near-zero ``|weight * vote|`` contributors in
        :func:`_top_factors`. Defaults to :data:`_EPSILON` (``1e-9``).
    """

    top_k: int = 3
    borderline_delta: float = 0.10
    account_size: Decimal = Decimal("100000")
    epsilon: float = _EPSILON


#: The shipped default config (Q-B / Q-C / Q-E defaults).
DEFAULT_REC: RecommendationConfig = RecommendationConfig()


def build_recommendation(
    plan: TradePlan, *, config: RecommendationConfig = DEFAULT_REC
) -> Recommendation:
    """Build a fully-populated :class:`Recommendation` from a paper-filled ``TradePlan`` (§14.2).

    The pure, return-only builder (design Q-F). Resolves the realized / planned levels per
    Q-D, computes the derived gaps + R:R in Decimal (§2.1), normalizes risk to a fraction
    of abstract notional (Q-E E3), and renders the deterministic, votes-only narrative
    (§4). The result is string-stable: identical ``TradePlan`` in => identical
    ``Recommendation`` out.

    The caller (``plan_router`` / ``scan``) attaches the result via
    ``plan.model_copy(update={"recommendation": rec})`` (Q-F return-only contract). No
    mutation here.

    Parameters
    ----------
    plan : TradePlan
        A paper-filled trade plan: ``signal`` / ``rule`` / ``position_size`` / ``orders``
        are populated; ``simulated_fills`` carries the entry fill when the plan filled,
        an empty list otherwise; ``recommendation`` is the inline #77 build (overwritten
        by the caller's ``model_copy`` after this returns).
    config : RecommendationConfig, optional
        Builder configuration. Defaults to :data:`DEFAULT_REC`.

    Returns
    -------
    Recommendation
        A fully-populated recommendation (all 20 fields), with deterministic
        ``reasoning`` / ``top_factors`` / ``caveats`` traceable to ``plan.signal.votes``.
    """
    signal = plan.signal
    direction = signal.direction
    action = _ACTIONS[direction]
    conviction = conviction_for(signal.score)

    # --- Levels (Q-D: realized / planned / flat) ---
    entry, stop, target, fill_status = _resolve_levels(plan)

    # --- Derived gaps + R:R (§2.1, Decimal -> float at boundary, FLAT zero-distance) ---
    stop_distance_pct, target_distance_pct, risk_reward = _gaps_and_rr(entry, stop, target)

    # --- Risk / sizing (Q-E E3: realized fraction of abstract notional) ---
    qty = plan.position_size
    risk_per_share = abs(entry - stop) if direction != "flat" else Decimal(0)
    risk_pct_of_notional = (
        float(qty * risk_per_share / config.account_size)
        if direction != "flat" and config.account_size != 0
        else 0.0
    )

    return Recommendation(
        symbol=signal.symbol,
        segment=signal.segment,
        as_of=signal.as_of,
        action=action,
        conviction=conviction,
        score=signal.score,
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        stop_distance_pct=stop_distance_pct,
        target_distance_pct=target_distance_pct,
        risk_reward=risk_reward,
        atr=_carry_through_atr(plan),
        position_size=qty,
        risk_per_share=risk_per_share,
        risk_pct_of_notional=risk_pct_of_notional,
        time_stop_bars=plan.rule.max_holding_bars if direction != "flat" else None,
        reasoning=_build_reasoning(
            plan, stop_distance_pct, target_distance_pct, risk_reward
        ),
        top_factors=_top_factors(signal.votes, config),
        caveats=_build_caveats(plan, fill_status, config),
    )


# ---------------------------------------------------------------------------
# Level resolution (Q-D)
# ---------------------------------------------------------------------------


def _entry_fill(plan: TradePlan) -> Fill | None:
    """Return the entry-intent fill from ``plan.simulated_fills``, or ``None``.

    The #78 broker stamps each fill with ``order_ref = f"{symbol}:{intent}"`` -- the entry
    leg therefore ends in ``":entry"``. A plan with no fills (no forward window supplied)
    yields ``None`` and the no-fill fallback (Q-D) takes over.
    """
    for fill in plan.simulated_fills:
        if fill.order_ref.endswith(":entry"):
            return fill
    return None


def _orders_by_intent(plan: TradePlan) -> dict[str, object]:
    """Index the plan's #77 order legs by ``intent`` for cheap lookup."""
    return {order.intent: order for order in plan.orders}


def _resolve_levels(plan: TradePlan) -> tuple[Decimal, Decimal, Decimal, str]:
    """Resolve ``(entry, stop, target, fill_status)`` per design Q-D.

    Three branches:

    * **HOLD/FLAT**: ``entry = stop = target = plan.recommendation.entry_price`` (the
      ``as_of`` close, set by #77's inline build); ``fill_status = "flat"``. The
      zero-distance levels collapse the derived gaps / R:R in :func:`_gaps_and_rr`.
    * **BUY/SELL_SHORT, filled**: ``entry = entry_fill.price`` (realized, after slippage);
      ``stop`` / ``target`` are the **frozen** planned levels from the order legs (per
      #77 Q-F: freeze + report drift). ``fill_status = "filled"``.
    * **BUY/SELL_SHORT, not filled** (limit never marketable / no forward window):
      ``entry = plan.recommendation.entry_price`` (the planned ``entry_ref``); ``stop`` /
      ``target`` from the order legs. ``fill_status = "no_fill"`` -- triggers caveat #2.

    The planned ``entry_ref`` is read from ``plan.recommendation.entry_price`` because
    that is the single carry-through site for the #76 entry across the chain (the inline
    #77 build sets it from the same ``entry`` Decimal passed to :func:`apply_rule`).
    """
    direction = plan.signal.direction
    planned_entry = plan.recommendation.entry_price

    if direction == "flat":
        return planned_entry, planned_entry, planned_entry, "flat"

    by_intent = _orders_by_intent(plan)
    stop: Decimal = by_intent["exit_stop"].stop_price  # type: ignore[attr-defined]
    target: Decimal = by_intent["exit_target"].limit_price  # type: ignore[attr-defined]

    fill = _entry_fill(plan)
    if fill is not None:
        return fill.price, stop, target, "filled"
    return planned_entry, stop, target, "no_fill"


def _carry_through_atr(plan: TradePlan) -> float:
    """Carry the ATR(14) used to size the stop (§2 input table).

    Surfaced verbatim from the inline #77 recommendation (which received it from
    :func:`~openbb_techtrade.engine.plan._default_level_fetcher` via
    :func:`~openbb_techtrade.engine.orders.build_trade_plan`). #80 never touches pandas-ta.
    """
    return plan.recommendation.atr


# ---------------------------------------------------------------------------
# Derived gaps + R:R (§2.1)
# ---------------------------------------------------------------------------


def _gaps_and_rr(entry: Decimal, stop: Decimal, target: Decimal) -> tuple[float, float, float]:
    """Compute ``(stop_distance_pct, target_distance_pct, risk_reward)`` per §2.1.

    Arithmetic stays in Decimal end-to-end, with a single cast to ``float`` at the
    boundary (no float money math, L5). Guards the FLAT / zero-distance / zero-entry
    sentinel: ``entry == 0`` or ``entry == stop`` collapses all three returns to ``0.0``,
    so :func:`_resolve_levels`'s FLAT branch produces a clean zero-row recommendation
    (Excel maps the zeros to "--" per #81's §14.3 sketch).
    """
    if entry == 0 or stop == entry:
        return 0.0, 0.0, 0.0
    stop_distance = abs(entry - stop)
    target_distance = abs(target - entry)
    stop_distance_pct = float(stop_distance / entry)
    target_distance_pct = float(target_distance / entry)
    risk_reward = float(target_distance / stop_distance) if stop_distance != 0 else 0.0
    return stop_distance_pct, target_distance_pct, risk_reward


# ---------------------------------------------------------------------------
# Reasoning (§4.1) -- the deterministic, votes-only template
# ---------------------------------------------------------------------------


def _vote_sign(value: float) -> int:
    """Return ``+1`` / ``-1`` / ``0`` for ``value > / < / == 0`` (int -- distinct from confluence._sign)."""
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _vote_token(vote: IndicatorVote) -> str:
    """Format a vote as a polarity token: ``"{name}{+|-}"`` (design Q-A, A1)."""
    suffix = "+" if vote.vote > 0 else "-" if vote.vote < 0 else "0"
    return f"{vote.name}{suffix}"


def _strength_bucket(votes: list[IndicatorVote]) -> str:
    """Bucket a family's mean-vote magnitude into ``"strong"`` / ``"mid"`` / ``"weak"`` (§4.1).

    The design uses ``|family_contribution| / w_family`` which is algebraically
    ``|mean(family votes)|`` since every vote in a family carries the same weight; we
    compute the latter directly. Thresholds ``>= 0.66`` / ``>= 0.33`` are provisional
    (design §4.1) but deterministic, so the golden lock is stable.
    """
    if not votes:
        return "weak"
    mean_vote = sum(v.vote for v in votes) / len(votes)
    magnitude = abs(mean_vote)
    if magnitude >= 0.66:
        return "strong"
    if magnitude >= 0.33:
        return "mid"
    return "weak"


def _family_polarity_sign(votes: list[IndicatorVote]) -> int:
    """Return the sign of a family's mean vote (``+1`` / ``-1`` / ``0``)."""
    if not votes:
        return 0
    mean_vote = sum(v.vote for v in votes) / len(votes)
    return _vote_sign(mean_vote)


def _family_clause(family: str, votes: list[IndicatorVote]) -> str | None:
    """Render one family's clause, or ``None`` when the family has no votes.

    Uniform shape across families to keep the auditability invariant clean -- every vote
    name appears in the parenthetical detail token list -- while still honouring the §4.1
    per-family polarity vocabulary:

    * ``trend``: ``"{strength}{positive|negative|mixed}"``
    * ``momentum``: ``"{strength}{confirming|diverging|neutral}"``
    * ``volatility``: ``"{breakout|range-bound|neutral}"`` (no strength prefix)
    * ``volume``: ``"{confirming|diverging|neutral}"`` (no strength prefix)

    Design §4.1 sketches more natural-language phrasings for volume (e.g. *"rising OBV
    confirms participation"*) -- those would drop the vote name and weaken the
    auditability invariant L8. The uniform form preserves it.
    """
    if not votes:
        return None
    sign = _family_polarity_sign(votes)
    detail = ", ".join(_vote_token(v) for v in votes)
    if family == "trend":
        prefix = _STRENGTH_PREFIX[_strength_bucket(votes)]
        return f"trend {prefix}{_TREND_POLARITY[sign]} ({detail})"
    if family == "momentum":
        prefix = _STRENGTH_PREFIX[_strength_bucket(votes)]
        return f"momentum {prefix}{_MOMENTUM_POLARITY[sign]} ({detail})"
    if family == "volatility":
        return f"volatility {_VOLATILITY_POLARITY[sign]} ({detail})"
    if family == "volume":
        return f"volume {_VOLUME_POLARITY[sign]} ({detail})"
    return None  # pragma: no cover -- family is constrained by Literal in models.py


def _join_with_and(clauses: list[str]) -> str:
    """Join clauses with commas + an Oxford ``"and"`` before the last (deterministic)."""
    if not clauses:
        return ""
    if len(clauses) == 1:
        return clauses[0]
    if len(clauses) == 2:
        return f"{clauses[0]} and {clauses[1]}"
    return ", ".join(clauses[:-1]) + f", and {clauses[-1]}"


def _build_reasoning(
    plan: TradePlan,
    stop_distance_pct: float,
    target_distance_pct: float,
    risk_reward: float,
) -> str:
    """Render the deterministic, non-LLM reasoning string (§4.1).

    Three slots: lead (action + symbol), per-family clauses (canonical order), and a
    levels sentence. FLAT skips the levels sentence (zero-distance, design §4.1 FLAT
    branch). The string is byte-stable: same plan in => identical string out.
    """
    signal = plan.signal
    direction = signal.direction
    lead = f"{_LEAD_WORD[direction]} {signal.symbol}: "

    # Bucket votes by family (canonical order) so the clause sequence is deterministic.
    by_family: dict[str, list[IndicatorVote]] = {family: [] for family in _FAMILY_ORDER}
    for vote in signal.votes:
        if vote.family in by_family:
            by_family[vote.family].append(vote)

    clauses = [
        clause
        for clause in (_family_clause(family, by_family[family]) for family in _FAMILY_ORDER)
        if clause is not None
    ]

    if direction == "flat":
        # FLAT: clauses + "below the entry threshold" -- no levels sentence.
        body = (
            f"{_join_with_and(clauses)}; below the entry threshold."
            if clauses
            else "below the entry threshold."
        )
        return lead + body

    clauses_str = _join_with_and(clauses) if clauses else "no contributing votes"

    # Levels sentence (§4.1):
    #   "Stop {mult}xATR {below|above} entry ({stop%:+.1%}); target at {RR:.1f}R ({tgt%:+.1%})."
    # Signs follow direction: long stop below entry => negative %; short stop above => positive %.
    is_long = direction == "long"
    stop_word = "below" if is_long else "above"
    stop_signed = (-stop_distance_pct) if is_long else stop_distance_pct
    target_signed = target_distance_pct if is_long else (-target_distance_pct)
    atr_mult = plan.rule.atr_stop_mult
    levels_sentence = (
        f"Stop {atr_mult:g}xATR {stop_word} entry ({stop_signed:+.1%}); "
        f"target at {risk_reward:.1f}R ({target_signed:+.1%})."
    )
    return f"{lead}{clauses_str}. {levels_sentence}"


# ---------------------------------------------------------------------------
# top_factors (§4.2)
# ---------------------------------------------------------------------------


def _attribution(vote: IndicatorVote) -> float:
    """Return the #74 attribution key ``|weight * vote|`` used to rank top factors."""
    return abs(vote.weight * vote.vote)


def _top_factors(votes: list[IndicatorVote], config: RecommendationConfig) -> list[str]:
    """Rank ``votes`` by ``|weight * vote|`` desc, take top-K, format as ``"name+- (family)"`` (§4.2).

    Tie-break (design Q-B, total order): ``|weight * vote|`` desc =>
    canonical family order ``(trend, momentum, volatility, volume)`` => name alpha. Votes
    whose ``|weight * vote|`` is at or below :attr:`RecommendationConfig.epsilon` are
    dropped (the "near-zero contributors" cut).
    """
    filtered = [vote for vote in votes if _attribution(vote) > config.epsilon]
    filtered.sort(
        key=lambda vote: (
            -_attribution(vote),
            _FAMILY_RANK.get(vote.family, len(_FAMILY_RANK)),
            vote.name,
        )
    )
    return [_format_factor(vote) for vote in filtered[: config.top_k]]


def _format_factor(vote: IndicatorVote) -> str:
    """Format one top factor as ``"{name}{+|-} ({family})"`` (design Q-B)."""
    suffix = "+" if vote.vote > 0 else "-"
    return f"{vote.name}{suffix} ({vote.family})"


# ---------------------------------------------------------------------------
# Caveats (§4.3) -- fixed-precedence trigger evaluation
# ---------------------------------------------------------------------------


def _validation_is_failing(validation: object) -> bool:
    """Duck-typed read of #82's ``ValidationReport`` -- best-effort until #82 lands.

    Fires when ``validation`` is not ``None`` AND either:
    * a duck-typed ``passed`` attribute is ``False``, **or**
    * a duck-typed ``overfit_probability`` exceeds ``0.5``.

    Both attribute names are best-effort: #82 has not landed in this branch, so we cannot
    import its real schema. When #82 ships and the schema stabilises, swap this check for
    the typed read; the caveat clause stays identical so the golden lock is unaffected.
    """
    if validation is None:
        return False
    passed = getattr(validation, "passed", True)
    overfit_probability = getattr(validation, "overfit_probability", 0.0)
    return (not passed) or (overfit_probability > 0.5)


def _has_volume_divergence(votes: list[IndicatorVote], score: float) -> bool:
    """True when any ``volume`` vote opposes ``sign(score)`` (Q-C trigger #3)."""
    score_sign = _vote_sign(score)
    if score_sign == 0:
        return False
    for vote in votes:
        if vote.family != "volume":
            continue
        vote_sign = _vote_sign(vote.vote)
        if vote_sign != 0 and vote_sign != score_sign:
            return True
    return False


def _first_split_family(votes: list[IndicatorVote]) -> str | None:
    """Return the first family (in canonical order) with intra-family sign disagreement.

    A family is split when at least one of its votes has ``vote > 0`` AND at least one has
    ``vote < 0``. Zero-votes do not constitute a split. Returning only the **first** family
    keeps the caveat string short and deterministic (Q-C precedence).
    """
    by_family: dict[str, set[int]] = {}
    for vote in votes:
        sign = _vote_sign(vote.vote)
        if sign == 0:
            continue
        by_family.setdefault(vote.family, set()).add(sign)
    for family in _FAMILY_ORDER:
        if 1 in by_family.get(family, set()) and -1 in by_family.get(family, set()):
            return family
    return None


def _first_missing_family(votes: list[IndicatorVote]) -> str | None:
    """Return the first family (canonical order) with no votes in the signal, or ``None``."""
    present = {vote.family for vote in votes}
    for family in _FAMILY_ORDER:
        if family not in present:
            return family
    return None


def _build_caveats(
    plan: TradePlan, fill_status: str, config: RecommendationConfig
) -> str:
    """Render the caveats string by evaluating the §4.3 / Q-C triggers in fixed precedence.

    Six triggers, evaluated in this order (deterministic / golden-stable):

    1. **Validation**: ``plan.validation`` present and failing (duck-typed best effort
       until #82 lands).
    2. **No paper fill**: non-flat ``action`` but no entry fill in ``simulated_fills``.
    3. **Volume divergence**: a volume vote opposing ``sign(score)``.
    4. **Intra-family disagreement**: first family (canonical order) with mixed signs.
    5. **Borderline conviction**: non-flat ``|score|`` in
       ``[entry_threshold, entry_threshold + borderline_delta)``.
    6. **Missing family**: first family (canonical order) absent from the panel.

    Empty trigger set => ``"None."`` (Q-C empty-case: a benign, non-blank, golden-stable
    string). Otherwise the firing clauses are joined as period-terminated sentences with
    leading capitals so the result reads naturally in the Excel ``Reasoning`` column.
    """
    signal = plan.signal
    direction = signal.direction
    clauses: list[str] = []

    # 1. Validation
    if _validation_is_failing(plan.validation):
        clauses.append("validation flags overfitting")

    # 2. No paper fill
    if direction != "flat" and fill_status == "no_fill":
        clauses.append("no paper fill - levels are planned, not realized")

    # 3. Volume divergence
    if direction != "flat" and _has_volume_divergence(signal.votes, signal.score):
        clauses.append("volume diverging from price")

    # 4. Intra-family disagreement
    split_family = _first_split_family(signal.votes)
    if split_family is not None:
        clauses.append(f"{split_family} votes split")

    # 5. Borderline conviction (non-flat, within delta band)
    threshold = plan.rule.entry_threshold
    score_abs = abs(signal.score)
    if direction != "flat" and threshold <= score_abs < threshold + config.borderline_delta:
        clauses.append("borderline conviction")

    # 6. Missing family
    missing_family = _first_missing_family(signal.votes)
    if missing_family is not None:
        clauses.append(f"{missing_family} unavailable (short history)")

    if not clauses:
        return "None."
    return ". ".join(clause[0].upper() + clause[1:] for clause in clauses) + "."
