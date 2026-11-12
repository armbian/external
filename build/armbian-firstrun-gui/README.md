# armbian-firstrun-gui

Graphical first-run wizard. It runs on the screen at the first boot, without X11 or Wayland (DRM/KMS, else `/dev/fb0`).

It asks for a wireless network (only without a connection), the user account, and the time zone, locale and keyboard. The location preselects the time zone, locale and keyboard. Without a network, the image defaults stay.

The wizard is a frontend. It writes `PRESET_*` variables to `/root/.not_logged_in_yet` and runs `armbian-firstlogin`, which applies them. When presets answer everything, the wizard does not start. Serial console and SSH keep the text setup.

## Use

- Image: install the package, for example in the package list of a desktop. The service starts only while `/root/.not_logged_in_yet` exists.
- Test without changes: `armbian-firstrun-gui --dry-run` as root on a free console (`chvt 8; systemd-run armbian-firstrun-gui --dry-run`). The answers go to `/tmp/armbian-firstrun-gui.preset`.
- Theme: `/etc/armbian/firstrun-gui.conf` (`BACKGROUND`, `LOGO`, `TITLE`, `FONT`, `ACCENT`).

## Develop

`cargo build --features dev` draws in an X11 window. `FRG_FAKE_WIFI=1` shows fake wireless networks. Keep `rust-version` at the oldest Rust of the releases (trixie: 1.85): `resolver = "3"` keeps `Cargo.lock` compatible.

Code: `src/main.rs` (pages, presets), `src/data.rs` (lists, location), `src/wifi.rs` (NetworkManager or netplan), `ui/app.slint` (layout).
