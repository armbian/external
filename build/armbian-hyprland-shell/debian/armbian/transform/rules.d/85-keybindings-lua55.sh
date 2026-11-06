# The key sheet reads the Lua bindings with "lua -E". Debian keeps "lua" at
# 5.1, which has no -E. Hyprland 0.56 uses Lua 5.5: call lua5.5.
. "$TRANSFORM_LIB"

replace bin/omarchy-menu-keybindings 'omarchy-cmd-present lua ||' 'omarchy-cmd-present lua5.5 ||' 1
replace bin/omarchy-menu-keybindings 'timeout 10 lua -E -' 'timeout 10 lua5.5 -E -' 1
