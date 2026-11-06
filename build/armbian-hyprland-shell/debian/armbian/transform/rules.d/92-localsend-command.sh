# The LocalSend .deb (mirror/localsend.yaml) installs the command
# localsend_app. The Arch package names it localsend.
. "$TRANSFORM_LIB"

replace bin/omarchy-menu-share 'systemd-run --user --quiet --collect localsend --headless' 'systemd-run --user --quiet --collect localsend_app --headless' 1
replace default/omarchy/omarchy-menu.jsonc '"action":"uwsm-app -- localsend"' '"action":"uwsm-app -- localsend_app"' 1
replace default/nautilus-python/extensions/localsend.py 'shutil.which("localsend")' 'shutil.which("localsend_app")' 1
