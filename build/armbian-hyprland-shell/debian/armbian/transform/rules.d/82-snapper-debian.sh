# Snapper: Debian reads SNAPPER_CONFIGS from /etc/default/snapper, a conffile
# of the snapper package. Set the variable there. Do not replace the file.
# Debian has no limine-snapper-sync: enable the cleanup timer alone.
# Armbian images can have an ext4 root. There snapper has nothing to
# snapshot: return 127 like a missing snapper, so omarchy-update stays quiet.
# Boot entries: GRUB (etc/grub.d/42_armbian-snapshots) instead of limine.
# Boards without GRUB have no boot menu: say so. Restore: snapshot-restore
# instead of limine-snapper-restore.
. "$TRANSFORM_LIB"

replace install/config/snapper.sh 'SNAPPER_CONF_PATH="${OMARCHY_SNAPPER_CONF_PATH:-/etc/conf.d/snapper}"' 'SNAPPER_CONF_PATH="${OMARCHY_SNAPPER_CONF_PATH:-/etc/default/snapper}"' 1
replace install/config/snapper.sh "printf '%s\\n' 'SNAPPER_CONFIGS=\"root\"' >\"\$SNAPPER_CONF_PATH\"" "touch \"\$SNAPPER_CONF_PATH\"
sed -i '/^SNAPPER_CONFIGS=/d' \"\$SNAPPER_CONF_PATH\"
printf '%s\\n' 'SNAPPER_CONFIGS=\"root\"' >>\"\$SNAPPER_CONF_PATH\"" 1
replace install/config/snapper.sh 'systemctl enable --now snapper-cleanup.timer limine-snapper-sync.service' 'systemctl enable --now snapper-cleanup.timer' 1
replace bin/omarchy-snapshot 'if omarchy-cmd-missing snapper; then
  exit 127 # omarchy-update can use this to just ignore if snapper is not available
fi' 'if omarchy-cmd-missing snapper || [[ $(findmnt -n -o FSTYPE /) != btrfs ]]; then
  exit 127 # omarchy-update can use this to just ignore if snapper is not available
fi' 1
replace bin/omarchy-snapshot '  echo "Snapshots can be selected during boot."' '  if [[ -x /etc/grub.d/42_armbian-snapshots && -d /boot/grub ]]; then
    echo "Snapshots can be selected during boot."
  else
    echo "Snapshots are in /.snapshots. Selecting them during boot needs GRUB."
  fi' 1
replace bin/omarchy-snapshot '  sudo limine-snapper-restore' '  sudo /usr/lib/armbian-hyprland-shell/snapshot-restore "${@:2}"' 1
