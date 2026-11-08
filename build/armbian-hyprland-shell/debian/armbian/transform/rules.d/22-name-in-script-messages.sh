# Show "Armbian" for the product name in the messages of the commands in
# bin/: echo, printf, warnings, notifications, the update terminal title.
# Only output lines. grep patterns (EFI boot labels) and code keep the name.
# Skipped: omarchy-upgrade-to-quattro ("Omarchy 3", "Omarchy quattro" are
# upstream versions) and the omarchy-dev-* developer tools.
python3 - <<- 'EOF_PY'
import pathlib
import re
import sys

output = re.compile(r"^\s*(echo|printf|warn|die|error|fail|notify-send|omarchy-notification-send|gum|omarchy_log_line)\b")
name = re.compile(r"\bOmarchy\b")
changed = {}
for path in sorted(pathlib.Path("bin").iterdir()):
    if not path.is_file() or path.name == "omarchy-upgrade-to-quattro" or path.name.startswith("omarchy-dev-"):
        continue
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        continue
    count = 0
    for i, line in enumerate(lines):
        if "grep" in line or not name.search(line):
            continue
        if output.match(line) or "--title=Omarchy" in line:
            lines[i] = name.sub("Armbian", line)
            count += 1
    if count:
        path.write_text("".join(lines), encoding="utf-8")
        changed[path.name] = count
# The update free-space check names the product: without it, upstream changed.
if "omarchy-update-requires-free-space" not in changed or sum(changed.values()) < 20:
    sys.exit(f"transform: script messages changed upstream ({sum(changed.values())} lines)")
print(f"transform: {sum(changed.values())} script messages renamed in {len(changed)} commands")
EOF_PY
