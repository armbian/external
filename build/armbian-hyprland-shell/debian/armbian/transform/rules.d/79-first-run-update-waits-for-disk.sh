# The first-run update notice waits for the Armbian first-boot disk work:
# the LUKS re-key of an encrypted root, then the root resize.
# omarchy-update needs 10 GiB free, which the root has only after the resize.
. "$TRANSFORM_LIB"

old=$(cat <<'EOF_OLD'
  # A fresh install from current media has nothing to update, and a toast
EOF_OLD
)
new=$(cat <<'EOF_NEW'
  # Armbian: the first boot re-keys an encrypted root, then grows the root.
  # omarchy-update needs 10 GiB free: invite after both. The resize starts
  # a moment after the re-key ends, so check twice.
  for _ in 1 2; do
    while [[ -e /run/armbian-luks-rekey.running ]] ||
      [[ -n $(systemctl show -p Job --value armbian-resize-filesystem.service 2>/dev/null) ]] ||
      [[ $(systemctl show -p ActiveState --value armbian-resize-filesystem.service 2>/dev/null) == activating ]]; do
      sleep 10
    done
    sleep 5
  done

  # A fresh install from current media has nothing to update, and a toast
EOF_NEW
)
replace install/user/first-run/wifi.sh "$old" "$new" 1
