# First-run sets the shell language from the system locale
# (overlay usr/share/omarchy/install/user/first-run/armbian-language.sh).
. "$TRANSFORM_LIB"

old=$(cat <<'EOF_OLD'
run_first_run_step "set the timezone" \
  bash "$OMARCHY_PATH/install/user/first-run/armbian-timezone.sh"
EOF_OLD
)
new=$(cat <<'EOF_NEW'
run_first_run_step "set the timezone" \
  bash "$OMARCHY_PATH/install/user/first-run/armbian-timezone.sh"
run_first_run_step "set the language from the system locale" \
  bash "$OMARCHY_PATH/install/user/first-run/armbian-language.sh"
EOF_NEW
)
replace bin/omarchy-provision-first-run "$old" "$new" 1
