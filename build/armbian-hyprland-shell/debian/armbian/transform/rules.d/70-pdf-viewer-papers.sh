# Debian ships Papers, the successor of Evince, as the GNOME PDF viewer
# (deps.map: evince -> papers). Open PDFs with it and float it the same way.
. "$TRANSFORM_LIB"

replace default/applications/mimeapps.list 'application/pdf=org.gnome.Evince.desktop' 'application/pdf=org.gnome.Papers.desktop' 1
replace default/hypr/apps/system.lua '|org.gnome.Evince|' '|org.gnome.Papers|' 1
