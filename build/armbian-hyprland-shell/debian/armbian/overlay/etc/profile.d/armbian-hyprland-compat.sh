# Armbian: bat and fd with the Arch names for login shells (ssh, tty), as
# /usr/share/uwsm/env.d/51-armbian-compat does for the desktop session.
case ":$PATH:" in
  *:/usr/lib/armbian-hyprland-shell/compat:*) ;;
  *) export PATH="$PATH:/usr/lib/armbian-hyprland-shell/compat" ;;
esac
