# Arch /run/lock is root-owned 0755. Debian /run/lock is 1777: the lock
# checks in these scripts refuse it, so passwordless sudo and the Windows
# VM did not work. Use /run/omarchy (root 0755, from the package tmpfiles).
. "$TRANSFORM_LIB"

replace bin/omarchy-sudo-passwordless '/run/lock' '/run/omarchy' 6
replace bin/omarchy-windows-vm '/run/lock' '/run/omarchy' 3
