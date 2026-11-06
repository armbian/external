# The login screen shows the session name and the greeter theme name.
. "$TRANSFORM_LIB"

replace default/wayland-sessions/omarchy.desktop 'Name=Omarchy (Hyprland uwsm)' 'Name=Armbian (Hyprland uwsm)' 1
replace default/wayland-sessions/omarchy.desktop 'Comment=Omarchy Hyprland' 'Comment=Armbian Hyprland' 1
replace default/sddm/omarchy/metadata.desktop 'Name=Omarchy' 'Name=Armbian' 1
