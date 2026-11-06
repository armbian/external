# Menu entries Update > Armbian and Appearance > Branding draw glyph U+E900,
# the logo. Take it from the Armbian icon font, as the bar button does
# (10-bar-logo-font). The other omarchy glyphs are agent logos: keep them.
. "$TRANSFORM_LIB"

replace default/omarchy/omarchy-menu.jsonc '"icon":"","iconFont":"omarchy"' '"icon":"","iconFont":"armbian"' 2
