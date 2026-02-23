# Portfolio App — Standalone Backend
#
# This app runs as a *separate* service from the OpenBB Platform API.
# It queries the MySQL database for Portfolio_Positions data and can
# also proxy requests to the OpenBB API for market data enrichment.
#
# Architecture:
#   ┌──────────────┐       ┌──────────────────┐
#   │  OpenBB API  │ :6900 │  Portfolio App    │ :6901
#   │  (market     │◄──────│  (positions,      │
#   │   data)      │ httpx │   allocation,     │
#   └──────────────┘       │   cost basis)     │
#                          └──────────────────┘
#                                  ▲
#                                  │
#                          ┌──────────────────┐
#                          │  OpenBB Workspace │
#                          │  (widgets.json)   │
#                          └──────────────────┘
