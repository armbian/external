//! Armbian first-run wizard.
//!
//! The wizard is a frontend only. It writes the answers as PRESET_* variables to
//! /root/.not_logged_in_yet and runs armbian-firstlogin, which applies them unattended.
//! Network is optional: without it, the values start from the image defaults.

mod data;
mod wifi;

use data::{Item, Location};
use slint::{ComponentHandle, ModelRc, SharedString, StandardListViewItem, VecModel};
use std::cell::RefCell;
use std::collections::BTreeMap;
use std::fs;
use std::io::{BufRead, BufReader};
use std::os::unix::process::CommandExt;
use std::process::{Command, Stdio};
use std::rc::Rc;
use std::sync::mpsc::{channel, Receiver, Sender};

slint::include_modules!();

const PRESET: &str = "/root/.not_logged_in_yet";
const CONFIG: &str = "/etc/armbian/firstrun-gui.conf";
const FIRSTLOGIN: &str = "/usr/lib/armbian/armbian-firstlogin";
const DEFAULT_FONT: &str = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf";
/// Dry run: root-only /run, not the shared /tmp.
const DRY_RUN_OUT: &str = "/run/armbian-firstrun-gui.preset";
/// Answers kept over the restart that loads a new keyboard layout.
const RESUME: &str = "/run/armbian-firstrun-gui.resume";

const PAGE_CHECK: i32 = 0;
const PAGE_WIFI: i32 = 1;
const PAGE_ACCOUNT: i32 = 2;
const PAGE_REGION: i32 = 3;
const PAGE_APPLY: i32 = 4;

struct Args {
    preset: String,
    config: String,
    firstlogin: String,
    dry_run: bool,
}

fn args() -> Args {
    let mut a = Args { preset: PRESET.into(), config: CONFIG.into(), firstlogin: FIRSTLOGIN.into(), dry_run: false };
    let mut it = std::env::args().skip(1);
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--dry-run" => a.dry_run = true,
            "--preset" => a.preset = it.next().unwrap_or_default(),
            "--config" => a.config = it.next().unwrap_or_default(),
            "--firstlogin" => a.firstlogin = it.next().unwrap_or_default(),
            _ => {
                eprintln!("Usage: armbian-firstrun-gui [--dry-run] [--preset FILE] [--config FILE] [--firstlogin FILE]");
                std::process::exit(2);
            }
        }
    }
    a
}

/// KEY=value lines of a shell variables file. Quotes are removed.
fn read_vars(path: &str) -> BTreeMap<String, String> {
    let mut vars = BTreeMap::new();
    for line in fs::read_to_string(path).unwrap_or_default().lines() {
        let line = line.trim();
        if line.starts_with('#') {
            continue;
        }
        if let Some((k, v)) = line.split_once('=') {
            let v = v.trim();
            let v = v
                .strip_prefix('\'')
                .and_then(|v| v.strip_suffix('\''))
                .or_else(|| v.strip_prefix('"').and_then(|v| v.strip_suffix('"')))
                .unwrap_or(v);
            vars.insert(k.trim().to_string(), v.to_string());
        }
    }
    vars
}

fn shell_quote(s: &str) -> String {
    format!("'{}'", s.replace('\'', "'\\''"))
}

/// A list with a search filter. `shown` holds indexes into `all`.
struct List {
    all: Vec<Item>,
    shown: Vec<usize>,
    value: String,
    search: String,
}

impl List {
    fn new(all: Vec<Item>, value: String) -> Self {
        let shown = (0..all.len()).collect();
        List { all, shown, value, search: String::new() }
    }
    fn filter(&mut self, text: &str) {
        self.search = text.to_string();
        let t = text.to_lowercase();
        self.shown = (0..self.all.len()).filter(|&i| self.all[i].label.to_lowercase().contains(&t)).collect();
    }
    fn rows(&self) -> Vec<StandardListViewItem> {
        self.shown.iter().map(|&i| StandardListViewItem::from(self.all[i].label.as_str())).collect()
    }
    fn current(&self) -> i32 {
        self.shown.iter().position(|&i| self.all[i].value == self.value).map_or(-1, |p| p as i32)
    }
    fn pick(&mut self, row: i32) {
        if let Some(&i) = usize::try_from(row).ok().and_then(|r| self.shown.get(r)) {
            self.value = self.all[i].value.clone();
        }
    }
    /// A search hides the value: take the best match. That is the shortest label
    /// that starts with the search text ("german" gives "German (de)"), else the first one.
    fn take_match(&mut self, text: &str) {
        if self.shown.len() == self.all.len() || self.shown.iter().any(|&i| self.all[i].value == self.value) {
            return;
        }
        let t = text.to_lowercase();
        let best = self
            .shown
            .iter()
            .filter(|&&i| self.all[i].label.to_lowercase().starts_with(&t))
            .min_by_key(|&&i| self.all[i].label.len())
            .or(self.shown.first());
        if let Some(&i) = best {
            self.value = self.all[i].value.clone();
        }
    }
    fn label(&self) -> String {
        self.all.iter().find(|i| i.value == self.value).map_or(self.value.clone(), |i| i.label.clone())
    }
}

