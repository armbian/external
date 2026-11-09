# Reset Computer: removed from the menu. It needs the @factory snapshot of
# the Omarchy ISO installer and Limine. Armbian images have neither.
. "$TRANSFORM_LIB"

python3 - <<'PY'
import sys
path = "default/omarchy/omarchy-menu.jsonc"
lines = open(path, encoding="utf-8").read().split("\n")
key = '"setup.reset":'
found = sum(1 for l in lines if l.lstrip().startswith(key))
if found != 1:
    sys.exit(f"transform: {path}: expected 1 line {key}, found {found}")
lines = [l for l in lines if not l.lstrip().startswith(key)]
open(path, "w", encoding="utf-8").write("\n".join(lines))
PY
