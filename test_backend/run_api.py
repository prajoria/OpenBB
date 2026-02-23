"""
Launch OpenBB Platform API from source with the custom backend.

This script bootstraps sys.path so that openbb_core and openbb_platform_api
are importable directly from the repo source tree — no pip install needed.

Usage:
    python test_backend/run_api.py [--port 6900] [--ssl]

Equivalent to:
    openbb-api --app test_backend/main.py
"""

import os
import sys

# ── Encoding fix for Windows ──────────────────────────────────────────────── #
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Resolve project root (one level up from this file) ────────────────────── #
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)

# ── Bootstrap source packages onto sys.path ───────────────────────────────── #
SOURCE_PATHS = [
    "openbb_platform/core",
    "openbb_platform/platform",
    "openbb_platform/extensions/platform_api",
    "openbb_platform/providers/fmp_cached",
    "openbb_platform/providers/fmp",
]

# Add all extensions
extensions_root = os.path.join(PROJECT_ROOT, "openbb_platform", "extensions")
if os.path.isdir(extensions_root):
    for d in os.listdir(extensions_root):
        full = os.path.join(extensions_root, d)
        if os.path.isdir(full):
            SOURCE_PATHS.append(os.path.relpath(full, PROJECT_ROOT))

# Add all providers
providers_root = os.path.join(PROJECT_ROOT, "openbb_platform", "providers")
if os.path.isdir(providers_root):
    for d in os.listdir(providers_root):
        full = os.path.join(providers_root, d)
        if os.path.isdir(full):
            SOURCE_PATHS.append(os.path.relpath(full, PROJECT_ROOT))

for p in SOURCE_PATHS:
    abs_p = os.path.join(PROJECT_ROOT, p)
    if abs_p not in sys.path:
        sys.path.insert(0, abs_p)

# ── Environment variables ─────────────────────────────────────────────────── #
os.environ["FMP_CACHE_AUTO_CREATE_DB"] = "false"
os.environ["FMP_CACHE_TEST_MODE"] = "true"

# ── Parse our own args, then hand the rest to openbb-api via sys.argv ────── #
import argparse

parser = argparse.ArgumentParser(description="Launch OpenBB API from source")
parser.add_argument("--port", type=int, default=6900, help="Port (default: 6900)")
parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
parser.add_argument("--ssl", action="store_true", help="Enable HTTPS with self-signed certs")
parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
parser.add_argument("--no-build", action="store_true", help="Skip widget auto-build")
parser.add_argument("--editable", action="store_true", help="Hot-reload widgets.json from disk")
parser.add_argument(
    "--widgets-json", default=None,
    help="Path to static widgets.json (implies --editable --no-build)",
)
parser.add_argument("--apps-json", default=None, help="Path to apps.json")

args = parser.parse_args()

# Build sys.argv for openbb_platform_api.main's parse_args()
# Use relative path — import_app() joins with CWD, and absolute Windows paths
# (e.g. I:\...) break because they don't start with "/" on Windows.
app_path = "test_backend/main.py"
sys.argv = ["openbb-api", "--app", app_path, "--host", args.host, "--port", str(args.port)]

if args.ssl:
    sys.argv += ["--ssl-certfile", "test_backend/cert.pem", "--ssl-keyfile", "test_backend/key.pem"]

if args.reload:
    sys.argv.append("--reload")
if args.no_build:
    sys.argv.append("--no-build")
if args.editable:
    sys.argv.append("--editable")
if args.widgets_json:
    sys.argv += ["--widgets-json", args.widgets_json]
if args.apps_json:
    sys.argv += ["--apps-json", args.apps_json]

# ── Launch ─────────────────────────────────────────────────────────────────── #
print(f"Launching OpenBB API from source: {' '.join(sys.argv)}")
print(f"Project root: {PROJECT_ROOT}")
print(f"Custom backend: {app_path}")
print()

from openbb_platform_api.main import main

main()
