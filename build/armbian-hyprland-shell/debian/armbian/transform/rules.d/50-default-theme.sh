# New users start with the Armbian theme (debian/armbian/overlay), not
# Tokyo Night. Other themes stay available in the theme menu.
. "$TRANSFORM_LIB"

replace install/user/theme.sh 'omarchy-theme-set "Tokyo Night"' 'omarchy-theme-set "armbian"' 2
