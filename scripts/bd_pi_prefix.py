"""Rename every portfolio-intel bd item to prefix its title with [portfolio]."""
import subprocess, sys

EPIC = "OpenBBTechnical-qy83"
PHASES = [f"{EPIC}.{i}" for i in range(1, 6)]

# Collect all IDs: epic + phases + children (dot-child of each phase)
ids = [EPIC] + PHASES
# The task IDs are qy83.<phase>.<n>. Use bd list --label to enumerate.
r = subprocess.run(
    ["bd", "list", "-l", "portfolio-intel", "--flat", "-n", "200"],
    capture_output=True, encoding="utf-8", errors="replace",
)
if r.returncode != 0:
    print(r.stderr); sys.exit(1)

# Parse: lines look like "○ OpenBBTechnical-qy83.4.21 [● P0] ... - <title>"
import re
line_re = re.compile(r"^[○●] +(\S+) +\[.*?\] +\[.*?\] +\[.*?\] +- +(.*)$")
items = []
for line in r.stdout.splitlines():
    m = line_re.match(line)
    if m:
        items.append((m.group(1), m.group(2)))

print(f"Found {len(items)} items to consider")

renamed = skipped = failed = 0
for iid, title in items:
    if title.startswith("[portfolio]"):
        skipped += 1
        continue
    new = f"[portfolio] {title}"
    r = subprocess.run(
        ["bd", "update", iid, "--title", new],
        capture_output=True, encoding="utf-8", errors="replace",
    )
    if r.returncode == 0:
        renamed += 1
        print(f"  ok  {iid}  {new[:90]}")
    else:
        failed += 1
        print(f"  FAIL {iid}: {r.stderr.strip()[:200]}", file=sys.stderr)

print(f"\nRenamed {renamed}, skipped {skipped}, failed {failed}")
