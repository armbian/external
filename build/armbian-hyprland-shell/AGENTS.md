# Instructions for agents: armbian-hyprland-shell

This package is the Omarchy desktop (Hyprland Lua config, Quickshell shell,
scripts, themes) with Armbian branding, for Debian forky and sid.

Goal: keep the user experience identical to upstream Omarchy, with every
feature. Change only the branding and what Debian needs.

Read the repository [CLAUDE.md](../../CLAUDE.md) and
[docs/technical.md](../../docs/technical.md) first.

## Rule 1: never edit upstream code by hand

Upstream is `https://github.com/basecamp/omarchy` at the tag in
[../armbian-hyprland-shell.yaml](../armbian-hyprland-shell.yaml).
Every Armbian difference is one of four kinds. Put it in the matching
place. Nothing else may change upstream files.

| Kind | Place | Use it for |
|---|---|---|
| Transform rule | `debian/armbian/transform/rules.d/*.sh` | Repeatable text changes: the product name, a font family, a path. |
| Overlay | `debian/armbian/overlay/` | Files that Armbian owns: theme, font, artwork, fontconfig. Laid out like the installed system and copied over the package. |
| Adaptation | `debian/armbian/adapt.list` | Arch-specific code that has a Debian equivalent. One entry per feature: what upstream does, what Armbian does, which rule, overlay or patch does it. |
| Patch | `patches/` | Logic changes that a rule cannot express. Last resort. |

The build only sees `debian/` and `patches/`, so all Armbian files live in
`debian/armbian/`. The build tool applies `patches/series` to the upstream
tree. Then `debian/rules` runs `debian/armbian/transform/apply`, installs
the tree to `/usr/share/omarchy` with commands in `/usr/bin`, and copies
`debian/armbian/overlay/`.

### Transform rules

- One rule changes one thing. Name the file after the change, for example
  `20-name-in-catalogs.sh`.
- A rule must fail when it matches nothing, or matches a different number
  of places than it expects. A silent no-op hides an upstream change.
- Rules run once, on a clean upstream tree. Use the `replace` helper in
  `transform/lib.sh`: it fails when the count of matches differs.
- Change values, not lookup keys. Example: in `default/i18n/*/*.json`,
  replace `Omarchy` in the values only. The code looks up the keys.

### Patches

- Keep each patch small. Put the reason and the upstream file in the
  header.
- When a patch fixes a bug that is not Armbian specific, also open an
  upstream issue or pull request. Link it in the header.
- Drop a patch as soon as upstream has the change.

## Rule 1b: follow the upstream install layout

Install each file where upstream's own packages install it.
`docs/file-layout.md` in upstream is the map (repository path to installed
path, for the `omarchy` and `omarchy-settings` Arch packages). One Armbian
package holds both. Put the mapping in `debian/rules` and `debian/links`.
A file that is branding (SDDM theme, Plymouth theme, logo text) gets an
Armbian replacement instead.

## Rule 2: what Armbian changes

Change these. Nothing more.

| Item | Upstream | Armbian |
|---|---|---|
| Name in visible text | `Omarchy` | `Armbian` (catalog values, notifications, menu titles, messages of the commands in `bin/`) |
| Bar menu logo | glyph `U+E900` in font `omarchy` | glyph `U+E900` in font `armbian`: the "A" of the Armbian wordmark, because the bar fits icons into a square. Make it with `debian/armbian/tools/mkfont.py`. Keep `omarchy.ttf` installed: its other glyphs are agent logos. |
| Default theme | Tokyo Night | `armbian` theme: palette, wallpapers, lock artwork, Papirus-Dark. Its wallpapers are copies of the armbian-config desktop branding wallpapers (configng `tools/modules/desktops/branding/wallpapers/`). Ship real files: Omarchy copies the theme into the user state, which breaks symlinks. |
| Lock artwork | `themes/*/unlock.png` | Armbian wordmark, Armbian orange glow |
| First-run notices | Omarchy texts | The same notices, Armbian name |
| Logo in menu entries | glyph `U+E900` in font `omarchy` | font `armbian`, as the bar button |
| Links | Omarchy manual, release notes, Discord, `ping.omacom.io` | `docs.armbian.com`, `docs.armbian.com/releases/`, Armbian Discord, `network-test.debian.org`. Learn > Arch is removed. |
| Fonts | Arch Nerd Font packages | `fonts-jetbrains-mono-nerd` package. Upstream `50-omarchy.conf` is active system-wide, as in upstream. |

Keep these unchanged, so that upstream updates apply cleanly:

- Command names (`omarchy-*`), the install path `/usr/share/omarchy`, QML
  identifiers, Lua module names, state paths. The user does not see them
  in normal use. Maintainer decision for the initial port: keep these
  internal names. A rename needs a new maintainer decision.
- Key bindings, menus, panels, animations, layouts and theme mechanics.
- The license file and its copyright notice (MIT).

## Rule 3: keep every feature

Do not remove a feature. When a feature uses Arch, adapt it to Debian and
record it in `debian/armbian/adapt.list`. A feature that fails on Armbian is a
bug: fix it, do not hide it.