/// Messages from the worker threads.
enum Msg {
    /// Result of the network check. Online without a location: the location service failed.
    Checked { id: u64, online: bool, loc: Option<Location>, quiet: bool },
    Scanned(Result<Vec<wifi::Net>, String>),
    Connected(Result<(), String>),
}

struct State {
    tz: List,
    locale: List,
    kb: List,
    /// The user changed the value: detection must not replace it.
    touched: [bool; 3],
    username_auto: bool,
    /// The layout that the input uses now.
    active_kb: String,
    /// Draws without X11 or Wayland: a new layout needs a restart.
    kms: bool,
    wifi_iface: Option<String>,
    wifi_nets: Vec<wifi::Net>,
    checking: bool,
    /// Number of the newest network check: the results of older checks are ignored.
    check_id: u64,
    /// Connected to Wi-Fi: no internet does not show the Wi-Fi page again.
    wifi_done: bool,
    dry_run: bool,
    /// Values before the region page opened: Cancel restores them.
    saved: Option<([String; 3], [bool; 3])>,
    tx: Sender<Msg>,
}

fn suggest_username(realname: &str) -> String {
    let first = realname.split_whitespace().next().unwrap_or("").to_lowercase();
    let name: String = first.chars().filter(|c| c.is_ascii_lowercase() || c.is_ascii_digit()).collect();
    name.trim_start_matches(|c: char| c.is_ascii_digit()).to_string()
}

fn user_exists(name: &str) -> bool {
    fs::read_to_string("/etc/passwd").unwrap_or_default().lines().any(|l| l.split(':').next() == Some(name))
}

fn validate_user(ui: &AppWindow) -> Result<(), &'static str> {
    let user = ui.get_username().to_string();
    let valid = !user.is_empty()
        && user.len() <= 32
        && user.starts_with(|c: char| c.is_ascii_lowercase())
        && user.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-' || c == '_');
    if !valid {
        return Err("Username: start with a lower case letter. Use only a-z, 0-9, - and _.");
    }
    if user == "root" || user_exists(&user) {
        return Err("This username exists already.");
    }
    if ui.get_password().is_empty() {
        return Err("Enter a password.");
    }
    if ui.get_password() != ui.get_password2() {
        return Err("The passwords are not the same.");
    }
    Ok(())
}

/// True when /etc/shells lists zsh.
fn has_zsh() -> bool {
    fs::read_to_string("/etc/shells").unwrap_or_default().lines().any(|l| l.trim().ends_with("/zsh"))
}

/// IPv4 addresses of the network interfaces, without container and VM bridges.
fn ip_addresses() -> String {
    let out = Command::new("ip").args(["-o", "-4", "addr", "show", "scope", "global"]).output();
    let text = out.map(|o| String::from_utf8_lossy(&o.stdout).into_owned()).unwrap_or_default();
    parse_ip_addresses(&text)
}

/// Container and VM interfaces. Docker networks are "br-" and 12 hex digits;
/// host bridges such as br-lan stay.
fn is_container_iface(iface: &str) -> bool {
    const SKIP: [&str; 5] = ["docker", "veth", "virbr", "lxc", "cni"];
    let docker_net = iface.strip_prefix("br-").is_some_and(|id| id.len() == 12 && id.bytes().all(|b| b.is_ascii_hexdigit()));
    docker_net || SKIP.iter().any(|p| iface.starts_with(p))
}

/// `ip -o -4 addr` lines: "2: eth0    inet 10.0.2.15/24 ...". Returns "10.0.2.15, ...".
fn parse_ip_addresses(text: &str) -> String {
    let mut addrs: Vec<&str> = vec![];
    for line in text.lines() {
        let f: Vec<&str> = line.split_whitespace().collect();
        let (Some(iface), Some(addr)) = (f.get(1), f.iter().position(|w| *w == "inet").and_then(|i| f.get(i + 1))) else {
            continue;
        };
        if is_container_iface(iface) {
            continue;
        }
        let addr = addr.split('/').next().unwrap_or(addr);
        if !addrs.contains(&addr) {
            addrs.push(addr);
        }
    }
    addrs.join(", ")
}

/// The PRESET_* variables for armbian-firstlogin.
fn preset_vars(ui: &AppWindow, st: &State) -> Vec<(&'static str, String)> {
    let (layout, variant) = st.kb.value.split_once(':').map_or((st.kb.value.clone(), String::new()), |(l, v)| (l.into(), v.into()));
    let password = ui.get_password().to_string();
    vec![
        ("PRESET_ROOT_PASSWORD", password.clone()),
        ("PRESET_USER_NAME", ui.get_username().to_string()),
        ("PRESET_USER_PASSWORD", password),
        ("PRESET_DEFAULT_REALNAME", ui.get_realname().to_string()),
        ("PRESET_TIMEZONE", st.tz.value.clone()),
        ("PRESET_LOCALE", st.locale.value.clone()),
        ("SET_LANG_BASED_ON_LOCATION", "y".into()),
        ("PRESET_KEYBOARD_LAYOUT", layout),
        ("PRESET_KEYBOARD_VARIANT", variant),
        ("PRESET_USER_SHELL", if ui.get_has_zsh() && ui.get_shell() == "zsh" { "zsh".into() } else { "bash".into() }),
    ]
}

