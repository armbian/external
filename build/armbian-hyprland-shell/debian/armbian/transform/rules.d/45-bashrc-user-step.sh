# Users get the Omarchy .bashrc from a setup step, not from /etc/skel
# (debian/armbian/overlay/usr/share/omarchy/install/user/bashrc.sh).
. "$TRANSFORM_LIB"

replace install/user/all.sh 'run_logged "$OMARCHY_INSTALL/user/theme.sh"' \
	'run_logged "$OMARCHY_INSTALL/user/bashrc.sh"
run_logged "$OMARCHY_INSTALL/user/theme.sh"' 1
replace bin/omarchy-reinstall-configs 'cp -af /etc/skel/. ~/
' 'cp -af /etc/skel/. ~/
bash "${OMARCHY_PATH:-/usr/share/omarchy}/install/user/bashrc.sh"
' 1
