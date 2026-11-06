# FIDO2 setup calls pamu2fcfg. Debian ships it in its own package, which
# libpam-u2f only recommends, and Armbian does not install recommends.
. "$TRANSFORM_LIB"

replace bin/omarchy-setup-security-fido2 'omarchy-pkg-add libfido2 pam-u2f' 'omarchy-pkg-add libfido2 pam-u2f pamu2fcfg' 1