Areas that need adaptation:

| Upstream (Arch) | Armbian (Debian) |
|---|---|
| Package install and removal helpers (`omarchy-pkg-*`, `pacman`, `yay`, `expac`) | `apt-get`, `dpkg-query`. Keep the command names and their arguments. |
| AUR packages | Debian package, Armbian repository (this repository), vendor apt repository, or the vendor's official installer. Write the choice in `adapt.list`. |
| AI agents (Claude Code, Codex, OpenCode, ...) | Upstream installs the CLIs with `mise`. Armbian builds `mise` in this repository, so the same code works. |
| Dictation, web apps, app bindings | Same features. Map the packages; web apps use Chromium, the upstream default, on every architecture. |
| Updates (`omarchy-update`, migrations, `libalpm` hooks) | `apt` and Armbian updates. Keep the update notices and the migration mechanism. |
| Snapshots and reset (`snapper`, `limine`, ISO reset) | Debian `snapper` on btrfs where it exists. Armbian boots with GRUB or U-Boot: adapt boot entries to them. When the hardware or boot method has no equivalent, show why in the menu. |
| Passwordless sudo setup (`omarchy-sudo-passwordless`) | Upstream script unchanged. The maintainer scripts do the work of the `libalpm` hooks and `omarchy-settings.install`. |

When there is no Debian equivalent yet, ask the maintainer. Do not remove
the feature on your own.

### Debian differences to check

Each item broke a feature once. Check them after every upstream update.

- `pacman` outside `omarchy-pkg-*`: search all of `bin`, `install/user`
  and `shell`. The menu builds its own package set in
  `shell/plugins/menu/MenuModel.js`; on Armbian it comes from
  `usr/lib/armbian-hyprland-shell/pkg-names` (dpkg and `deps.map`).
- PAM files that include Arch stacks (`system-auth`,
  `system-local-login`): use the Debian `common-*` stacks. A missing include
  fails the account step: the lock screen does not unlock. Test with
  `pamtester`.
- Conffiles of other packages, for example `/etc/skel/.bashrc`: do not
  divert them. dpkg asks a question, and an unattended install fails. Use
  a user setup step.
- `/usr/sbin`: Arch merges it into `/usr/bin`, Debian keeps it off the
  user `PATH`. uwsm sets the session `PATH` from the login shell, so
  `environment.d` has no effect. Add it in `/usr/share/uwsm/env.d/`.
- Command names: `localsend_app` (Arch `localsend`), `lua5.5` (Debian
  `lua` is 5.1), `/usr/libexec/imv/imv` (no `imv` in `PATH`).
- Chromium: the Debian wrapper reads `/etc/chromium.d/`, not
  `~/.config/chromium-flags.conf`, and loads every entry of
  `/usr/share/chromium/extensions/` as an unpacked extension.
- Install-time setup from `install/config/` (firewall, services): the
  one-shot `armbian-hyprland-shell-setup.service` runs it once at boot.
- Armbian owns the zram swap (`armbian-zram-config`), the Plymouth theme,
  user creation and the first timezone (`armbian-firstlogin`). Do not
  install upstream copies. The sddm theme file
  `zz-armbian-hyprland-shell.conf` sorts after `armbian.conf`.
- Proprietary software that only the vendor may distribute, for example
  Superwhisper: never mirror it. Use the vendor's official installer.

## Rule 4: Debian dependencies

Map each upstream Arch package to its Debian source in
`debian/armbian/deps.map`: `arch-name debian-name`, or `arch-name source:<where>`
when Debian has no package (Armbian repository, vendor repository,
official installer). Every package gets a source. Kinds without a Debian
package: `armbian-platform` (Armbian kernel, firmware, board support),
`arch-only` (replaced by an entry in `adapt.list`), `armbian-build` (build
it in this repository), `vendor` (vendor repository, release or Flathub).

`Recommends` in `debian/control` comes from the map at build time
(`override_dh_gencontrol`). Do not edit it by hand. `Depends` lists only
what the session and the shell need to start.

Armbian turns off Recommends, so the installer adds `--install-recommends`.
apt then also installs the Recommends of each recommended package.
`nautilus` recommends `xdg-desktop-portal-gnome`, which pulls in
`gnome-shell` and `gdm3`. Upstream uses only the `hyprland` and `gtk`
portals. Install with:

```sh
apt-get install --install-recommends armbian-hyprland-shell xdg-desktop-portal-gnome-
```

Known so far:

| Need | Debian package |
|---|---|
| Quickshell 0.3 | `quickshell` |
| Qt QML modules | `qml6-module-qtquick`, `-controls`, `-effects`, `-layouts`, `-shapes`, `-window`, `qml6-module-qtqml-models` |
| Plugin folder watch | `inotify-tools` |
| Image sizes | `imagemagick` (`magick`) |
| WebP wallpapers | `qt6-image-formats-plugins` |
| Shell IPC | `socat` |
| `awk` scripts | `gawk` (Debian default `mawk` fails) |
| Keybinding sheet | `libxkbcommon-tools` (`xkbcli`) |
| Icon glyphs | `fonts-jetbrains-mono-nerd` (Qt does not fall back to `fonts-nerd-symbols`) |

