# Update > Channel: Armbian has two repositories, stable and rolling.
# The edge entry selects rolling. Armbian has no RC or dev repository.
. "$TRANSFORM_LIB"

old=$(cat <<'EOF_OLD'
  "update.channel.rc": {"icon":"🟡","label":"RC","checked":"[[ \"$(omarchy-channel-current)\" == \"rc\" ]]","action":"omarchy-launch-floating-terminal-with-presentation 'omarchy-channel-set rc'"},
EOF_OLD
)
replace default/omarchy/omarchy-menu.jsonc "$old
" "" 1

old=$(cat <<'EOF_OLD'
  "update.channel.dev": {"icon":"🔴","label":"Dev","checked":"[[ \"$(omarchy-channel-current)\" == \"dev\" ]]","action":"omarchy-launch-floating-terminal-with-presentation 'omarchy-channel-set dev'"},
EOF_OLD
)
replace default/omarchy/omarchy-menu.jsonc "$old
" "" 1

replace default/omarchy/omarchy-menu.jsonc \
	'"update.channel.edge": {"icon":"🟠","label":"Edge",' \
	'"update.channel.edge": {"icon":"🟠","label":"Rolling",' 1

# The label of update.channel.edge, in every catalog.
python3 - <<'EOF'
import glob, re, sys
files = sorted(glob.glob("default/i18n/*/menu.json"))
if not files:
    sys.exit("transform: no default/i18n/*/menu.json")
pattern = re.compile(r'("update\.channel\.edge": \{\s*"label": )"[^"]*"')
for path in files:
    text = open(path, encoding="utf-8").read()
    text, found = pattern.subn(r'\1"Rolling"', text)
    if found != 1:
        sys.exit(f"transform: {path}: expected 1 update.channel.edge label, found {found}")
    open(path, "w", encoding="utf-8").write(text)
EOF
