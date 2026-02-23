"""
Run the OpenBB Platform API on port 6901 with HTTPS.

This is the standard OpenBB API — provides market data endpoints
(/api/v1/equity/price/quote, /api/v1/equity/price/historical, etc.)

The Portfolio App (port 6902) calls this API for live market data.

Usage:
    python portfolio_app/run_openbb_api.py
    python portfolio_app/run_openbb_api.py --port 6901
    python portfolio_app/run_openbb_api.py --no-ssl
"""

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Run OpenBB Platform API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6901)
    parser.add_argument("--no-ssl", action="store_true", default=False,
                        help="Disable HTTPS (use HTTP instead)")
    args = parser.parse_args()

    app_dir = Path(__file__).resolve().parent
    ssl_certfile = app_dir / "cert.pem"
    ssl_keyfile = app_dir / "key.pem"
    use_ssl = not args.no_ssl and ssl_certfile.exists() and ssl_keyfile.exists()
    scheme = "https" if use_ssl else "http"

    print(f"\n{'='*60}")
    print(f"  OpenBB Platform API starting on {scheme}://{args.host}:{args.port}")
    print(f"  Docs: {scheme}://{args.host}:{args.port}/docs")
    if use_ssl:
        print(f"  SSL: {ssl_certfile}")
    print(f"{'='*60}\n")

    # Import the OpenBB Platform API app and launch via uvicorn directly
    # (bypasses openbb-api CLI which has a dash/underscore bug with SSL args)
    import uvicorn

    kwargs = dict(
        host=args.host,
        port=args.port,
    )
    if use_ssl:
        kwargs["ssl_certfile"] = str(ssl_certfile)
        kwargs["ssl_keyfile"] = str(ssl_keyfile)

    uvicorn.run("openbb_platform_api.main:app", **kwargs)


if __name__ == "__main__":
    main()