Arch base packages provide commands that upstream lists do not name. Map
them with extra lines: `libpulse` (`pactl`), `util-linux` (`rfkill`),
`alsa-lib` (`alsa-ucm-conf`: SoundWire laptops have no speaker without it),
`lua` (`lua5.5`), `cryptsetup`. Only the first line of a name counts for
`omarchy-pkg-debname`.

Hyprland, hyprlock, hypridle and the portals come from Debian. Do not
build them here.

### Companion packages

Omarchy's own packages, and the AUR or vendor packages that Debian does
not have, are configs in this repository: `build/<name>.yaml` with
packaging in `build/<name>/debian/`. Each one follows its upstream Arch
PKGBUILD in `omacom/omarchy-pkgs` (`pkgbuilds/<name>`). The Arch name maps
to the package name in `deps.map`.

| Kind | Configs |
|---|---|
| Omarchy apps and tools | `owe`, `omasnap`, `omacut`, `hype`, `signed`, `gliff`, `ttfx`, `monologue`, `omawrite`, `omacalc`, `aether`, `omarchy-nvim`, `omarchy-speedtest`, `omarchy-hyprland-titlebars` |
| AUR and vendor tools | `mise`, `usage`, `herdr`, `cliamp`, `tobi-try`, `disktree`, `hyprland-preview-share-picker`, `gpu-screen-recorder`, `tzupdate`, `ufw-docker` |
| Preinstalled apps without a Debian package | `pinta` (self-contained .NET), `moonlight-qt` (`upstream.submodules`) |
| Fonts | `fonts-jetbrains-mono-nerd`, `fonts-ia-writer` |
| Vendor `.deb` (mirror) | `mirror/localsend.yaml`, `mirror/localsend-arm64.yaml`, `mirror/obsidian.yaml`, `mirror/voxtype.yaml` |

To update one: set the tag of the PKGBUILD `pkgver` in `build/<name>.yaml`.
Compare the new PKGBUILD with the old one, and copy changes to the install
steps into `debian/rules`. Build it for forky and sid.

`omarchy-hyprland-titlebars` is a Hyprland plugin. It loads only in the
Hyprland it was built against, and its package depends on that exact
version. Rebuild it after each Hyprland update in forky or sid.

## Update to a new upstream tag

1. Set the new tag in `../armbian-hyprland-shell.yaml`.
2. Run `debian/armbian/transform/check-upstream <old-tag> <new-tag>`.
   Add `--repo <clone>` to reuse an Omarchy clone; a fresh check takes a
   few minutes. It lists, with file and line:
   - new or changed `omarchy-*` scripts that the shell or the bindings call,
   - new packages in `install/*.packages`,
   - new `Omarchy` strings in catalog values and notifications,
   - new private-use glyphs in `default/fonts/omarchy`,
   - new Arch-only commands (`pacman`, `yay`, `expac`, `limine`, `snapper`).
3. For each item, add a rule, an adaptation, a map entry or an overlay
   change.
   - new features that use Arch, for `adapt.list`.
4. Run `debian/armbian/transform/apply` on a clean upstream tree. Every
   rule must pass.
5. Refresh the patches. Drop the ones that upstream merged.
6. Test (next section). Then open the pull request.

If the new tag needs a Hyprland feature that forky does not have, keep the
old tag. Write the missing feature and the Hyprland version in the pull
request.

## Test

Test on a forky VM and a sid VM with GPU acceleration (virgl). Install the
package and start the Hyprland session.

- `hyprctl configerrors` is empty.
- The shell runs once. The bar shows the Armbian logo and icons, not boxes.
- Super+Space opens the menu. Super+K opens the key sheet.
- `omarchy-theme-set armbian` works, and the lock screen shows the
  Armbian artwork.
- No visible `Omarchy` text: check the menu, the key sheet, notifications
  and the first-run notices.
- Each entry in `adapt.list` works: run the feature from its menu or
  binding (for example add an agent account, install a package, start
  dictation, open a web app).

Also test on real hardware (VMs miss these):

- Install unattended (no terminal): no conffile question.
- Every launcher entry opens. Start them as the launcher does:
  `uwsm-app -- gtk-launch <id>.desktop` through
  `hyprctl dispatch "hl.dsp.exec_cmd([[...]])"`, not from SSH.
- Install and Remove menus show the right entries for installed packages.
- The lock screen unlocks with the password and a fingerprint.
- Audio devices, screen recording (VA-API), firewall rules and SSH access.
- A new user's first run: `~/.local/state/omarchy/first-run.log` has no
  failed step, and `PATH` has the sbin folders.

Add screenshots of the bar, the menu and the lock screen to the pull
request. Name the tested releases and the upstream tag.

## Style

Text, comments, commit messages and pull requests: ASD-STE100 Simplified
Technical English, as in the repository CLAUDE.md. End commit messages
with `Signed-off-by:`.
