"""SEC Form N-PORT-P submission parser (#99 T3).

Pure parser — no HTTP, no DB, no logging side-effects beyond a single
WARNING on unrecoverable parse failure.

Two-layer decoding (SEC pattern):
1. ``<SEC-DOCUMENT>`` envelope — line-oriented header (``<TYPE>NPORT-P``)
   followed by an XML body wrapped in ``<XML>`` ... ``</XML>``.
2. The XML body — N-PORT-P schema (``edgar-filing-mod-fund-nport-p``).
   We don't validate against the schema; we walk it with ``xml.etree`` and
   pluck the fields we need.

G4 holding-key contract (design §0.2 Q-B Resolution):
``holding_key = COALESCE(cusip, isin, lei, sha1(issuer_name||asset_category))``
with ``_lotN`` suffix appended deterministically when the same key collides
within one filing. This is the schema-level antidote to parse-order
ordinal collisions — the same content yields the same key across re-parses,
so ``upsert_holdings`` with the ``(accession_number, holding_key)`` PK is
genuinely idempotent.

L11 amendment detection: ``<TYPE>NPORT-P/A`` in the envelope -> ``is_amendment=True``.
The read helper in ``nport_index.holdings_for_fund`` uses this flag to
prefer the amendment over the original for the same period.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime
from typing import Any, TypedDict
from xml.etree.ElementTree import Element  # noqa: S405 — only the Element TYPE; parsing goes through defusedxml

import defusedxml.ElementTree as ET  # safe parser: blocks XXE + billion-laughs (matches xbrl_taxonomy_helper.py pattern)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Typed shapes (mirror §0.2 Q-B Resolution; total=False so callers can build
# them incrementally while keeping mypy honest about required keys).
# ---------------------------------------------------------------------------


class NportFiling(TypedDict, total=False):
    """One row destined for ``sec_nport_filings`` (T2 upsert_filing 12-tuple)."""

    accession_number: str
    cik: str
    series_id: str | None
    class_id: str | None
    report_date: date | None
    filing_date: date | None
    is_amendment: bool
    source: str
    raw_xml_url: str | None
    raw_xml_sha256: str | None
    fund_name: str | None
    period_of_report: str | None


class NportHolding(TypedDict, total=False):
    """One row destined for ``sec_nport_holdings`` (T2 upsert_holdings 13-tuple)."""

    accession_number: str
    holding_key: str
    issuer_name: str | None
    ticker: str | None
    cusip: str | None
    isin: str | None
    lei: str | None
    asset_category: str | None
    units: float | None
    value_usd: float | None
    pct_nav: float | None
    payoff_direction: str | None
    derivative_flag: bool


class NportParseError(RuntimeError):
    """Raised only for unrecoverable *structural* failures.

    The public ``parse_submission_envelope`` does NOT raise this — it logs
    a WARNING and returns ``(NportFiling{accession_number=..., source=...}, [])``
    so a single malformed filing doesn't kill a 10k-row bulk ingest.

    The class is exported because the underlying helpers may raise it; a
    caller that wants strict-mode parsing can wrap and catch.
    """


# ---------------------------------------------------------------------------
# G4 holding-key derivation (the heart of #99's idempotency story)
# ---------------------------------------------------------------------------


def derive_holding_key(
    issuer_name: str | None,
    asset_category: str | None,
    cusip: str | None,
    isin: str | None,
    lei: str | None,
) -> str:
    """Derive a content-stable holding key per design §0.2 Q-B Resolution + G4.

    Order: CUSIP -> ISIN -> LEI -> sha1(issuer_name||asset_category)[:16].

    A holding with both CUSIP and ISIN always keys on CUSIP — the deterministic
    waterfall is the whole point. Without it, two parses of the same XML could
    pick a different "primary id" depending on element order.
    """
    if cusip:
        cleaned = cusip.strip().upper()
        if cleaned and cleaned not in {"N/A", "0", "000000000", "NA"}:
            return cleaned
    if isin:
        cleaned = isin.strip().upper()
        if cleaned:
            return cleaned
    if lei:
        cleaned = lei.strip().upper()
        if cleaned:
            return cleaned
    # Fallback: content hash of issuer+asset_cat. 16 hex chars = 64 bits of
    # collision resistance, far more than needed for one filing's holdings.
    seed = f"{(issuer_name or '').strip().lower()}||{(asset_category or '').strip().lower()}"
    return hashlib.sha1(seed.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


def apply_lot_suffix(rows: list[NportHolding]) -> list[NportHolding]:
    """Append ``_lotN`` suffix to colliding holding_keys within one filing.

    Sort first by ``(issuer_name, identifier_presence_score)`` then suffix —
    that way the same content set produces the same suffixes across re-parses
    regardless of XML element walk order. The first occurrence keeps its bare
    key; the 2nd, 3rd, ... get ``_lot2``, ``_lot3``, ...
    """
    # Deterministic sort: stable across XML element ordering.
    def sort_key(h: NportHolding) -> tuple:
        # Lower presence_score = more concrete (cusip < isin < lei < hash-only).
        if h.get("cusip"):
            score = 0
        elif h.get("isin"):
            score = 1
        elif h.get("lei"):
            score = 2
        else:
            score = 3
        return (h.get("issuer_name") or "", score, h.get("holding_key") or "")

    sorted_rows = sorted(rows, key=sort_key)
    seen: dict[str, int] = {}
    out: list[NportHolding] = []
    for row in sorted_rows:
        base_key = row.get("holding_key") or ""
        if not base_key:
            # Defensive: shouldn't happen because derive_holding_key always
            # returns something; but if it did, skip the suffix logic.
            out.append(row)
            continue
        count = seen.get(base_key, 0)
        if count == 0:
            seen[base_key] = 1
            out.append(row)
        else:
            count += 1
            seen[base_key] = count
            new_row: NportHolding = dict(row)  # type: ignore[assignment]
            new_row["holding_key"] = f"{base_key}_lot{count}"
            out.append(new_row)
    return out


# ---------------------------------------------------------------------------
# Envelope splitter — finds the <XML>...</XML> body inside <SEC-DOCUMENT>
# ---------------------------------------------------------------------------


# Match the line-oriented envelope header. Tolerates trailing whitespace +
# either NPORT-P or NPORT-P/A. Capture the form type for is_amendment.
_TYPE_LINE = re.compile(rb"<TYPE>\s*(NPORT-P(?:/A)?)\b", re.IGNORECASE)

# Match the XML body — non-greedy so the FIRST </XML> closes it.
_XML_BLOCK = re.compile(rb"<XML>\s*(?P<body>.*?)\s*</XML>", re.DOTALL | re.IGNORECASE)


def _split_envelope(raw: bytes) -> tuple[bool, bytes | None]:
    """Return ``(is_amendment, xml_body_bytes_or_None)``.

    ``xml_body_bytes_or_None`` is None if we can't find a sensible XML block —
    a malformed filing.
    """
    type_match = _TYPE_LINE.search(raw)
    is_amendment = False
    if type_match:
        form_type = type_match.group(1).decode("ascii", errors="replace").upper()
        is_amendment = form_type.endswith("/A")
    xml_match = _XML_BLOCK.search(raw)
    if xml_match is None:
        return is_amendment, None
    return is_amendment, xml_match.group("body")


# ---------------------------------------------------------------------------
# XML field plucking — N-PORT-P uses a namespaced schema, but envelope-stripped
# bodies frequently arrive without xmlns declarations on inner elements. We
# walk the tree with tag-suffix matching (`localname`) so we don't depend on
# any particular xmlns prefix being present.
# ---------------------------------------------------------------------------


def _localname(tag: str) -> str:
    """Strip xmlns prefix from ``{ns}Name`` -> ``Name``."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _find_first(root: Element, *localnames: str) -> Element | None:
    """Find the first descendant with any of the given local tag names."""
    target = set(localnames)
    for el in root.iter():
        if _localname(el.tag) in target:
            return el
    return None


