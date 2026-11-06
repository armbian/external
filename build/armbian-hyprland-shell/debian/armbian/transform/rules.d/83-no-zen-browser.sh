# Zen browser: removed. It has no Debian package or apt repository, only
# tarballs. Other browsers cover it (maintainer decision).
. "$TRANSFORM_LIB"

python3 - <<'PY'
import sys
path = "default/omarchy/omarchy-menu.jsonc"
text = open(path, encoding="utf-8").read()
lines = text.split("\n")
keys = ('"setup.default.browser.zen":', '"install.browser.zen":', '"remove.browser.zen":')
for key in keys:
    found = sum(1 for l in lines if l.lstrip().startswith(key))
    if found != 1:
        sys.exit(f"transform: {path}: expected 1 line {key}, found {found}")
lines = [l for l in lines if not l.lstrip().startswith(keys)]
open(path, "w", encoding="utf-8").write("\n".join(lines))
PY
