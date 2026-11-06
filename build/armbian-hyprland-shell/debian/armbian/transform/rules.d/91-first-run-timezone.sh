# First-run sets the timezone when it is still UTC
# (overlay usr/share/omarchy/install/user/first-run/armbian-timezone.sh).
. "$TRANSFORM_LIB"

old=$(cat <<'EOF_OLD'
run_first_run_step "set GTK primary paste" \
  bash "$OMARCHY_PATH/install/user/first-run/gtk-primary-paste.sh"
EOF_OLD
)
new=$(cat <<'EOF_NEW'
run_first_run_step "set GTK primary paste" \
  bash "$OMARCHY_PATH/install/user/first-run/gtk-primary-paste.sh"
run_first_run_step "set the timezone" \
  bash "$OMARCHY_PATH/install/user/first-run/armbian-timezone.sh"
EOF_NEW
)
replace bin/omarchy-provision-first-run "$old" "$new" 1
