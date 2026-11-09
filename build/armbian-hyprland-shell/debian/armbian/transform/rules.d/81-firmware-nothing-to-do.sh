# fwupdmgr update exits 2 when no device has an update.
# set -e then shows "Failed" for a normal result.
. "$TRANSFORM_LIB"

replace bin/omarchy-update-firmware 'sudo fwupdmgr update' 'sudo fwupdmgr update || [[ $? == 2 ]]' 1
