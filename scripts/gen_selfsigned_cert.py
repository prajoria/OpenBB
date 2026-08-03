#!/usr/bin/env python
"""Generate a self-signed TLS certificate for local OpenBB Workspace backends.

OpenBB Workspace (https://pro.openbb.co) talks to custom backends over HTTPS.
For local development the ``portfolio`` extension backend is served at
``https://127.0.0.1:6902`` (see ``openbb_platform/extensions/portfolio/README.md``),
which needs a certificate + key pair. Those files are **per-machine dev
artifacts** — they are gitignored and generated on demand by this helper
(invoked automatically by ``scripts/run_portfolio_backend.ps1``).

The certificate carries Subject Alternative Names for ``localhost``,
``127.0.0.1`` and ``::1`` so the same pair works for loopback over IPv4/IPv6.

Usage::

    python scripts/gen_selfsigned_cert.py \
        --cert portfolio_app/cert.pem \
        --key  portfolio_app/key.pem

Idempotent: if both files already exist and ``--force`` is not passed, the
script is a no-op (exit 0) so it is cheap to call on every server start.
"""

from __future__ import annotations

import argparse
import datetime
import ipaddress
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cert",
        default="portfolio_app/cert.pem",
        help="Output path for the PEM certificate (default: portfolio_app/cert.pem).",
    )
    parser.add_argument(
        "--key",
        default="portfolio_app/key.pem",
        help="Output path for the PEM private key (default: portfolio_app/key.pem).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=825,
        help="Validity window in days (default: 825 — the CA/Browser Forum max for leaf certs).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even if both cert and key already exist.",
    )
    return parser


def generate(cert_path: Path, key_path: Path, days: int) -> None:
    """Write a fresh self-signed cert + key pair to the given paths."""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise SystemExit(
            "cryptography is required to generate a self-signed certificate.\n"
            "Install it into your environment first, e.g.:\n"
            "    python -m pip install cryptography"
        ) from exc

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "OpenBB Portfolio Dev"),
        ]
    )

    san = x509.SubjectAlternativeName(
        [
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            x509.IPAddress(ipaddress.ip_address("::1")),
        ]
    )

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=days))
        .add_extension(san, critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)

    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and generate the cert/key pair unless it already exists."""
    args = _build_parser().parse_args(argv)
    cert_path = Path(args.cert)
    key_path = Path(args.key)

    if cert_path.exists() and key_path.exists() and not args.force:
        print(
            f"Certificate already present: {cert_path} / {key_path} (use --force to regenerate)."
        )
        return 0

    generate(cert_path, key_path, args.days)
    print(
        f"Generated self-signed certificate:\n  cert: {cert_path}\n  key:  {key_path}"
    )
    print(
        "This is a DEV-ONLY self-signed cert. Your browser will warn on first use -- "
        "accept the exception for 127.0.0.1, or trust the cert in your OS store."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
