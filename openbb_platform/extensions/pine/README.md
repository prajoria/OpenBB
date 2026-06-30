# openbb-extension-pine

Pine Script compatibility for the OpenBB Platform. This extension exposes the
public `obb.pine.*` surface: a Pine v5/v6 source compiler, a runtime that
executes the compiled module over OHLCV from FMP (or a user-supplied
DataFrame), and the supporting catalog, health, and `about` commands. The
current revision is the **scaffold** (bead `OpenBBTechnical-0e9.4.2`,
GH issue #106 leg L0.2): the package installs cleanly and `obb.pine.about()`
returns the expected metadata, but the compiler, runtime, widgets, and MCP
tools are P1+ work and not yet present.

## Status

Scaffold only -- the lazy sub-router include in `pine_router._include_subrouters`
silently skips every routing module at this point because none of them exist
yet. Tracking issues: see the `project:pine` label on
[prajoria/OpenBB](https://github.com/prajoria/OpenBB/issues?q=label%3Aproject%3Apine).

---

## Trademark disclaimer

*Pine Script (TM) is a trademark of TradingView, Inc. This project
(`openbb-extension-pine`) is an independent, clean-room implementation that
aims to provide compatibility with the Pine Script language concept inside the
Python and OpenBB ecosystems. We are not affiliated with, endorsed by, or
sponsored by TradingView or PyneSys LLC.*

*Portions of the runtime are vendored from PyneCore (TM) (Apache-2.0,
copyright PYNESYS LLC). PyneCore (TM) and PyneComp (TM) are trademarks of
PYNESYS LLC. Powered by PyneSys (https://pynesys.io).*

---

Powered by PyneSys (https://pynesys.io)
