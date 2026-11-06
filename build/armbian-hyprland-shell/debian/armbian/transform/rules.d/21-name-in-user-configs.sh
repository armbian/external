# User configs (config/, copied to ~/.config): the name in comments.
# Only the word Omarchy. Paths and commands (omarchy-*) stay.
. "$TRANSFORM_LIB"

python3 - <<'EOF'
import os, re, sys
expected = 20
pattern = re.compile(r"\bOmarchy\b")
total = 0
for root, _, files in os.walk("config"):
    for name in files:
        path = os.path.join(root, name)
        try:
            text = open(path, encoding="utf-8").read()
        except UnicodeDecodeError:
            continue
        text, found = pattern.subn("Armbian", text)
        if found:
            total += found
            open(path, "w", encoding="utf-8").write(text)
if total != expected:
    sys.exit(f"transform: config/: expected {expected} of 'Omarchy', found {total}")
EOF
