"""
`pe replay <name>` — imports `recordings/<name>.py` and calls its `run(page,
download_dir)` function against the persistent browser context.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

from portfolio_export.config import Config, dated_download_dir
from portfolio_export.session import persistent_context
from portfolio_export.tagger import TaggerError, tag_csv


class ReplayError(RuntimeError):
    pass


def _resolve_recording(cfg: Config, name: str) -> Path:
    """Search user_recordings_dir first, then bundled_recordings_dir."""
    candidates = [
        cfg.user_recordings_dir / f"{name}.py",
        cfg.bundled_recordings_dir / f"{name}.py",
    ]
    for c in candidates:
        if c.exists():
            return c
    searched = "\n  ".join(str(c) for c in candidates)
    raise ReplayError(
        f"Recording '{name}' not found. Searched:\n  {searched}\n"
        f"Run `pe record {name} --url ...` first."
    )


def _load_recording(cfg: Config, name: str):
    """Load a recording module from user_recordings_dir or bundled_recordings_dir."""
    module_path = _resolve_recording(cfg, name)
    spec = importlib.util.spec_from_file_location(
        f"portfolio_export_recordings_{name}", module_path
    )
    if spec is None or spec.loader is None:
        raise ReplayError(f"Failed to build import spec for {module_path}.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if not hasattr(module, "run"):
        raise ReplayError(
            f"Recording {module_path} does not define a top-level `run(page, download_dir)` function."
        )
    module.__source_path__ = module_path
    return module


def run_replay(cfg: Config, name: str, *, user_id: str | None = None) -> int:
    module = _load_recording(cfg, name)
    download_dir = dated_download_dir(cfg.download_dir)

    print(f"[replay] recording        : {name}")
    print(f"[replay] source           : {module.__source_path__}")
    print(f"[replay] profile dir      : {cfg.profile_dir}")
    print(f"[replay] download dir     : {download_dir}")
    print(f"[replay] headless         : {cfg.headless}")
    if user_id:
        print(f"[replay] auto-tag user_id : {user_id}")

    with persistent_context(cfg, download_dir=download_dir) as ctx:
        page = ctx.new_page()
        try:
            result = module.run(page, str(download_dir))
        except Exception as exc:  # surface but keep browser closing cleanly
            print(f"[replay] ERROR: recording raised {type(exc).__name__}: {exc}")
            raise

    files = result or []
    if files:
        print(f"[replay] downloaded {len(files)} file(s):")
        for f in files:
            print(f"  - {f}")
    else:
        print("[replay] no files reported downloaded (recording returned empty list).")

    if user_id and files:
        tagged: list[str] = []
        for f in files:
            p = Path(f)
            if p.suffix.lower() != ".csv":
                continue
            try:
                out, n = tag_csv(p, user_id, delete_original=True)
            except TaggerError as exc:
                print(f"[replay] tag skipped for {p.name}: {exc}")
                continue
            tagged.append(f"{out}  ({n} rows)")
        if tagged:
            print(f"[replay] auto-tagged {len(tagged)} csv file(s):")
            for t in tagged:
                print(f"  - {t}")

    return 0