/// Keep the lines of the existing file. Replace the variables that the wizard sets.
fn write_preset(path: &str, vars: &[(&str, String)]) -> std::io::Result<()> {
    let mut out = String::new();
    for line in fs::read_to_string(path).unwrap_or_default().lines() {
        let key = line.split('=').next().unwrap_or("").trim();
        if !vars.iter().any(|(k, _)| *k == key) {
            out.push_str(line);
            out.push('\n');
        }
    }
    for (k, v) in vars {
        out.push_str(&format!("{k}={}\n", shell_quote(v)));
    }
    wifi::write_private(path, out.as_bytes())
}

/// Remove escape sequences (colors, clear screen) from firstlogin output.
fn strip_ansi(s: &str) -> String {
    let mut out = String::new();
    let mut chars = s.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '\x1b' {
            if chars.peek() == Some(&'[') {
                chars.next();
                for n in chars.by_ref() {
                    if n.is_ascii_alphabetic() {
                        break;
                    }
                }
            }
        } else if c != '\r' {
            out.push(c);
        }
    }
    out
}

/// Progress of armbian-firstlogin from its output: known steps, else a small step per line.
fn setup_progress(line: &str, current: f32) -> f32 {
    const STEPS: [(&str, f32); 7] = [
        ("Waiting for system to finish booting", 0.10),
        ("Waiting for network startup", 0.20),
        ("Welcome to", 0.30),
        ("Shell:", 0.40),
        ("has been created", 0.60),
        ("Keyboard:", 0.85),
        ("Now starting desktop", 0.95),
    ];
    let step = STEPS.iter().filter(|(s, _)| line.contains(s)).map(|(_, p)| *p).fold(0.0, f32::max);
    step.max(current).max((current + 0.02).min(0.9))
}

/// Run armbian-firstlogin. Its last lines go to the log on the page.
fn run_firstlogin(ui: &AppWindow, firstlogin: &str) {
    let weak = ui.as_weak();
    let firstlogin = firstlogin.to_string();
    std::thread::spawn(move || {
        // armbian-firstlogin needs a terminal (tty -s): run it in one with script(1).
        // One stream keeps the order of the lines.
        let child = Command::new("script")
            .args(["-q", "-e", "-c", &format!("bash {}", shell_quote(&firstlogin)), "/dev/null"])
            .env("TERM", "dumb")
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .spawn();
        let mut child = match child {
            Ok(c) => c,
            Err(e) => {
                let msg = format!("Cannot start {firstlogin}: {e}");
                let _ = weak.upgrade_in_event_loop(move |ui| {
                    ui.set_log(msg.into());
                    ui.set_busy(false);
                    ui.set_failed(true);
                });
                return;
            }
        };
        let mut lines: Vec<String> = Vec::new();
        let mut progress = 0.05f32;
        let _ = weak.upgrade_in_event_loop(move |ui| ui.set_progress(progress));
        if let Some(out) = child.stdout.take() {
            // Bytes, not lines(): a line that is not UTF-8 must not stop the reading.
            let mut reader = BufReader::new(out);
            let mut buf = Vec::new();
            while reader.read_until(b'\n', &mut buf).is_ok_and(|n| n > 0) {
                let line = strip_ansi(String::from_utf8_lossy(&buf).trim_end_matches('\n'));
                buf.clear();
                if line.trim().is_empty() {
                    continue;
                }
                progress = setup_progress(&line, progress);
                lines.push(line);
                // The log shows only after a failure.
                let text = lines[lines.len().saturating_sub(12)..].join("\n");
                let _ = weak.upgrade_in_event_loop(move |ui| {
                    ui.set_log(text.into());
                    ui.set_progress(progress);
                });
            }
        }
        let ok = child.wait().map(|s| s.success()).unwrap_or(false);
        let _ = weak.upgrade_in_event_loop(move |ui| {
            if ok {
                ui.set_progress(1.0);
            }
            ui.set_busy(false);
            ui.set_failed(!ok);
            ui.set_finished(ok);
        });
        // Success: give the screen to tty1 or to the display manager.
        if ok {
            std::thread::sleep(std::time::Duration::from_secs(2));
            std::process::exit(0);
        }
    });
}

/// Restart with the chosen keyboard layout, so that the passwords use it.
fn restart_with_layout(ui: &AppWindow, st: &State) {
    let resume = format!(
        "TZ={}\nLOCALE={}\nKB={}\nNAME={}\nUSER={}\nSHELL={}\n",
        st.tz.value,
        st.locale.value,
        st.kb.value,
        ui.get_realname().replace('\n', " "),
        ui.get_username(),
        ui.get_shell()
    );
    if let Err(e) = fs::write(RESUME, resume) {
        ui.set_error(format!("Cannot save the answers: {e}").into());
        return;
    }
    let (layout, variant) = st.kb.value.split_once(':').unwrap_or((&st.kb.value, ""));
    let exe = std::env::current_exe().unwrap_or_else(|_| "/usr/bin/armbian-firstrun-gui".into());
    let _ = ui.hide();
    let err = Command::new(exe).args(std::env::args().skip(1)).env("XKB_DEFAULT_LAYOUT", layout).env("XKB_DEFAULT_VARIANT", variant).exec();
    eprintln!("Cannot restart: {err}");
    std::process::exit(1);
}

