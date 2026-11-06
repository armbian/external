# About: the OS line shows the Armbian release. The theme line uses
# echo -e, which needs bash: Debian /bin/sh is dash.
. "$TRANSFORM_LIB"

old=$(cat <<'EOF_OLD'
"text": "version=$(omarchy-version) && echo \"Omarchy $version\""
EOF_OLD
)
new=$(cat <<'EOF_NEW'
"text": "v=$(. /etc/armbian-release && echo \"$VERSION\"); c=$(. /etc/os-release && echo \"$VERSION_CODENAME\"); echo \"Armbian $v $c\""
EOF_NEW
)
replace etc/fastfetch/config.jsonc "$old" "$new" 1

old=$(cat <<'EOF_OLD'
      "text": "theme=$(omarchy-theme-current); echo -e
EOF_OLD
)
new=$(cat <<'EOF_NEW'
      "shell": "bash",
      "text": "theme=$(omarchy-theme-current); echo -e
EOF_NEW
)
replace etc/fastfetch/config.jsonc "$old" "$new" 1
