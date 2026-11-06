# Support log: package list from dpkg, upload to the Armbian paste service,
# as omarchy-upload-log (transform 97-pacman-to-apt).
. "$TRANSFORM_LIB"

old=$(cat <<'EOF_OLD'
Omarchy Package: $(pacman -Q omarchy-dev 2>/dev/null || pacman -Q omarchy 2>/dev/null || echo "unknown")
EOF_OLD
)
new=$(cat <<'EOF_NEW'
Omarchy Package: $(dpkg-query -W -f '${Package} ${Version}' armbian-hyprland-shell 2>/dev/null || echo "unknown")
EOF_NEW
)
replace bin/omarchy-debug "$old" "$new" 1

old=$(cat <<'EOF_OLD'
$({ expac -S '%n %v (%r)' $(pacman -Qqe) 2>/dev/null; comm -13 <(pacman -Sql | sort) <(pacman -Qqe | sort) | xargs -r expac -Q '%n %v (AUR)'; } | sort)
EOF_OLD
)
new=$(cat <<'EOF_NEW'
$(dpkg-query -W -f '${db:Status-Abbrev} ${Package} ${Version}\n' 2>/dev/null | awk '$1 == "ii" { print $2, $3 }' | sort)
EOF_NEW
)
replace bin/omarchy-debug "$old" "$new" 1

old=$(cat <<'EOF_OLD'
echo "Uploading debug log to logs.omarchy.org..."
EOF_OLD
)
new=$(cat <<'EOF_NEW'
echo "Uploading debug log to paste.armbian.com..."
EOF_NEW
)
replace bin/omarchy-debug "$old" "$new" 1

old=$(cat <<'EOF_OLD'
URL=$(curl -sf -F "file=@$LOG_FILE" -Fexpires=24 https://logs.omarchy.org/)
EOF_OLD
)
new=$(cat <<'EOF_NEW'
URL=$(curl -sf --data-binary "@$LOG_FILE" https://paste.armbian.com/log)
EOF_NEW
)
replace bin/omarchy-debug "$old" "$new" 1
