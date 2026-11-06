# Debian fcitx5 depends on im-config. Its launcher entry opens nothing in
# Hyprland, and Omarchy sets up the input method itself. Hide it as upstream
# hides other system entries.
. "$TRANSFORM_LIB"

replace default/omarchy/launcher.hides 'hermes
' 'hermes
im-config
' 1
