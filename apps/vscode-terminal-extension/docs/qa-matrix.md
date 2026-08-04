# OpenBB Terminal — Pre-Release QA Matrix

Run this matrix before every `v0.x` release tag. Each cell records whether
the layout renders correctly under the given theme and data mode. Any
failed cell blocks the release until fixed or explicitly waived on the
release PR.

Modes:

- **fixture**: extension launches with bundled `fixtures/widgets.sample.json`
- **live**: local `openbb-api` back-end running against real endpoints

| Layout              | Dark (fixture)                                 | Dark (live)                                     | Light (fixture)                                 | Light (live)                                    | HC (fixture)                                    | HC (live)                                       |
| ------------------- | ---------------------------------------------- | ----------------------------------------------- | ----------------------------------------------- | ----------------------------------------------- | ----------------------------------------------- | ----------------------------------------------- |
| Portfolio Overview  | [ ] all widgets mount, no CSP errors            | [ ] live data populates, no 4xx/5xx             | [ ] tokens flip cleanly on theme change         | [ ] live data populates, no 4xx/5xx             | [ ] contrast ≥ WCAG AA on every widget          | [ ] live data populates, no 4xx/5xx             |
| Trading Desk        | [ ] order ticket + positions + tape all render | [ ] paper buy/sell round-trips                  | [ ] tokens flip cleanly on theme change         | [ ] paper buy/sell round-trips                  | [ ] focus outlines visible everywhere           | [ ] paper buy/sell round-trips                  |
| Portfolio Risk      | [ ] all widgets mount, no CSP errors            | [ ] live risk endpoints resolve                 | [ ] tokens flip cleanly on theme change         | [ ] live risk endpoints resolve                 | [ ] contrast ≥ WCAG AA on every widget          | [ ] live risk endpoints resolve                 |
| Chart Focus         | [ ] chart canvas visible, hover works          | [ ] live OHLCV populates                        | [ ] tokens flip cleanly on theme change         | [ ] live OHLCV populates                        | [ ] chart axes readable under HC palette        | [ ] live OHLCV populates                        |
| Equity Deep Dive    | [ ] all widgets mount, no CSP errors            | [ ] live equity endpoints resolve               | [ ] tokens flip cleanly on theme change         | [ ] live equity endpoints resolve               | [ ] contrast ≥ WCAG AA on every widget          | [ ] live equity endpoints resolve               |

**30 cells total** = 5 layouts × 3 themes × 2 modes.

---

Signed off: _____________________ Date: ___________
