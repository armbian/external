# The menu guards answer omarchy-pkg-present from a package set built with
# pacman. Build it from dpkg instead (overlay usr/lib/armbian-hyprland-shell/
# pkg-names), so Install and Remove entries see what is installed.
. "$TRANSFORM_LIB"

old=$(cat <<'EOF_OLD'
  var build = '{ set -o pipefail; pacman -Qq && LC_ALL=C pacman -Qi'
    + " | awk '/^[A-Za-z]/ { provides = ($0 ~ /^Provides/); sub(/^[^:]*: /, \"\") }"
    + ' provides && $0 != "None" { n = split($0, p, " ");'
    + ' for (i = 1; i <= n; i++) { sub(/[<>=].*/, "", p[i]); print p[i] } }\' && echo /; } 2>/dev/null'
EOF_OLD
)
new=$(cat <<'EOF_NEW'
  var build = '/usr/lib/armbian-hyprland-shell/pkg-names 2>/dev/null'
EOF_NEW
)
replace shell/plugins/menu/MenuModel.js "$old" "$new" 1

old=$(cat <<'EOF_OLD'
"$__omarchy_pkg_db/local"
EOF_OLD
)
new=$(cat <<'EOF_NEW'
"$__omarchy_pkg_db/status"
EOF_NEW
)
replace shell/plugins/menu/MenuModel.js "$old" "$new" 1

old=$(cat <<'EOF_OLD'
'__omarchy_pkg_db=${OMARCHY_PACMAN_DB_PATH:-$(pacman-conf DBPath 2>/dev/null)} || __omarchy_pkg_db=""\n'
EOF_OLD
)
new=$(cat <<'EOF_NEW'
'__omarchy_pkg_db=/var/lib/dpkg\n'
EOF_NEW
)
replace shell/plugins/menu/MenuModel.js "$old" "$new" 1

old=$(cat <<'EOF_OLD'
{ pacman -Q "$1" &>/dev/null; return; }
EOF_OLD
)
new=$(cat <<'EOF_NEW'
{ dpkg -s "${1%%[\\<\\>=]*}" &>/dev/null; return; }
EOF_NEW
)
replace shell/plugins/menu/MenuModel.js "$old" "$new" 1
