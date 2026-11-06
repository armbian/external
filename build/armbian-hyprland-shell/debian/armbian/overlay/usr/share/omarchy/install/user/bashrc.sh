# Armbian: bash owns /etc/skel/.bashrc, so new users get the Debian file.
# Replace it with the Omarchy one while the user has not changed it.
omarchy_path=${OMARCHY_PATH:-/usr/share/omarchy}
if [[ ! -e ~/.bashrc ]] || cmp -s ~/.bashrc /etc/skel/.bashrc; then
  cp "$omarchy_path/default/bashrc" ~/.bashrc
fi