def _findall_invst_or_secs(root: Element) -> list[Element]:
    """Return every ``<invstOrSec>`` element regardless of namespace."""
    return [el for el in root.iter() if _localname(el.tag) == "invstOrSec"]


def _text_of(root: Element, *localnames: str) -> str | None:
    """Return the stripped text of the first child matching any local name."""
    el = _find_first(root, *localnames)
    if el is None or el.text is None:
        return None
    text = el.text.strip()
    return text or None


def _parse_date(text: str | None) -> date | None:
    """Parse an SEC date string (typically YYYY-MM-DD)."""
    if not text:
        return None
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_float(text: str | None) -> float | None:
    """Parse a numeric string tolerating commas and stray whitespace."""
    if not text:
        return None
    cleaned = text.replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_bool(text: str | None) -> bool:
    """Parse 'Y'/'N'/'true'/'false' booleans the SEC uses for flag fields."""
    if not text:
        return False
    return text.strip().upper() in {"Y", "YES", "TRUE", "1"}


# ---------------------------------------------------------------------------
# Public API: parse_submission_envelope
# ---------------------------------------------------------------------------


def _extract_filing_meta(
    root: Element,
    accession_number: str,
    source: str,
    is_amendment: bool,
) -> NportFiling:
    """Pull CIK / series_id / class_id / report_date out of the gen-info section."""
    filing: NportFiling = {
        "accession_number": accession_number,
        "source": source,
        "is_amendment": is_amendment,
    }
    cik = _text_of(root, "regCik", "filerCik", "cik")
    if cik:
        # Strip ANY leading zeros for join consistency, then re-pad to 10 to
        # match #89's thirteen_f_index convention.
        digits = re.sub(r"\D", "", cik) or "0"
        filing["cik"] = digits.zfill(10)
    filing["series_id"] = _text_of(root, "seriesId")
    filing["class_id"] = _text_of(root, "classId")
    filing["fund_name"] = _text_of(root, "seriesName", "regName")
    filing["report_date"] = _parse_date(_text_of(root, "repPdEnd", "reportingPeriodEnd"))
    filing["filing_date"] = _parse_date(_text_of(root, "filingDate"))
    filing["period_of_report"] = _text_of(root, "repPdEnd", "reportingPeriodEnd")
    return filing


