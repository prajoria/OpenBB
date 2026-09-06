# local-ci PowerShell wrapper (Windows). Invokes the same Python entrypoint
# as ci/local-ci does on POSIX. All argv passthrough via $args.

$ErrorActionPreference = 'Stop'

# Resolve repo root: this script lives at ci/local-ci.ps1
$here = Split-Path -Parent $PSCommandPath
$repoRoot = Split-Path -Parent $here

# Prefer the checked-in .venv_win python if present; otherwise fall back to python on PATH.
$venvPy = Join-Path $repoRoot '.venv_win\Scripts\python.exe'
$py = if (Test-Path $venvPy) { $venvPy } else { 'python' }

# Put ci/ on sys.path so `import local_ci` works without installing.
$env:PYTHONPATH = "$here;$env:PYTHONPATH"

& $py -m local_ci @args
exit $LASTEXITCODE
