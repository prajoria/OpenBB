"""portfolio_utils — ad-hoc portfolio-adjacent scripts.

Rehomed from the top-level ``Tools/`` directory (see gh-1628). Each
module here is a stand-alone script/CLI:

- ``build_sp500_constituents`` — S&P 500 membership snapshot builder
- ``enrich_cusip_figi`` — CUSIP → FIGI enrichment via OpenFIGI
- ``export_basket_weight_comparison`` — basket weight vs benchmark comparison
- ``fetch_position_history`` — brokerage position history collector
- ``ingest_sec_13f`` — 13F filings ingest
- ``load_espp_plan`` — ESPP plan calculator
- ``make_venv_portable`` — venv portable-fication helper
- ``mortgage_amortization`` — mortgage amort schedule
- ``parse_fidelity_positions`` — Fidelity Positions CSV parser
- ``populate_cusip_map`` — CUSIP map builder
- ``populate_market_holidays`` — market holidays table populator
- ``portfolio_stats`` — portfolio statistics summary
- ``refresh_etf_holdings_cache`` — ETF holdings cache refresher
- ``share_cost_basis`` — cost-basis helpers

Sub-packages:
- ``quant_scraper`` — TOML-configured quant strategy scraper
"""