def _extract_holding(
    invst: Element,
    accession_number: str,
) -> NportHolding:
    """Pull one ``<invstOrSec>`` element into an NportHolding row (pre-suffix)."""
    issuer_name = _text_of(invst, "name", "issuerName")
    asset_cat = _text_of(invst, "assetCat", "assetCategory")
    cusip = _text_of(invst, "cusip")
    isin = _text_of(invst, "isin")
    lei = _text_of(invst, "lei")
    ticker = _text_of(invst, "ticker")

    units = _parse_float(_text_of(invst, "balance", "units"))
    value_usd = _parse_float(_text_of(invst, "valUSD"))
    pct_nav = _parse_float(_text_of(invst, "pctVal", "percentageOfNetAssets"))
    payoff_direction = _text_of(invst, "payoffProfile")

    # Derivative flag: presence of <derivativeInfo> or its children -> True.
    derivative_flag = any(
        _localname(el.tag) in {"derivativeInfo", "fwdDeriv", "optionSwaption", "swapDeriv", "futrDeriv"}
        for el in invst.iter()
    )

    holding: NportHolding = {
        "accession_number": accession_number,
        "issuer_name": issuer_name,
        "ticker": ticker,
        "cusip": cusip,
        "isin": isin,
        "lei": lei,
        "asset_category": asset_cat,
        "units": units,
        "value_usd": value_usd,
        "pct_nav": pct_nav,
        "payoff_direction": payoff_direction,
        "derivative_flag": derivative_flag,
    }
    holding["holding_key"] = derive_holding_key(
        issuer_name=issuer_name,
        asset_category=asset_cat,
        cusip=cusip,
        isin=isin,
        lei=lei,
    )
    return holding


def parse_submission_envelope(
    raw: bytes,
    *,
    accession_number: str,
    source: str,
) -> tuple[NportFiling, list[NportHolding]]:
    """Parse a full SEC-DOCUMENT envelope -> (filing_meta, holdings).

    Public entry point. Never raises — on parse failure logs a WARNING and
    returns ``(NportFiling{accession_number, source, is_amendment=False}, [])``.
    """
    if not raw:
        logger.warning("parse_submission_envelope: empty input for %s", accession_number)
        return ({"accession_number": accession_number, "source": source, "is_amendment": False}, [])

    is_amendment, xml_body = _split_envelope(raw)
    if xml_body is None:
        logger.warning(
            "parse_submission_envelope: no <XML> block found for %s",
            accession_number,
        )
        return (
            {"accession_number": accession_number, "source": source, "is_amendment": is_amendment},
            [],
        )

    try:
        root = ET.fromstring(xml_body)  # noqa: S314 — SEC-controlled XML, no entity expansion risk
    except ET.ParseError as exc:
        logger.warning(
            "parse_submission_envelope: XML parse error for %s: %s",
            accession_number,
            exc,
        )
        return (
            {"accession_number": accession_number, "source": source, "is_amendment": is_amendment},
            [],
        )

    filing = _extract_filing_meta(root, accession_number, source, is_amendment)

    holdings: list[NportHolding] = [
        _extract_holding(invst, accession_number)
        for invst in _findall_invst_or_secs(root)
    ]
    holdings = apply_lot_suffix(holdings)

    return filing, holdings


def parse_xml_body_only(
    xml_body: bytes,
    *,
    accession_number: str,
    source: str,
    is_amendment: bool = False,
) -> tuple[NportFiling, list[NportHolding]]:
    """Test/integration helper: parse a raw XML body without the envelope.

    Some test fixtures want to exercise the XML walker without the
    line-oriented envelope; production callers should use
    ``parse_submission_envelope`` which handles both layers.
    """
    try:
        root = ET.fromstring(xml_body)  # noqa: S314
    except ET.ParseError as exc:
        logger.warning("parse_xml_body_only: parse error for %s: %s", accession_number, exc)
        return (
            {"accession_number": accession_number, "source": source, "is_amendment": is_amendment},
            [],
        )
    filing = _extract_filing_meta(root, accession_number, source, is_amendment)
    holdings = [_extract_holding(invst, accession_number) for invst in _findall_invst_or_secs(root)]
    holdings = apply_lot_suffix(holdings)
    return filing, holdings


__all__ = [
    "NportFiling",
    "NportHolding",
    "NportParseError",
    "apply_lot_suffix",
    "derive_holding_key",
    "parse_submission_envelope",
    "parse_xml_body_only",
]


# Suppress flake8 over-eager warnings about Any
_ = Any  # noqa: F841
