# The owner account gets admin rights through the group sudo on Debian,
# not wheel. The comments that name wheel stay.
. "$TRANSFORM_LIB"

replace bin/omarchy-provision-owner 'local groups="wheel" group' 'local groups="sudo" group' 1
replace bin/omarchy-provision-owner 'echo "%wheel ALL=(ALL:ALL) ALL"' 'echo "%sudo ALL=(ALL:ALL) ALL"' 1
