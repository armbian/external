# Binding descriptions show in the key sheet (Super+K). English shows the
# description itself. Other languages look it up as a key in
# keybindings.json, and the sheet puts this entry first by its text.
# Rename all three together.
. "$TRANSFORM_LIB"

replace default/hypr/bindings/utilities.lua '"Omarchy menu"' '"Armbian menu"' 2
replace bin/omarchy-menu-keybindings '/Omarchy menu/' '/Armbian menu/' 1
for f in default/i18n/*/keybindings.json; do
	replace "$f" '"Omarchy menu":' '"Armbian menu":' 1
done
