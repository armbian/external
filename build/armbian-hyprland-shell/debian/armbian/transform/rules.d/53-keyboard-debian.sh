# Debian keeps the keyboard layout in /etc/default/keyboard (keyboard(5)).
# Arch keeps it in /etc/vconsole.conf, which Debian does not have. Both use
# XKBLAYOUT and XKBVARIANT. Hyprland, the SDDM greeter and the input method
# setup read the Debian file, so they use the layout of the first login.
. "$TRANSFORM_LIB"

replace default/hypr/keyboard.lua '/etc/vconsole.conf' '/etc/default/keyboard' 2
replace default/sddm/hyprland.lua '"/etc/vconsole.conf"' '"/etc/default/keyboard"' 1
replace default/input-methods/configure.py '"/etc/vconsole.conf"' '"/etc/default/keyboard"' 1
