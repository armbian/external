# Arch gives admin rights to the group wheel, Debian to the group sudo.
. "$TRANSFORM_LIB"

for f in omarchy-dns omarchy-locale-generate omarchy-theme-browser omarchy-tzupdate; do
	replace "etc/sudoers.d/$f" '%wheel' '%sudo' 1
done
