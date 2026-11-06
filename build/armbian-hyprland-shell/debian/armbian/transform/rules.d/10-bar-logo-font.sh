# The bar menu button draws glyph U+E900. Take it from the Armbian icon
# font (overlay: usr/share/fonts/armbian/armbian.ttf).
. "$TRANSFORM_LIB"

replace shell/plugins/menu/BarWidget.qml 'fontFamily: "omarchy"' 'fontFamily: "armbian"' 1
