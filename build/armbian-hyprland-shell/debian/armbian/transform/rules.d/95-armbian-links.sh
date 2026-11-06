# Documentation, release notes and community point to Armbian.
. "$TRANSFORM_LIB"

replace default/omarchy/omarchy-menu.jsonc "omarchy-launch-webapp 'https://omarchy.org/manual/'" "omarchy-launch-webapp 'https://docs.armbian.com/'" 1
replace bin/omarchy-update-confirm 'https://github.com/omacom/omarchy/releases/latest' 'https://docs.armbian.com/releases/' 1
replace bin/omarchy-update 'get help from the community at https://omarchy.org/discord' 'get help from the community at https://discord.armbian.com' 1
# discord.armbian.com redirects here. The launcher takes the invite code
# from the end of the URL for the Discord app.
replace bin/omarchy-launch-discord-community 'invite="https://discord.gg/tXFUdasqhY"' 'invite="https://discord.com/invite/armbian"' 1