/// Show the account page. A new keyboard layout restarts the wizard first.
fn goto_account(ui: &AppWindow, st: &State) {
    if st.kms && st.kb.value != st.active_kb {
        restart_with_layout(ui, st);
    }
    ui.set_page(PAGE_ACCOUNT);
}

/// Network check and location lookup in a thread. `quiet`: a background check on the Wi-Fi page.
/// A new check replaces a running one: only the newest result counts.
fn start_check(st: &mut State, quiet: bool) {
    if quiet && st.checking {
        return;
    }
    st.checking = true;
    st.check_id += 1;
    let id = st.check_id;
    let tx = st.tx.clone();
    std::thread::spawn(move || {
        // A cable with a link: wait up to 20 s for the address (DHCP). Else check once:
        // the Wi-Fi page checks again every 5 s, for a cable that comes later.
        let start = std::time::Instant::now();
        let (online, loc) = loop {
            let r = if wifi::fake_offline() { (false, None) } else { data::detect() };
            if r.0 || quiet || !wifi::wired_link() || start.elapsed().as_secs() >= 20 {
                break r;
            }
            std::thread::sleep(std::time::Duration::from_secs(2));
        };
        let _ = tx.send(Msg::Checked { id, online, loc, quiet });
    });
}

fn start_scan(ui: &AppWindow, st: &State) {
    let Some(iface) = st.wifi_iface.clone() else { return };
    ui.set_wifi_busy(true);
    ui.set_wifi_status("Searching for networks…".into());
    let tx = st.tx.clone();
    std::thread::spawn(move || {
        let _ = tx.send(Msg::Scanned(wifi::scan(&iface)));
    });
}

/// Use the location for the values that the user did not change.
fn apply_location(st: &mut State, loc: &Location) {
    if !st.touched[0] {
        data::add_timezone(&mut st.tz.all, &loc.timezone);
        if st.tz.all.iter().any(|i| i.value == loc.timezone) {
            st.tz.value = loc.timezone.clone();
            st.tz.filter("");
        }
    }
    if !st.touched[1] {
        if let Some(l) = data::locale_for(&st.locale.all, &loc.country_code) {
            st.locale.value = l;
        }
    }
    if !st.touched[2] {
        if let Some(k) = data::keyboard_for(&st.kb.all, &loc.country_code) {
            st.kb.value = k;
        }
    }
}

fn handle(ui: &AppWindow, st: &Rc<RefCell<State>>, msg: Msg, refresh: &dyn Fn(bool)) {
    match msg {
        Msg::Checked { id, online, loc, quiet } => {
            // An older check, or the user is on another page now.
            if id != st.borrow().check_id || ![PAGE_CHECK, PAGE_WIFI].contains(&ui.get_page()) {
                return;
            }
            st.borrow_mut().checking = false;
            if let Some(loc) = loc {
                apply_location(&mut st.borrow_mut(), &loc);
                refresh(true);
            }
            if online || st.borrow().wifi_done {
                // Without a location: the image defaults.
                goto_account(ui, &st.borrow());
            } else if quiet {
                // Background check on the Wi-Fi page: still offline.
            } else if st.borrow().wifi_iface.is_some() {
                ui.set_page(PAGE_WIFI);
                start_scan(ui, &st.borrow());
            } else {
                // No network and no Wi-Fi: the image defaults.
                goto_account(ui, &st.borrow());
            }
        }
        Msg::Scanned(Err(e)) => {
            ui.set_wifi_busy(false);
            ui.set_wifi_status("".into());
            ui.set_error(e.into());
        }
        Msg::Scanned(Ok(nets)) => {
            ui.set_wifi_busy(false);
            ui.set_wifi_status(if nets.is_empty() { "No networks found.".into() } else { "".into() });
            let rows: Vec<WifiNet> =
                nets.iter().map(|n| WifiNet { ssid: n.ssid.as_str().into(), signal: n.signal, secure: n.secure() }).collect();
            ui.set_wifi_model(ModelRc::new(VecModel::from(rows)));
            ui.set_wifi_current(if nets.is_empty() { -1 } else { 0 });
            ui.set_wifi_password("".into());
            st.borrow_mut().wifi_nets = nets;
        }
        Msg::Connected(Ok(())) => {
            ui.set_wifi_busy(false);
            if st.borrow().dry_run {
                // Nothing changed: no network to check.
                goto_account(ui, &st.borrow());
                return;
            }
            st.borrow_mut().wifi_done = true;
            ui.set_page(PAGE_CHECK);
            ui.set_status("Connected. Detecting your location…".into());
            start_check(&mut st.borrow_mut(), false);
        }
        Msg::Connected(Err(e)) => {
            ui.set_wifi_busy(false);
            ui.set_wifi_status("".into());
            ui.set_error(e.into());
        }
    }
}

