# Steam: Debian packages the 32-bit libraries as i386 multiarch
# (steam-installer, mesa-vulkan-drivers:i386, deps.map). Enable i386 first.
# Debian has no Steam for arm64: the menu offers it on x86 only.
. "$TRANSFORM_LIB"

old=$(cat <<'EOF_OLD'
omarchy-install-gaming-gpu-lib32
omarchy-pkg-add steam
EOF_OLD
)
new=$(cat <<'EOF_NEW'
# Armbian: the 32-bit libraries come from the i386 architecture.
if ! dpkg --print-foreign-architectures | grep -qx i386; then
  sudo dpkg --add-architecture i386
  sudo apt-get update
fi
omarchy-install-gaming-gpu-lib32
omarchy-pkg-add steam
EOF_NEW
)
replace bin/omarchy-install-gaming-steam "$old" "$new" 1

replace default/omarchy/omarchy-menu.jsonc \
	'"label":"Steam","disabled":"omarchy-pkg-present steam",' \
	'"label":"Steam","when":"omarchy-hw-x86","disabled":"omarchy-pkg-present steam",' 1
