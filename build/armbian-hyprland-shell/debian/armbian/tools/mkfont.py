#!/usr/bin/python3
# Make the "armbian" icon font for the bar menu button (glyph U+E900).
# The bar fits each icon into a square, so the glyph is the "A" of the
# Armbian wordmark, with its triangle, not the whole word.
#
# Usage: mkfont.py <armbian-logo.svg> <armbian.ttf>
# armbian-logo.svg: packages/bsp/common/usr/share/pixmaps/ in armbian/build.
# Needs python3-fontforge.
import sys

import fontforge
import psMat

svg, out = sys.argv[1], sys.argv[2]

font = fontforge.font()
font.fontname = font.familyname = font.fullname = "armbian"
font.em = 1000
glyph = font.createChar(0xE900, "armbian")
glyph.importOutlines(svg)
glyph.removeOverlap()

# Keep the outlines of the first letter: those that start left of the
# right edge of the leftmost outer contour.
contours = sorted(glyph.foreground, key=lambda c: c.boundingBox()[0])
first_right = contours[0].boundingBox()[2]
keep = fontforge.layer()
for contour in contours:
    if contour.boundingBox()[0] < first_right:
        keep += contour
glyph.foreground = keep

# Fit into the em box like a text glyph: 700 units high, baseline at 0.
xmin, ymin, xmax, ymax = glyph.boundingBox()
scale = 700.0 / (ymax - ymin)
glyph.transform(psMat.translate(-xmin, -ymin))
glyph.transform(psMat.scale(scale))
glyph.width = int((xmax - xmin) * scale) + 60
glyph.transform(psMat.translate(30, 0))

font.generate(out)
print(f"armbian.ttf: U+E900 {len(keep)} contours, width {glyph.width}")
