"""
Run the Portfolio App on port 6903.

Usage:
    python portfolio_app/run_portfolio.py
    python portfolio_app/run_portfolio.py --port 6903
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Ensure portfolio_app/src directory is on sys.path so modules are importable
app_dir = Path(__file__).resolve().parent / "src"
if str(app_dir) not in sys.path:
    sys.path.insert(0, str(app_dir))

# ── Logging setup ────────────────────────────────────────────────────────────
_log_dir = Path(__file__).resolve().parent / "logs"
_log_dir.mkdir(exist_ok=True)

# New timestamped file for every restart — never overwrites previous runs
_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
_log_file = _log_dir / f"portfolio_app_{_ts}.log"

# Keep a rolling "latest" symlink/copy so tooling can always tail the same name
_latest_link = _log_dir / "portfolio_app_latest.log"
try:
    if _latest_link.exists() or _latest_link.is_symlink():
        _latest_link.unlink()
    _latest_link.symlink_to(_log_file.name)   # relative symlink inside logs/
except OSError:
    pass  # Windows may lack symlink privileges — skip silently

_fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s | %(message)s")

_file_handler = logging.FileHandler(_log_file, encoding="utf-8")
_file_handler.setFormatter(_fmt)
_file_handler.setLevel(logging.DEBUG)

_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(_fmt)
_console_handler.setLevel(logging.INFO)

logging.basicConfig(level=logging.DEBUG, handlers=[_file_handler, _console_handler])
# Quiet down noisy third-party loggers in the file too
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
# ─────────────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Run Portfolio App")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6903)
    parser.add_argument("--reload", action="store_true", default=False)
    parser.add_argument("--no-ssl", action="store_true", default=False,
                        help="Disable HTTPS (use HTTP instead)")
    args = parser.parse_args()

    os.environ["PORTFOLIO_DATABASE"] = "openbb_fmp_cache_test"

    import uvicorn

    portfolio_dir = app_dir.parent  # portfolio_app/
    ssl_certfile = portfolio_dir / "cert.pem"
    ssl_keyfile = portfolio_dir / "key.pem"
    use_ssl = not args.no_ssl and ssl_certfile.exists() and ssl_keyfile.exists()
    scheme = "https" if use_ssl else "http"

    print(f"\n{'='*60}")
    print(f"  Portfolio App starting on {scheme}://{args.host}:{args.port}")
    print(f"  OpenBB API expected on {os.getenv('OPENBB_API_URL', 'https://127.0.0.1:6902')}")
    print(f"  Database: {os.getenv('PORTFOLIO_DATABASE')}")
    print(f"  Docs: {scheme}://{args.host}:{args.port}/docs")
    print(f"  Log file: {_log_file}")
    # Show the 3 most recent log files for easy reference
    recent = sorted(_log_dir.glob("portfolio_app_2*.log"), reverse=True)[:3]
    if len(recent) > 1:
        print(f"  Recent logs:")
        for lf in recent:
            marker = " << current" if lf == _log_file else ""
            print(f"    {lf.name}{marker}")
    if use_ssl:
        print(f"  SSL: {ssl_certfile}")
    print(f"{'='*60}\n")

    kwargs = dict(
        host=args.host,
        port=args.port,
        reload=args.reload,
        app_dir=str(app_dir),
    )
    if use_ssl:
        kwargs["ssl_certfile"] = str(ssl_certfile)
        kwargs["ssl_keyfile"] = str(ssl_keyfile)

    uvicorn.run("main:app", **kwargs)


if __name__ == "__main__":
    main()
