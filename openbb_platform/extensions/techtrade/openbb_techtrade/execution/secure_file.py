"""Cross-platform owner-only permissions for execution audit storage."""

from __future__ import annotations

import ctypes
import os
import stat
from contextlib import suppress
from pathlib import Path


def secure_owner_only(path: Path, *, directory: bool) -> None:
    """Apply owner-only access, raising when the platform cannot enforce it."""
    if os.name == "nt":
        _set_windows_owner_dacl(path, directory=directory)
        return
    mode = 0o700 if directory else 0o600
    path.chmod(mode)
    actual = stat.S_IMODE(path.stat().st_mode)
    if actual != mode:
        raise PermissionError(
            f"owner-only permissions were not enforced for {path.name!r}"
        )


def prepare_private_audit_directory(path: Path, audit_filename: str) -> None:
    """Create or verify a dedicated audit directory, then lock it to its owner."""
    marker = path / ".openbb-execution-audit"
    allowed = {
        audit_filename,
        f"{audit_filename}-journal",
        f"{audit_filename}-shm",
        f"{audit_filename}-wal",
    }
    unrelated = (
        [item for item in path.iterdir() if item.name not in allowed]
        if path.exists() and not marker.exists()
        else []
    )
    if unrelated:
        raise PermissionError(
            "execution audit database requires a dedicated private directory"
        )
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    secure_owner_only(path, directory=True)
    marker.touch(exist_ok=True)
    secure_owner_only(marker, directory=False)
    for name in allowed:
        candidate = path / name
        if candidate.exists():
            with suppress(FileNotFoundError):
                secure_owner_only(candidate, directory=False)


def _set_windows_owner_dacl(path: Path, *, directory: bool) -> None:
    """Set a protected DACL granting generic-all access only to the owner."""
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    descriptor = ctypes.c_void_p()
    convert = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    convert.restype = ctypes.c_int
    sddl = "D:P(A;OICI;GA;;;OW)" if directory else "D:P(A;;GA;;;OW)"
    if not convert(sddl, 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        set_security = advapi32.SetFileSecurityW
        set_security.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        set_security.restype = ctypes.c_int
        security_information = 0x00000004 | 0x80000000
        if not set_security(str(path), security_information, descriptor):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.LocalFree(descriptor)
