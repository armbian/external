# Show "Armbian" for the product name in all translation catalogs.
# Change the values only: the code looks up the keys.
python3 - <<- 'EOF'
import json
import pathlib
import sys

def rename(value):
    if isinstance(value, dict):
        return {key: rename(item) for key, item in value.items()}
    if isinstance(value, list):
        return [rename(item) for item in value]
    if isinstance(value, str):
        return value.replace("Omarchy", "Armbian")
    return value

catalogs = sorted(pathlib.Path("default/i18n").glob("*/*.json"))
if not catalogs:
    sys.exit("transform: no catalogs in default/i18n")
changed = 0
for path in catalogs:
    data = json.loads(path.read_text(encoding="utf-8"))
    new = rename(data)
    if new != data:
        path.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        changed += 1
# The English catalogs name the product: a tree without it changed upstream.
if not any(p.parent.name == "en" and "Armbian" in p.read_text(encoding="utf-8") for p in catalogs):
    sys.exit("transform: English catalogs do not name the product any more")
print(f"transform: {changed} catalogs renamed")
EOF