/// Name (eDP-1) and modes of the first connected display, in the order of the kernel.
/// The first mode is the preferred one.
fn screen_modes() -> (String, Vec<(u32, u32)>) {
    let Ok(dir) = fs::read_dir("/sys/class/drm") else { return Default::default() };
    let mut dirs: Vec<_> = dir.flatten().map(|e| e.path()).collect();
    dirs.sort();
    dirs.iter()
        .filter(|d| fs::read_to_string(d.join("status")).is_ok_and(|s| s.trim() == "connected"))
        .find_map(|d| {
            let modes: Vec<(u32, u32)> = fs::read_to_string(d.join("modes"))
                .ok()?
                .lines()
                .filter_map(|l| {
                    let (w, h) = l.split_once('x')?;
                    Some((w.parse().ok()?, h.trim_end_matches(|c: char| !c.is_ascii_digit()).parse().ok()?))
                })
                .collect();
            let name = d.file_name()?.to_string_lossy().split_once('-')?.1.to_string();
            (!modes.is_empty()).then_some((name, modes))
        })
        .unwrap_or_default()
}

/// Sets SLINT_DRM_MODE (index of a smaller mode with the same aspect) or SLINT_SCALE_FACTOR.
fn choose_mode() {
    if std::env::var_os("SLINT_DRM_MODE").is_some() || std::env::var_os("SLINT_SCALE_FACTOR").is_some() {
        return;
    }
    let (output, modes) = screen_modes();
    let Some(&(pw, ph)) = modes.first() else { return };
    if ph <= 1200 {
        return;
    }
    let smaller = modes
        .iter()
        .enumerate()
        .filter(|(_, &(w, h))| (720..=1200).contains(&h) && w * ph == h * pw)
        .max_by_key(|(_, &(w, h))| w * h);
    match smaller {
        Some((i, _)) => {
            // The mode index belongs to this display: Slint must use the same one.
            std::env::set_var("SLINT_DRM_OUTPUT", output);
            std::env::set_var("SLINT_DRM_MODE", i.to_string());
        }
        None => {
            let scale = ((ph as f32 / 900.0) * 4.0).floor() / 4.0;
            std::env::set_var("SLINT_SCALE_FACTOR", scale.to_string());
        }
    }
}

