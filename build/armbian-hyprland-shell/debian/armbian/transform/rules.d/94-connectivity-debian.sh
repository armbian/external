# Connectivity check and captive portal URL: the Debian endpoint, as
# network-manager-config-connectivity-debian uses. Plain HTTP, and debian.org
# sends no HSTS for its subdomains, so a portal can intercept it.
. "$TRANSFORM_LIB"

replace etc/NetworkManager/conf.d/omarchy-connectivity.conf 'uri=http://ping.omacom.io/nm-check.txt
response=' 'uri=http://network-test.debian.org/nm
response=NetworkManager is online' 1
replace shell/plugins/panels/network/Model.js 'var captivePortalUrl = "http://ping.omacom.io/nm-check.txt"' 'var captivePortalUrl = "http://network-test.debian.org/nm"' 1
