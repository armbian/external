#!/bin/sh
# Remove the stale browser cache marker that stops the launcher from
# starting (Mojang MCL-25003). As the upstream Arch package does.
cef_version_file="$HOME/.minecraft/webcache2/CEF_VERSION"
[ -e "$cef_version_file" ] && rm -f "$cef_version_file"
exec /usr/lib/minecraft-launcher/minecraft-launcher "$@"
