# Start with Num Lock off. Compact keyboards without a keypad, such as the
# Raspberry Pi 400, map letter keys to a keypad while Num Lock is on.
# Users can turn it on in ~/.config/hypr/input.lua.
. "$TRANSFORM_LIB"

replace default/hypr/input.lua 'numlock_by_default = true,' 'numlock_by_default = false,' 1
