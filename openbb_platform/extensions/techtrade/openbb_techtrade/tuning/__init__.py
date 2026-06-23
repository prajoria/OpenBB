"""techtrade tuning: per-segment indicator-period optimisation (PRD §12.4, issue #83).

Behind the ``[tuneta]`` optional extra. ``obb.techtrade.tune(segment, ...)`` proposes
better indicator periods for a GICS sector via tuneta, gates the candidate through
#82's ``validate(...)`` (only ``verdict == "robust"`` persists), and writes accepted
configs to ``~/.openbb_platform/techtrade_tuned.json`` so the panel builder picks
them up transparently on the next ``scan`` / ``plan`` / ``signals``.

Module map:

- :mod:`openbb_techtrade.tuning.tuned_defaults` -- JSON read/write + mtime cache +
  contextvar override (the §5.3 W2 mechanism). The ONLY module imported by
  ``engine.indicators`` on the hot path; safe to import without ``tuneta``.
- :mod:`openbb_techtrade.tuning.sector_ohlcv` -- pool a segment's universe into the
  ``(date, symbol)``-indexed OHLCV DataFrame tuneta consumes (L4).
- :mod:`openbb_techtrade.tuning.tuneta_adapter` -- the ONLY module importing
  ``tuneta``; lazy ``_require_tuneta`` + knob table + column-name parser (L6).
- :mod:`openbb_techtrade.tuning.tune_router` -- the ``obb.techtrade.tune`` command.
"""
