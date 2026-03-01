"""
Run the Portfolio App on port 6903.

Usage:
    python portfolio_app/run_portfolio.py
    python portfolio_app/run_portfolio.py --port 6903
"""

import argparse
import os
import sys
from pathlib import Path

# Ensure portfolio_app/src directory is on sys.path so modules are importable
app_dir = Path(__file__).resolve().parent / "src"
if str(app_dir) not in sys.path:
    sys.path.insert(0, str(app_dir))


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
