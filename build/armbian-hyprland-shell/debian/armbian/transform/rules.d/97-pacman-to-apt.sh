# Scripts outside the omarchy-pkg-* helpers that call pacman directly.
. "$TRANSFORM_LIB"

# Fingerprint setup installs its packages on demand. Debian names; PAM needs
# libpam-fprintd. libfprint-git is Arch's newer libfprint build.
replace bin/omarchy-setup-security-fingerprint 'if omarchy-pkg-missing libfprint-git fprintd usbutils; then' 'if omarchy-pkg-missing libfprint-2-2 fprintd libpam-fprintd usbutils; then' 1
replace bin/omarchy-setup-security-fingerprint 'sudo pacman -S --needed --noconfirm --ask 4 -- libfprint-git fprintd usbutils' 'omarchy-pkg-add libfprint-2-2 fprintd libpam-fprintd usbutils' 1

# Remove a launcher entry: find and remove the owning package with dpkg/apt.
replace bin/omarchy-remove-launcher-entry 'pacman -Qqo "$desktop_file" 2>/dev/null | head -1' 'dpkg-query -S "$desktop_file" 2>/dev/null | head -1 | cut -d: -f1 | cut -d, -f1' 1
replace bin/omarchy-remove-launcher-entry 'sudo pacman -Rns $quoted_package' 'omarchy-pkg-drop $quoted_package' 1

# Log upload: package list from dpkg, upload to the Armbian paste service.
replace bin/omarchy-upload-log 'INSTALLED PACKAGES (pacman -Q)' 'INSTALLED PACKAGES (dpkg-query -W)' 1
replace bin/omarchy-upload-log 'pacman -Q 2>/dev/null' 'dpkg-query -W 2>/dev/null' 1
replace bin/omarchy-upload-log 'curl -sf -F "file=@$TEMP_LOG" -Fexpires=24 https://logs.omarchy.org/' 'curl -sf --data-binary "@$TEMP_LOG" https://paste.armbian.com/log' 1
replace bin/omarchy-upload-log 'logs.omarchy.org' 'paste.armbian.com' 5
