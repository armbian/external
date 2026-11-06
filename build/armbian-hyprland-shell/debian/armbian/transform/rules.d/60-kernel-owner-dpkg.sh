# After an update, a reboot is due when no installed kernel matches the
# running one. Debian: dpkg tells which package owns a kernel's modules.
. "$TRANSFORM_LIB"

replace bin/omarchy-update-restart 'pacman -Qo "$kernel"' 'dpkg -S "$kernel"' 1
