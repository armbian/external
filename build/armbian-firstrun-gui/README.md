# armbian-firstrun-gui

Graphical first-run wizard. It runs on the screen at the first boot, without X11 or Wayland (DRM/KMS, else `/dev/fb0`).

It asks for a wireless network (only without a connection), the user account and shell (bash or zsh, when zsh is installed), and the time zone, locale and keyboard. The wizard shows the IP address, for SSH. The location preselects the time zone, locale and keyboard. Without a network, the image defaults stay.

The wizard is a frontend. It writes `PRESET_*` variables to `/root/.not_logged_in_yet` and runs `armbian-firstlogin`, which applies them. When presets answer everything, the wizard does not start. Serial console and SSH keep the text setup.

Order: with a network, Quick setup comes first: the username or "@user", the password, and optional settings under Customize. Without a network and with Wi-Fi, the Wi-Fi page comes first. It has the keyboard choice, because the Wi-Fi password uses the keyboard.

Git account (optional, needs a network): type `@user` in the username field for GitHub, or `@user@host` for GitLab, Codeberg or another server. The wizard reads public data only: the SSH keys (`https://<host>/<user>.keys`), the display name, and a public repository with the name `armbian-dotfiles`. The fixed name keeps it apart from a `dotfiles` repository for other systems. The account fills in the name and username. The wizard writes `PRESET_USER_KEY` (the keys URL) and `PRESET_DOTFILES_URL` (the repository), only for the items that exist. `armbian-firstlogin` puts the keys into `authorized_keys`. It clones and applies the repository as the user only when it supports `PRESET_DOTFILES_URL` (armbian/build#11435); an older one ignores the preset.

## Use

- Image: install the package, for example in the package list of a desktop. The service starts only while `/root/.not_logged_in_yet` exists.
- Test without changes: `armbian-firstrun-gui --dry-run` as root on a free console (`chvt 8; systemd-run armbian-firstrun-gui --dry-run`). The answers go to `/tmp/armbian-firstrun-gui.preset`.
- Theme: `/etc/armbian/firstrun-gui.conf` (`BACKGROUND`, `LOGO`, `TITLE`, `FONT`, `ACCENT`).
- Screen keyboard: available when a touchscreen is detected. A mouse or touchpad alone does not enable it.
  Device detection follows udev events, including touchscreens that become available after the wizard starts.
  Tap a text field to type. Use Shift for capitals and 123 for numbers and symbols.
  Hide closes it; tapping the field opens it again. Physical typing also hides it.
  Hide the keyboard to change the shell or region settings on the account page.
  The screen keyboard uses a fixed US layout. The keyboard layout setting controls the physical keyboard.

## Develop

Run `make -f debian/rules override_dh_auto_configure` before a Cargo build.
It downloads the LinuxKMS backend, checks its SHA256 and applies the scanout row-pitch fix.
The patched source stays under `target/`. Other crate dependencies use Cargo as usual.

`cargo build --features dev` draws in an X11 window. `FRG_FAKE_WIFI=1` shows fake wireless networks. Keep `rust-version` at the oldest Rust of the releases (trixie: 1.85): `resolver = "3"` keeps `Cargo.lock` compatible.

Code: `src/main.rs` (pages, presets), `src/data.rs` (lists, location), `src/git.rs` (git account lookup), `src/wifi.rs` (NetworkManager or netplan), `ui/app.slint` (layout).
