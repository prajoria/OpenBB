"""``openbb-pine`` click CLI — entry point for the doctor + version banner.

Per D3 §10 + PRD §16.4:

* ``--version`` prints a two-line banner whose **first line** is the literal
  ``POWERED_BY_FULL`` string (§2.6 attribution surface #4).
* ``doctor`` runs the nine D3 §10.2 checks via the shared ``diagnostics``
  module and renders them as ``[OK]`` / ``[WARN]`` / ``[FAIL]`` lines.

Exit-code contract (D3 §10.1):

* ``0`` — all checks passed (WARN does not fail).
* ``1`` — at least one check FAILed (normal failure).
* ``2`` — pre-flight error: the harness itself could not run.

The CLI shells through to ``openbb_pine.diagnostics.run_all_checks`` so the
exact same code path also powers ``obb.pine.about()`` (§3 + D3 §10.6).
"""

from __future__ import annotations

import sys

import click

from openbb_pine.attribution import POWERED_BY_FULL
from openbb_pine.diagnostics import CheckResult, run_all_checks

# CLI-side mapping from lowercase status to the literal stdout tag.
# Defined as a module constant so the tests can introspect / extend if
# additional severities are ever added.
_TAG_FOR_STATUS = {
    "ok": "[OK]",
    "warn": "[WARN]",
    "fail": "[FAIL]",
}


def _reconfigure_stdio_for_unicode() -> None:
    """Force UTF-8 on stdout/stderr so the ``→`` fix-hint arrow renders.

    Windows ``cmd.exe`` defaults to cp1252, which cannot encode the U+2192
    arrow used by D3 §10.4 fix-hint output. We reconfigure both streams at
    CLI startup (idempotent; no-op on non-Windows terminals already on UTF-8).
    ``CliRunner`` in the test suite uses StringIO and is unaffected.
    """
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower()
        if enc in ("utf-8", "utf8"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):  # pragma: no cover - exotic streams
            pass


@click.group()
@click.version_option(
    package_name="openbb-extension-pine",
    message=f"{POWERED_BY_FULL}\n%(prog)s %(version)s",
)
def cli() -> None:
    """openbb-pine -- Pine Script compatibility CLI for OpenBB."""
    _reconfigure_stdio_for_unicode()


@cli.command()
@click.option(
    "--allow-byo-only",
    is_flag=True,
    default=False,
    help=(
        "Degrade FMP checks (api key, reachability) from FAIL to WARN. "
        "Use for BYO-OHLCV-only installs that never call request.security "
        "or syminfo.* (D3 §10 + PRD §16.4)."
    ),
)
def doctor(allow_byo_only: bool) -> None:
    """Run install / runtime diagnostics for the pine extension.

    Exit codes: 0 = all clean, 1 = at least one FAIL, 2 = pre-flight error.
    """
    try:
        results: list[CheckResult] = run_all_checks(allow_byo_only=allow_byo_only)
    except Exception as exc:
        click.echo(f"[PRE-FLIGHT ERROR] {exc}", err=True)
        sys.exit(2)

    any_fail = False
    for r in results:
        tag = _TAG_FOR_STATUS.get(r.status, f"[{r.status.upper()}]")
        click.echo(f"{tag} {r.name}: {r.message}")
        if r.fix_hint:
            click.echo(f"        → {r.fix_hint}")
        if r.status == "fail":
            any_fail = True

    if any_fail:
        n_failed = sum(1 for r in results if r.status == "fail")
        click.echo(f"{n_failed} check(s) failed.")
        sys.exit(1)

    click.echo("All checks passed.")
    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover - module-as-script entry
    cli()
