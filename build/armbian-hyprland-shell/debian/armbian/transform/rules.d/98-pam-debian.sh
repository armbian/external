# PAM files that Omarchy writes include Arch stacks. Debian has none of
# them: an include of a missing file fails the account step, so the lock
# screen never unlocked. Use the Debian common-* stacks.
. "$TRANSFORM_LIB"

replace bin/omarchy-apply-lock 'account    include                     system-local-login' 'account    include                     common-account' 2
for f in bin/omarchy-setup-security-fingerprint bin/omarchy-setup-security-fido2; do
	replace "$f" 'auth      include system-auth' 'auth      include common-auth' 1
	replace "$f" 'account   include system-auth' 'account   include common-account' 1
	replace "$f" 'password  include system-auth' 'password  include common-password' 1
	replace "$f" 'session   include system-auth' 'session   include common-session' 1
done
