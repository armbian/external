# Learn > Arch opened the Arch wiki. Armbian is Debian: Learn > Armbian
# covers it (maintainer decision).
. "$TRANSFORM_LIB"

replace default/omarchy/omarchy-menu.jsonc '  "learn.arch": {"icon":"󰣇","label":"Arch","action":"omarchy-launch-webapp '"'"'https://wiki.archlinux.org/title/Main_page'"'"'"},
' '' 1