fn main() {
    let a = args();
    wifi::init();

    // Presets that answer everything: armbian-firstlogin runs unattended without the wizard.
    let preset = read_vars(&a.preset);
    let has = |k: &str| preset.get(k).is_some_and(|v| !v.is_empty());
    if !a.dry_run && (has("PRESET_ROOT_PASSWORD") || has("PRESET_USER_NAME")) {
        println!("{}: presets found, armbian-firstlogin runs unattended", a.preset);
        return;
    }

    // Theme. FONT is a font file or a font family. Default: DejaVu Sans, which has the password bullet.
    let conf = read_vars(&a.config);
    let font = conf.get("FONT").cloned().filter(|f| !f.is_empty()).unwrap_or_else(|| DEFAULT_FONT.into());
    if font.starts_with('/') && std::path::Path::new(&font).exists() {
        std::env::set_var("SLINT_DEFAULT_FONT", &font);
    }

    // Without X11 and Wayland the wizard draws on DRM/KMS, or on /dev/fb0 without DRM.
    let kms = std::env::var_os("DISPLAY").is_none() && std::env::var_os("WAYLAND_DISPLAY").is_none();
    let has_drm = fs::read_dir("/dev/dri").map(|d| d.flatten().any(|e| e.file_name().to_string_lossy().starts_with("card"))).unwrap_or(false);
    if kms && !has_drm && std::path::Path::new("/dev/fb0").exists() {
        std::env::set_var("SLINT_BACKEND_LINUXFB", "1");
    }

    // Large screens: a mode of 1200 lines or less, else a scale factor. The software
    // renderer draws every pixel: 2880x1800 is slow on small CPUs.
    if kms && has_drm {
        choose_mode();
    }

    let ui = AppWindow::new().expect("cannot create the window");
    ui.set_dry_run(a.dry_run);
    ui.set_has_zsh(has_zsh());
    ui.set_ip_address(ip_addresses().into());
    if !font.starts_with('/') {
        ui.set_font_family(font.into());
    }
    if let Some(title) = conf.get("TITLE").filter(|t| !t.is_empty()) {
        ui.set_product(title.into());
    }
    if let Some(c) = conf.get("ACCENT").and_then(|c| u32::from_str_radix(c.trim_start_matches('#'), 16).ok()) {
        ui.global::<Theme>().set_accent(slint::Color::from_argb_encoded(0xff00_0000 | c));
    }
    if let Some(logo) = conf.get("LOGO").filter(|l| !l.is_empty()) {
        match slint::Image::load_from_path(std::path::Path::new(logo)) {
            Ok(img) => ui.set_logo(img),
            Err(_) => eprintln!("Cannot load the logo {logo}"),
        }
    }
    if let Some(bg) = conf.get("BACKGROUND").filter(|b| !b.is_empty()) {
        match slint::Image::load_from_path(std::path::Path::new(bg)) {
            Ok(img) => {
                ui.set_background_image(img);
                ui.set_has_background(true);
            }
            Err(_) => eprintln!("Cannot load the background {bg}"),
        }
    }

    // Start values: presets, else the answers before the restart, else the image defaults.
    let (tz, locale, kb) = data::system_defaults();
    let resume = read_vars(RESUME);
    let _ = fs::remove_file(RESUME);
    let resumed = !resume.is_empty();
    let start = |p: &str, r: &str, d: String| {
        let some = |v: &&String| !v.is_empty();
        preset.get(p).filter(some).or(resume.get(r).filter(some)).cloned().unwrap_or(d)
    };
    let kb_preset = preset.get("PRESET_KEYBOARD_LAYOUT").filter(|l| !l.is_empty()).map(|l| {
        match preset.get("PRESET_KEYBOARD_VARIANT").filter(|v| !v.is_empty()) {
            Some(v) => format!("{l}:{v}"),
            None => l.clone(),
        }
    });
    let active_kb = match (std::env::var("XKB_DEFAULT_LAYOUT"), std::env::var("XKB_DEFAULT_VARIANT")) {
        (Ok(l), Ok(v)) if !v.is_empty() => format!("{l}:{v}"),
        (Ok(l), _) => l,
        _ => kb.clone(),
    };
    let (tx, rx): (Sender<Msg>, Receiver<Msg>) = channel();
    let st = Rc::new(RefCell::new(State {
        tz: {
            let value = start("PRESET_TIMEZONE", "TZ", tz);
            let mut all = data::timezones();
            data::add_timezone(&mut all, &value);
            List::new(all, value)
        },
        locale: List::new(data::locales(), start("PRESET_LOCALE", "LOCALE", locale)),
        kb: List::new(data::keyboards(), kb_preset.clone().or_else(|| resume.get("KB").cloned()).unwrap_or(kb)),
        touched: [has("PRESET_TIMEZONE") || resumed, has("PRESET_LOCALE") || resumed, kb_preset.is_some() || resumed],
        // After a restart: the username was edited when it is not the one from the name.
        username_auto: resume.get("USER").is_none_or(|u| u.is_empty() || *u == suggest_username(resume.get("NAME").map_or("", |n| n.as_str()))),
        active_kb,
        kms,
        wifi_iface: wifi::interface(),
        wifi_nets: vec![],
        checking: false,
        check_id: 0,
        wifi_done: false,
        dry_run: a.dry_run,
        saved: None,
        tx,
    }));

    // Models keep their identity; only their rows change. Then the list views keep their state.
    let tz_rows = Rc::new(VecModel::<StandardListViewItem>::default());
    let locale_rows = Rc::new(VecModel::<StandardListViewItem>::default());
    let kb_rows = Rc::new(VecModel::<StandardListViewItem>::default());
    ui.set_tz_model(ModelRc::from(tz_rows.clone()));
    ui.set_locale_model(ModelRc::from(locale_rows.clone()));
    ui.set_kb_model(ModelRc::from(kb_rows.clone()));

    let refresh: Rc<dyn Fn(bool)> = {
        let weak = ui.as_weak();
        let st = st.clone();
        Rc::new(move |rows: bool| {
            let ui = weak.unwrap();
            let s = st.borrow();
            if rows {
                tz_rows.set_vec(s.tz.rows());
                locale_rows.set_vec(s.locale.rows());
                kb_rows.set_vec(s.kb.rows());
            }
            ui.set_tz_current(s.tz.current());
            ui.set_timezone(s.tz.label().into());
            ui.set_locale_current(s.locale.current());
            ui.set_locale(s.locale.label().into());
            ui.set_kb_current(s.kb.current());
            ui.set_keyboard(s.kb.label().into());
        })
    };
    refresh(true);

    // Lists: search and pick.
    macro_rules! wire_list {
        ($search:ident, $pick:ident, $field:ident, $n:expr) => {{
            let (st2, r2) = (st.clone(), refresh.clone());
            ui.$search(move |t: SharedString| {
                st2.borrow_mut().$field.filter(&t);
                r2(true);
            });
            let (st2, r2) = (st.clone(), refresh.clone());
            ui.$pick(move |row| {
                {
                    let mut s = st2.borrow_mut();
                    let before = s.$field.value.clone();
                    s.$field.pick(row);
                    if s.$field.value == before {
                        return;
                    }
                    s.touched[$n] = true;
                }
                r2(false);
            });
        }};
    }
    wire_list!(on_search_tz, on_pick_tz, tz, 0);
    wire_list!(on_search_locale, on_pick_locale, locale, 1);
    wire_list!(on_search_kb, on_pick_kb, kb, 2);

    // The username follows the name until the user edits it.
    {
        let (weak, st2) = (ui.as_weak(), st.clone());
        ui.on_realname_edited(move |name| {
            if st2.borrow().username_auto {
                weak.unwrap().set_username(suggest_username(&name).into());
            }
        });
        let st2 = st.clone();
        ui.on_username_edited(move |_| st2.borrow_mut().username_auto = false);
    }

    // Wi-Fi page.
    {
        let (weak, st2) = (ui.as_weak(), st.clone());
        ui.on_wifi_rescan(move || start_scan(&weak.unwrap(), &st2.borrow()));
        let (weak, st2) = (ui.as_weak(), st.clone());
        ui.on_wifi_skip(move || goto_account(&weak.unwrap(), &st2.borrow()));
        let (weak, st2) = (ui.as_weak(), st.clone());
        ui.on_wifi_connect(move || {
            let ui = weak.unwrap();
            // One attempt at a time.
            if ui.get_wifi_busy() {
                return;
            }
            let s = st2.borrow();
            let (Some(iface), Some(net)) = (s.wifi_iface.clone(), usize::try_from(ui.get_wifi_current()).ok().and_then(|i| s.wifi_nets.get(i)).cloned())
            else {
                return;
            };
            let password = ui.get_wifi_password().to_string();
            if net.secure() && password.is_empty() {
                ui.set_error("Enter the password of the network.".into());
                return;
            }
            ui.set_error("".into());
            ui.set_wifi_busy(true);
            ui.set_wifi_status(format!("Connecting to {}…", net.ssid).into());
            let (tx, dry_run) = (s.tx.clone(), s.dry_run);
            std::thread::spawn(move || {
                let _ = tx.send(Msg::Connected(wifi::connect(&iface, &net, &password, dry_run)));
            });
        });
    }

    // Region page. Cancel and Escape restore the values from before.
    {
        let (weak, st2) = (ui.as_weak(), st.clone());
        ui.on_change_region(move || {
            let ui = weak.unwrap();
            let mut s = st2.borrow_mut();
            s.saved = Some(([s.tz.value.clone(), s.locale.value.clone(), s.kb.value.clone()], s.touched));
            ui.set_error("".into());
            ui.set_page(PAGE_REGION);
        });
        let (weak, st2, r2) = (ui.as_weak(), st.clone(), refresh.clone());
        ui.on_region_done(move || {
            {
                let mut guard = st2.borrow_mut();
                let s = &mut *guard;
                s.saved = None;
                for (n, list) in [&mut s.tz, &mut s.locale, &mut s.kb].into_iter().enumerate() {
                    let (before, text) = (list.value.clone(), list.search.clone());
                    list.take_match(&text);
                    if list.value != before {
                        s.touched[n] = true;
                    }
                }
                s.tz.filter("");
                s.locale.filter("");
                s.kb.filter("");
            }
            r2(true);
            goto_account(&weak.unwrap(), &st2.borrow());
        });
        let (weak, st2, r2) = (ui.as_weak(), st.clone(), refresh.clone());
        ui.on_region_cancel(move || {
            {
                let mut s = st2.borrow_mut();
                if let Some(([tz, locale, kb], touched)) = s.saved.take() {
                    s.tz.value = tz;
                    s.locale.value = locale;
                    s.kb.value = kb;
                    s.touched = touched;
                }
                s.tz.filter("");
                s.locale.filter("");
                s.kb.filter("");
            }
            r2(true);
            weak.unwrap().set_page(PAGE_ACCOUNT);
        });
    }

    // Apply.
    {
        let weak = ui.as_weak();
        let st2 = st.clone();
        let preset_path = a.preset.clone();
        let firstlogin = a.firstlogin.clone();
        let dry_run = a.dry_run;
        ui.on_apply(move || {
            let ui = weak.unwrap();
            if let Err(e) = validate_user(&ui) {
                ui.set_error(e.into());
                return;
            }
            ui.set_error("".into());
            let vars = preset_vars(&ui, &st2.borrow());
            ui.set_page(PAGE_APPLY);
            if dry_run {
                let shown: Vec<String> = vars
                    .iter()
                    .map(|(k, v)| if k.contains("PASSWORD") { format!("{k}='********'") } else { format!("{k}={}", shell_quote(v)) })
                    .collect();
                match write_preset(DRY_RUN_OUT, &vars) {
                    Ok(()) => ui.set_log(format!("Dry run. Written to {DRY_RUN_OUT}:\n\n{}", shown.join("\n")).into()),
                    Err(e) => ui.set_log(format!("Cannot write {DRY_RUN_OUT}: {e}").into()),
                }
                ui.set_finished(true);
            } else if let Err(e) = write_preset(&preset_path, &vars) {
                ui.set_log(format!("Cannot write {preset_path}: {e}").into());
                ui.set_failed(true);
            } else {
                ui.set_busy(true);
                run_firstlogin(&ui, &firstlogin);
            }
        });
    }
    // Exit at once: quit_event_loop() does not end the linuxkms event loop.
    ui.on_finish(|| std::process::exit(0));
    ui.on_text_mode(|| std::process::exit(1));

    // Key repeat. libinput reports one press, and the linuxkms backend of Slint does not
    // repeat. X11 and Wayland repeat in the server. Same timing as the X11 default.
    if kms {
        let held: Rc<RefCell<Option<SharedString>>> = Rc::new(RefCell::new(None));
        let synthetic = Rc::new(std::cell::Cell::new(false));
        let delay = Rc::new(slint::Timer::default());
        let repeat = Rc::new(slint::Timer::default());
        let no_repeat: Vec<SharedString> = [
            slint::platform::Key::Shift, slint::platform::Key::ShiftR, slint::platform::Key::Control,
            slint::platform::Key::ControlR, slint::platform::Key::Alt, slint::platform::Key::AltGr,
            slint::platform::Key::Meta, slint::platform::Key::MetaR, slint::platform::Key::CapsLock,
            // Held Enter or Escape must not submit twice.
            slint::platform::Key::Return, slint::platform::Key::Escape,
        ]
        .into_iter()
        .map(SharedString::from)
        .collect();
        {
            let (held, synthetic, delay, repeat, weak) = (held.clone(), synthetic.clone(), delay.clone(), repeat.clone(), ui.as_weak());
            ui.on_key_down(move |text| {
                if synthetic.get() {
                    return;
                }
                repeat.stop();
                if no_repeat.contains(&text) || text.is_empty() {
                    *held.borrow_mut() = None;
                    delay.stop();
                    return;
                }
                *held.borrow_mut() = Some(text);
                let (held, synthetic, repeat, weak) = (held.clone(), synthetic.clone(), repeat.clone(), weak.clone());
                delay.start(slint::TimerMode::SingleShot, std::time::Duration::from_millis(500), move || {
                    let (held, synthetic, weak) = (held.clone(), synthetic.clone(), weak.clone());
                    repeat.start(slint::TimerMode::Repeated, std::time::Duration::from_millis(33), move || {
                        let (Some(ui), Some(text)) = (weak.upgrade(), held.borrow().clone()) else { return };
                        synthetic.set(true);
                        let _ = ui.window().try_dispatch_event(slint::platform::WindowEvent::KeyPressed { text });
                        synthetic.set(false);
                    });
                });
            });
        }
        ui.on_key_up(move |text| {
            if held.borrow().as_ref() == Some(&text) {
                *held.borrow_mut() = None;
                delay.stop();
                repeat.stop();
            }
        });
    }

    // Start: after a restart on the account page, else with the network check.
    if resumed {
        ui.set_realname(resume.get("NAME").cloned().unwrap_or_default().into());
        ui.set_username(resume.get("USER").cloned().unwrap_or_default().into());
        if let Some(sh) = resume.get("SHELL").filter(|v| !v.is_empty()) {
            ui.set_shell(sh.into());
        }
        ui.set_page(PAGE_ACCOUNT);
    } else {
        ui.set_page(PAGE_CHECK);
        ui.set_status("Checking the network…".into());
        start_check(&mut st.borrow_mut(), false);
    }

    // Worker results. On the Wi-Fi page: check every 5 s for a cable.
    let timer = slint::Timer::default();
    {
        let (weak, st2, r2) = (ui.as_weak(), st.clone(), refresh.clone());
        let mut ticks = 0u32;
        timer.start(slint::TimerMode::Repeated, std::time::Duration::from_millis(200), move || {
            let ui = weak.unwrap();
            while let Ok(msg) = rx.try_recv() {
                handle(&ui, &st2, msg, &*r2);
            }
            ticks += 1;
            if ticks % 15 == 0 {
                ui.set_ip_address(ip_addresses().into());
            }
            if ticks % 25 == 0 && ui.get_page() == PAGE_WIFI && !ui.get_wifi_busy() {
                start_check(&mut st2.borrow_mut(), true);
            }
        });
    }

    ui.run().expect("cannot run the window");
    drop(timer);
    // Exit code 1: the service starts the text mode.
    if ui.get_failed() {
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn username_from_name() {
        assert_eq!(suggest_username("Igor Pečovnik"), "igor");
        assert_eq!(suggest_username("  Ana-Marija X"), "anamarija");
        assert_eq!(suggest_username("42 Bob"), "");
    }

    #[test]
    fn quote() {
        assert_eq!(shell_quote("it's"), "'it'\\''s'");
    }

    #[test]
    fn list_filter() {
        let mut l = List::new(
            vec![
                Item { value: "a".into(), label: "Alpha".into(), countries: vec![] },
                Item { value: "b".into(), label: "Beta".into(), countries: vec![] },
            ],
            "b".into(),
        );
        assert_eq!(l.current(), 1);
        l.filter("bet");
        assert_eq!(l.current(), 0);
        assert_eq!(l.rows().len(), 1);
        l.pick(0);
        assert_eq!(l.value, "b");
    }

    #[test]
    fn strip() {
        assert_eq!(strip_ansi("\x1b[92mok\x1b[0m\r"), "ok");
    }

    #[test]
    fn progress() {
        let near = |a: f32, b: f32| (a - b).abs() < 1e-6;
        assert!(near(setup_progress("Shell: BASH", 0.1), 0.4));
        assert!(near(setup_progress("some line", 0.4), 0.42));
        assert!(near(setup_progress("some line", 0.9), 0.9));
        assert!(near(setup_progress("Now starting desktop environment via sddm...", 0.6), 0.95));
        assert!(near(setup_progress("some line", 0.95), 0.95));
    }

    #[test]
    fn ip_list() {
        let text = "2: enp1s0    inet 10.0.2.15/24 brd 10.0.2.255 scope global dynamic enp1s0\n\
                    3: docker0    inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0\n\
                    4: wlan0    inet 192.168.1.20/24 brd 192.168.1.255 scope global wlan0\n\
                    5: br-3f2a9c1d8e7b    inet 172.18.0.1/16 brd 172.18.255.255 scope global br-3f2a9c1d8e7b\n\
                    6: br-lan    inet 192.168.2.1/24 brd 192.168.2.255 scope global br-lan\n";
        assert_eq!(parse_ip_addresses(text), "10.0.2.15, 192.168.1.20, 192.168.2.1");
        assert_eq!(parse_ip_addresses(""), "");
    }
}
