# Superwhisper is proprietary: only the vendor channel may distribute it. Use
# the official installer (per user, in ~/.local) instead of superwhisper-bin.
# deps.map recommends its dependencies, so the installer needs no sudo.
. "$TRANSFORM_LIB"

replace bin/omarchy-install-dictation-superwhisper 'omarchy-pkg-add superwhisper-bin
bash /usr/share/superwhisper/setup-user
' 'curl -fsSL https://tux.superwhisper.com/install.sh | sh
' 1
replace bin/omarchy-remove-dictation-superwhisper 'omarchy-pkg-drop superwhisper-bin
' 'uninstaller="$data_home/superwhisper/app/current/uninstall.sh"
[[ ! -x $uninstaller ]] || "$uninstaller"
' 1
# Upstream preinstalls the package. Here first run installs it.
replace install/user/first-run/superwhisper.sh 'omarchy-pkg-present superwhisper-bin && ' '' 1
replace default/omarchy/omarchy-menu.jsonc 'omarchy-pkg-present superwhisper-bin' 'omarchy-cmd-present superwhisper' 2
