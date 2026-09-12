"""Cross-platform owner-only permissions for execution audit storage."""

from __future__ import annotations

import ctypes
import os
import stat
from contextlib import suppress
from pathlib import Path


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("sid", ctypes.c_void_p), ("attributes", ctypes.c_uint32)]


class _TokenUser(ctypes.Structure):
    _fields_ = [("user", _SidAndAttributes)]


def secure_owner_only(path: Path, *, directory: bool) -> None:
    """Apply owner-only access, raising when the platform cannot enforce it."""
    if not _path_owned_by_current_user(path):
        raise PermissionError(
            f"execution audit path {path.name!r} is not owned by the current identity"
        )
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
    if not path.is_absolute() or path == Path.cwd() or path.parent == path:
        raise PermissionError(
            "execution audit database requires an absolute dedicated directory"
        )
    marker = path / ".openbb-execution-audit"
    for component in (path, *path.parents):
        if component.exists() and _is_link(component):
            raise PermissionError("execution audit path must not contain links")
    allowed = {
        marker.name,
        audit_filename,
        f"{audit_filename}-journal",
        f"{audit_filename}-shm",
        f"{audit_filename}-wal",
    }
    unrelated = (
        [item for item in path.iterdir() if item.name not in allowed]
        if path.exists()
        else []
    )
    if unrelated:
        raise PermissionError(
            "execution audit database requires a dedicated private directory"
        )
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    secure_owner_only(path, directory=True)
    if _is_link(marker):
        raise PermissionError("execution audit marker must not be a link")
    marker.touch(exist_ok=True)
    secure_owner_only(marker, directory=False)
    for name in allowed:
        candidate = path / name
        if _is_link(candidate):
            raise PermissionError("execution audit files must not be links")
        if candidate.exists():
            with suppress(FileNotFoundError):
                secure_owner_only(candidate, directory=False)
    database_path = path / audit_filename
    if os.name == "nt":
        database_path.touch(exist_ok=True)
    else:
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(database_path, flags, 0o600)
        os.close(descriptor)
    secure_owner_only(database_path, directory=False)


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = os.lstat(path).st_file_attributes
    except (AttributeError, FileNotFoundError):
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _path_owned_by_current_user(path: Path) -> bool:
    if os.name != "nt":
        get_effective_user_id = getattr(os, "geteuid")
        return path.stat(follow_symlinks=False).st_uid == get_effective_user_id()
    return _windows_path_owned_by_current_user(path)


def _windows_path_owned_by_current_user(path: Path) -> bool:
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    owner_sid = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    get_owner = advapi32.GetNamedSecurityInfoW
    get_owner.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    get_owner.restype = ctypes.c_uint32
    result = get_owner(
        str(path),
        1,
        0x00000001,
        ctypes.byref(owner_sid),
        None,
        None,
        None,
        ctypes.byref(descriptor),
    )
    if result:
        raise ctypes.WinError(result)
    token = ctypes.c_void_p()
    try:
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        open_token = advapi32.OpenProcessToken
        open_token.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        open_token.restype = ctypes.c_int
        if not open_token(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
            raise ctypes.WinError(ctypes.get_last_error())
        token_info = advapi32.GetTokenInformation
        token_info.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        token_info.restype = ctypes.c_int
        required = ctypes.c_uint32()
        token_info(token, 1, None, 0, ctypes.byref(required))
        if not required.value:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_string_buffer(required.value)
        if not token_info(token, 1, buffer, required.value, ctypes.byref(required)):
            raise ctypes.WinError(ctypes.get_last_error())
        token_user = ctypes.cast(buffer, ctypes.POINTER(_TokenUser)).contents
        equal_sid = advapi32.EqualSid
        equal_sid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        equal_sid.restype = ctypes.c_int
        return bool(equal_sid(owner_sid, token_user.user.sid))
    finally:
        if token:
            kernel32.CloseHandle(token)
        if descriptor:
            kernel32.LocalFree(descriptor)


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
