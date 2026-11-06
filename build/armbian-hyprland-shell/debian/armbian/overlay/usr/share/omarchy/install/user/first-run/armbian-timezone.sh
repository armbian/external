# Armbian: armbian-firstlogin sets the timezone from the public IP. On a Wi-Fi
# laptop there is no network yet at that time, so the timezone stays UTC. Set
# it here, in the session. Offline, this fails and first-run retries at the
# next login. The sudoers rule omarchy-tzupdate allows timedatectl.
current=$(timedatectl show -p Timezone --value)
[[ $current == "Etc/UTC" || $current == "UTC" ]] || exit 0
timezone=$(timeout 15 tzupdate -p)
[[ -n $timezone ]]
sudo -n timedatectl set-timezone "$timezone"
