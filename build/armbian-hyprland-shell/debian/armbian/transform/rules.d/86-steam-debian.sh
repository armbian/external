# Steam and Lutris: Debian packages the 32-bit graphics libraries as i386
# multiarch (mesa-vulkan-drivers:i386, deps.map). The lib32 driver install
# enables i386 first. Debian has no arm64 Steam: the menu offers it on x86 only.
. "$TRANSFORM_LIB"

old=$(cat <<'EOF_OLD'
omarchy-hw-x86 || exit 0
EOF_OLD
)
new=$(cat <<'EOF_NEW'
omarchy-hw-x86 || exit 0

# Armbian: the 32-bit libraries come from the i386 architecture.
if ! dpkg --print-foreign-architectures | grep -qx i386; then
  sudo dpkg --add-architecture i386
  sudo apt-get update
fi
EOF_NEW
)
replace bin/omarchy-install-gaming-gpu-lib32 "$old" "$new" 1

replace default/omarchy/omarchy-menu.jsonc \
	'"label":"Steam","disabled":"omarchy-pkg-present steam",' \
	'"label":"Steam","when":"omarchy-hw-x86","disabled":"omarchy-pkg-present steam",' 1
