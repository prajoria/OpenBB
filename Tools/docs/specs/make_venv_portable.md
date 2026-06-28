# make_venv_portable.py — Spec

| | |
|---|---|
| **Category** | Infra utility |
| **Path** | `Tools/make_venv_portable.py` |
| **Writes** | `.venv_win/Lib/site-packages/*.pth` (rewritten in place) |

## Purpose

Rewrite the absolute paths that editable installs leave in `.pth` files inside
`.venv_win/Lib/site-packages` into **repo-relative** paths, so moving the repo
to a new drive / user / machine doesn't break every editable install.

## How it works

Python's `site` module joins each relative `.pth` line with the containing
site-packages directory. Site-packages lives four levels below the repo root
(`<repo>/.venv_win/Lib/site-packages`), so a target like
`<repo>/openbb_platform/extensions/techtrade` becomes
`../../../openbb_platform/extensions/techtrade`.

## CLI

```
.venv_win/Scripts/python.exe Tools/make_venv_portable.py
```

No flags. Prints how many lines were rewritten and any paths left untouched.

## Behavior

- **Idempotent** — lines already relative are left alone.
- Only paths **inside** the repo root are rewritten; anything pointing outside
  (system install, another project) is preserved verbatim.
- Handles both Windows (`DRIVE:/...`) and POSIX (`/...`) absolute paths;
  comparison is case-insensitive on Windows.
- Skips comment lines and `import ...` lines.

## Notes

- Run after `dev_install.py -e` if you plan to relocate the checkout.
- Pairs with the vendored `Tools/uv/` binaries for portable environment setup.
