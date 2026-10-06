"""Bounded paid-provider MCP spot check with per-capability evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re

from fastmcp import Client


def _error_text(result) -> str:
    """Return normalized protocol error text without emitting provider details."""
    return " ".join(
        str(getattr(content, "text", "")) for content in result.content
    ).lower()


def _is_entitlement_error(error_text: str) -> bool:
    """Recognize only provider-plan denial language, not generic 403s."""
    entitlement_phrases = (
        "entitlement",
        "plan limit",
        "plan-limit",
        "upgrade plan",
        "premium endpoint",
        "subscription required",
    )
    return any(phrase in error_text for phrase in entitlement_phrases)


async def run(symbol: str, max_requests: int) -> dict:
    """Invoke at most two explicitly named FMP capabilities."""
    url = os.environ.get("OPENBB_MCP_URL", "").strip()
    token = os.environ.get("OPENBB_MCP_TOKEN", "").strip()
    if not url or not token:
        raise RuntimeError("Provider-live MCP URL and token are required")
    requests = [
        ("equity_price_quote", {"symbol": symbol, "provider": "fmp"}),
        (
            "equity_price_historical",
            {"symbol": symbol, "provider": "fmp", "start_date": "2026-01-02"},
        ),
    ][:max_requests]
    evidence = []
    async with Client(url, auth=token, name="provider-live-spot-check") as client:
        for tool, arguments in requests:
            result = await client.call_tool(tool, arguments, raise_on_error=False)
            verification = "live_call_passed"
            if result.is_error:
                error_text = _error_text(result)
                if not _is_entitlement_error(error_text):
                    raise RuntimeError(f"Unexpected MCP failure for {tool}")
                verification = "entitlement_error"
            evidence.append(
                {
                    "capability": tool,
                    "verification": verification,
                }
            )
    return {
        "contract_models": 181,
        "contract_verification": "not_run",
        "requests_used": len(requests),
        "spot_checks": evidence,
        "untested_entitlements": "unverified",
    }


def main() -> int:
    """Validate bounded inputs and print sanitized verification levels."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--max-requests", type=int, choices=(1, 2), required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Z]{1,10}", args.symbol):
        raise SystemExit("Symbol must be one uppercase public ticker")
    print(  # noqa: T201
        json.dumps(
            asyncio.run(run(args.symbol, args.max_requests)),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
