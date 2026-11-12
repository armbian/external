//! Wi-Fi for the first boot. NetworkManager when it runs, else netplan.
//! The wizard writes its own profile file, and removes only that file on failure.

use std::fs;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::process::Command;
use std::sync::atomic::{AtomicBool, Ordering};

/// The netplan file of armbian-firstlogin. A failed attempt restores its old content.
const NETPLAN: &str = "/etc/netplan/30-wifis-dhcp.yaml";
/// NetworkManager profiles. The name is the SSID, as `nmcli dev wifi connect` gives it.
/// A keyfile keeps the password out of process arguments.
const NM_DIR: &str = "/etc/NetworkManager/system-connections";

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Auth {
    Open,
    /// WPA or WPA2 personal, also WPA2/WPA3 transition mode.
    Psk,
    /// WPA3 personal only.
    Sae,
}

#[derive(Clone, Debug)]
pub struct Net {
    pub ssid: String,
    /// 0 to 100.
    pub signal: i32,
    pub auth: Auth,
}

impl Net {
    pub fn secure(&self) -> bool {
        self.auth != Auth::Open
    }
}

/// Development only (FRG_FAKE_WIFI): a fake offline system with fake networks.
static FAKE_OFFLINE: AtomicBool = AtomicBool::new(false);

fn fake() -> bool {
    cfg!(feature = "dev") && std::env::var_os("FRG_FAKE_WIFI").is_some()
}

pub fn init() {
    FAKE_OFFLINE.store(fake(), Ordering::Relaxed);
}

/// The system is offline for the development fake.
pub fn fake_offline() -> bool {
    FAKE_OFFLINE.load(Ordering::Relaxed)
}

/// Write a file that only root can read. The temporary file is created new (O_EXCL),
/// with mode 0600 from the start: it does not follow a symbolic link.
pub fn write_private(path: &str, content: &[u8]) -> std::io::Result<()> {
    let tmp = format!("{path}.tmp");
    let _ = fs::remove_file(&tmp);
    let mut f = fs::OpenOptions::new().write(true).create_new(true).mode(0o600).open(&tmp)?;
    f.write_all(content)?;
    f.sync_all()?;
    fs::rename(&tmp, path)
}

/// The first wireless interface.
pub fn interface() -> Option<String> {
    if fake() {
        return Some("wlan0".into());
    }
    let mut names: Vec<String> = fs::read_dir("/sys/class/net")
        .ok()?
        .flatten()
        .filter(|e| e.path().join("wireless").exists() || e.path().join("phy80211").exists())
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .collect();
    names.sort();
    names.into_iter().next()
}

fn nm_running() -> bool {
    Command::new("nmcli")
        .args(["-t", "-f", "RUNNING", "general"])
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).trim() == "running")
        .unwrap_or(false)
}

/// Unblock soft-blocked wireless radios, as `rfkill unblock wifi`.
/// Error: a hardware switch or key blocks the radio.
fn unblock() -> Result<(), String> {
    let Ok(dir) = fs::read_dir("/sys/class/rfkill") else { return Ok(()) };
    let mut hard = false;
    let mut changed = false;
    for e in dir.flatten() {
        let p = e.path();
        if fs::read_to_string(p.join("type")).map_or(true, |t| t.trim() != "wlan") {
            continue;
        }
        hard |= fs::read_to_string(p.join("hard")).is_ok_and(|v| v.trim() == "1");
        if fs::read_to_string(p.join("soft")).is_ok_and(|v| v.trim() == "1") {
            changed |= fs::write(p.join("soft"), "0").is_ok();
        }
    }
    if hard {
        return Err("Wireless is off: turn it on with the switch or key of the device.".into());
    }
    if changed {
        // The driver needs a moment before the interface can come up.
        std::thread::sleep(std::time::Duration::from_secs(1));
    }
    Ok(())
}

/// Visible networks, strongest first. One entry per name.
/// Scanning turns the radio on: that is not a configuration change.
pub fn scan(iface: &str) -> Result<Vec<Net>, String> {
    if !fake() {
        unblock()?;
        if nm_running() {
            let _ = Command::new("nmcli").args(["radio", "wifi", "on"]).status();
        }
    }
    let mut nets = if fake() {
        std::thread::sleep(std::time::Duration::from_secs(1));
        vec![
            Net { ssid: "Armbian-Lab".into(), signal: 82, auth: Auth::Psk },
            Net { ssid: "Guest".into(), signal: 55, auth: Auth::Open },
            Net { ssid: "Neighbour 5G".into(), signal: 31, auth: Auth::Sae },
        ]
    } else if nm_running() {
        scan_nm(iface)
    } else {
        scan_iw(iface)
    };
    nets.retain(|n| !n.ssid.is_empty());
    nets.sort_by(|a, b| b.signal.cmp(&a.signal));
    let mut seen = std::collections::HashSet::new();
    nets.retain(|n| seen.insert(n.ssid.clone()));
    Ok(nets)
}

/// nmcli terse output: fields split by ":", and "\:" is a colon in a field.
fn split_terse(line: &str) -> Vec<String> {
    let mut fields = vec![String::new()];
    let mut chars = line.chars();
    while let Some(c) = chars.next() {
        match c {
            '\\' => fields.last_mut().unwrap().extend(chars.next()),
            ':' => fields.push(String::new()),
            _ => fields.last_mut().unwrap().push(c),
        }
    }
    fields
}

/// nmcli SECURITY: "WPA3" alone is SAE. "WPA2 WPA3" (transition) takes PSK.
fn nm_auth(security: &str) -> Auth {
    let s = security.trim();
    if s.is_empty() || s == "--" {
        Auth::Open
    } else if s.contains("WPA3") && !s.contains("WPA2") && !s.contains("WPA1") {
        Auth::Sae
    } else {
        Auth::Psk
    }
}

fn scan_nm(iface: &str) -> Vec<Net> {
    let out = Command::new("nmcli")
        .args(["-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "ifname", iface, "--rescan", "yes"])
        .output();
    let Ok(out) = out else { return vec![] };
    String::from_utf8_lossy(&out.stdout)
        .lines()
        .filter_map(|l| {
            let f = split_terse(l);
            (f.len() >= 3).then(|| Net { ssid: f[0].clone(), signal: f[1].parse().unwrap_or(0), auth: nm_auth(&f[2]) })
        })
        .collect()
}

/// "\x20" escapes of iw.
fn unescape_iw(s: &str) -> String {
    let mut bytes = Vec::new();
    let b = s.as_bytes();
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'\\' && i + 3 < b.len() && b[i + 1] == b'x' {
            if let Ok(v) = u8::from_str_radix(&s[i + 2..i + 4], 16) {
                bytes.push(v);
                i += 4;
                continue;
            }
        }
        bytes.push(b[i]);
        i += 1;
    }
    String::from_utf8_lossy(&bytes).into_owned()
}

fn parse_iw(text: &str) -> Vec<Net> {
    let mut nets: Vec<Net> = Vec::new();
    for line in text.lines() {
        let t = line.trim().trim_start_matches("* ");
        if line.starts_with("BSS ") {
            nets.push(Net { ssid: String::new(), signal: 0, auth: Auth::Open });
        } else if let Some(n) = nets.last_mut() {
            if let Some(v) = t.strip_prefix("signal: ") {
                // dBm to 0..100: -100 dBm is 0, -50 dBm is 100.
                let dbm: f32 = v.split_whitespace().next().and_then(|x| x.parse().ok()).unwrap_or(-100.0);
                n.signal = (2.0 * (dbm + 100.0)).clamp(0.0, 100.0) as i32;
            } else if let Some(v) = t.strip_prefix("SSID: ") {
                n.ssid = unescape_iw(v);
            } else if let Some(v) = t.strip_prefix("Authentication suites: ") {
                // SAE without PSK: WPA3 only. With PSK: transition mode, PSK works.
                n.auth = if v.contains("SAE") && !v.contains("PSK") { Auth::Sae } else { Auth::Psk };
            } else if (t.starts_with("capability:") && t.contains("Privacy") || t.starts_with("RSN:") || t.starts_with("WPA:"))
                && n.auth == Auth::Open
            {
                n.auth = Auth::Psk;
            }
        }
    }
    nets
}

fn iw(args: &[&str]) -> Vec<Net> {
    Command::new("iw").args(args).output().map(|o| parse_iw(&String::from_utf8_lossy(&o.stdout))).unwrap_or_default()
}

fn scan_iw(iface: &str) -> Vec<Net> {
    let _ = Command::new("ip").args(["link", "set", iface, "up"]).status();
    for _ in 0..5 {
        // "busy": the first scan after "up", or wpa_supplicant scans at the same time.
        // Then take the last results of the other scan.
        let nets = iw(&["dev", iface, "scan"]);
        let nets = if nets.is_empty() { iw(&["dev", iface, "scan", "dump"]) } else { nets };
        if !nets.is_empty() {
            return nets;
        }
        std::thread::sleep(std::time::Duration::from_secs(2));
    }
    vec![]
}

/// The netplan file for one network. JSON strings are valid YAML strings.
fn netplan_yaml(iface: &str, net: &Net, password: &str) -> String {
    let q = |s: &str| serde_json::to_string(s).unwrap_or_default();
    let ap = match net.auth {
        Auth::Open => "{}".to_string(),
        Auth::Psk => format!("\n          password: {}", q(password)),
        Auth::Sae => format!("\n          auth:\n            key-management: sae\n            password: {}", q(password)),
    };
    format!(
        "# Created by armbian-firstrun-gui\nnetwork:\n  wifis:\n    {}:\n      dhcp4: true\n      dhcp6: true\n      access-points:\n        {}: {}\n",
        q(iface),
        q(&net.ssid),
        ap
    )
}

/// A value of a GLib key file: escape backslash, line breaks and edge spaces.
fn keyfile_value(s: &str) -> String {
    let mut v = s.replace('\\', "\\\\").replace('\n', "\\n").replace('\r', "\\r").replace('\t', "\\t");
    if v.starts_with(' ') {
        v.replace_range(0..1, "\\s");
    }
    v
}

/// The NetworkManager keyfile for one network. The SSID is a byte list: any name works.
fn nm_keyfile(iface: &str, net: &Net, password: &str, uuid: &str) -> String {
    let ssid: String = net.ssid.bytes().map(|b| format!("{b};")).collect();
    let mut s = format!(
        "# Created by armbian-firstrun-gui\n[connection]\nid={}\nuuid={uuid}\ntype=wifi\ninterface-name={}\n\n[wifi]\nmode=infrastructure\nssid={ssid}\n\n",
        keyfile_value(&net.ssid),
        keyfile_value(iface)
    );
    match net.auth {
        Auth::Open => {}
        Auth::Psk => s.push_str(&format!("[wifi-security]\nkey-mgmt=wpa-psk\npsk={}\n\n", keyfile_value(password))),
        Auth::Sae => s.push_str(&format!("[wifi-security]\nkey-mgmt=sae\npsk={}\n\n", keyfile_value(password))),
    }
    s.push_str("[ipv4]\nmethod=auto\n\n[ipv6]\nmethod=auto\n");
    s
}

/// The interface has an IPv4 address: the connection works, with or without internet.
fn has_address(iface: &str) -> bool {
    Command::new("ip")
        .args(["-4", "-o", "addr", "show", "dev", iface])
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).contains(" inet "))
        .unwrap_or(false)
}

const WRONG: &str = "Cannot connect: wrong password, or the network is out of range.";

/// Connect the interface to the network and wait for an address.
/// Failure: remove the profile of the wizard again. Dry run: change nothing.
pub fn connect(iface: &str, net: &Net, password: &str, dry_run: bool) -> Result<(), String> {
    if fake() || dry_run {
        std::thread::sleep(std::time::Duration::from_secs(2));
        if password == "wrong" {
            return Err(WRONG.into());
        }
        if fake() && !dry_run {
            FAKE_OFFLINE.store(false, Ordering::Relaxed);
        }
        return Ok(());
    }
    let nm = nm_running();
    if nm {
        let profile = format!("{NM_DIR}/{}.nmconnection", net.ssid.replace('/', "_"));
        let old = fs::read(&profile).ok();
        let uuid = fs::read_to_string("/proc/sys/kernel/random/uuid").map_err(|e| format!("uuid: {e}"))?;
        let uuid = uuid.trim();
        write_private(&profile, nm_keyfile(iface, net, password, uuid).as_bytes())
            .map_err(|e| format!("Cannot write {profile}: {e}"))?;
        let _ = Command::new("nmcli").args(["connection", "load", &profile]).status();
        let ok = Command::new("nmcli")
            .args(["--wait", "45", "connection", "up", "uuid", uuid, "ifname", iface])
            .output()
            .is_ok_and(|o| o.status.success());
        if ok && has_address(iface) {
            return Ok(());
        }
        // Remove only the profile of this attempt. An old file comes back.
        let _ = Command::new("nmcli").args(["connection", "delete", "uuid", uuid]).output();
        if let Some(old) = old {
            let _ = write_private(&profile, &old);
            let _ = Command::new("nmcli").args(["connection", "load", &profile]).status();
        }
        return Err(WRONG.into());
    }
    let old = fs::read(NETPLAN).ok();
    write_private(NETPLAN, netplan_yaml(iface, net, password).as_bytes()).map_err(|e| format!("Cannot write {NETPLAN}: {e}"))?;
    let _ = Command::new("netplan").args(["apply"]).status();
    for _ in 0..20 {
        if has_address(iface) {
            return Ok(());
        }
        std::thread::sleep(std::time::Duration::from_secs(2));
    }
    match old {
        Some(old) => drop(write_private(NETPLAN, &old)),
        None => drop(fs::remove_file(NETPLAN)),
    }
    let _ = Command::new("netplan").args(["apply"]).status();
    Err(WRONG.into())
}

/// A wired interface has a link: an address can still come (DHCP).
pub fn wired_link() -> bool {
    if fake() {
        return false;
    }
    let Ok(dir) = fs::read_dir("/sys/class/net") else { return false };
    dir.flatten().any(|e| {
        let p = e.path();
        let name = e.file_name().to_string_lossy().into_owned();
        name != "lo"
            && !p.join("wireless").exists()
            && !p.join("phy80211").exists()
            // Physical interfaces only: not bridges, VPNs or containers.
            && p.join("device").exists()
            && fs::read_to_string(p.join("carrier")).is_ok_and(|c| c.trim() == "1")
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn terse() {
        assert_eq!(split_terse(r"a\:b:70:WPA2"), vec!["a:b", "70", "WPA2"]);
        assert_eq!(nm_auth("WPA3"), Auth::Sae);
        assert_eq!(nm_auth("WPA2 WPA3"), Auth::Psk);
        assert_eq!(nm_auth("--"), Auth::Open);
    }

    #[test]
    fn iw() {
        let text = "BSS 00:11 (on wlan0)\n\tcapability: ESS Privacy\n\tsignal: -50.00 dBm\n\tSSID: My\\x20Net\n\tRSN:\t * Version: 1\n\t\t * Authentication suites: PSK SAE\n\
                    BSS 00:22 (on wlan0)\n\tsignal: -80.00 dBm\n\tSSID: Open\n\
                    BSS 00:33 (on wlan0)\n\tcapability: ESS Privacy\n\tSSID: New\n\tRSN:\t * Version: 1\n\t\t * Authentication suites: SAE\n";
        let n = parse_iw(text);
        assert_eq!(n.len(), 3);
        assert_eq!((n[0].ssid.as_str(), n[0].signal, n[0].auth), ("My Net", 100, Auth::Psk));
        assert_eq!((n[1].ssid.as_str(), n[1].signal, n[1].auth), ("Open", 40, Auth::Open));
        assert_eq!(n[2].auth, Auth::Sae);
    }

    #[test]
    fn yaml() {
        let net = |a| Net { ssid: "Café \"x\"".into(), signal: 0, auth: a };
        assert!(netplan_yaml("wlan0", &net(Auth::Psk), "p:w").contains("\"Café \\\"x\\\"\": \n          password: \"p:w\""));
        assert!(netplan_yaml("wlan0", &net(Auth::Open), "").contains("\"Café \\\"x\\\"\": {}"));
        assert!(netplan_yaml("wlan0", &net(Auth::Sae), "p").contains("key-management: sae"));
    }

    #[test]
    fn keyfile() {
        let net = Net { ssid: "ab".into(), signal: 0, auth: Auth::Sae };
        let k = nm_keyfile("wlan0", &net, " p\\w", "u-1");
        assert!(k.contains("ssid=97;98;\n"));
        assert!(k.contains("key-mgmt=sae\npsk=\\sp\\\\w\n"));
        assert!(!nm_keyfile("wlan0", &Net { auth: Auth::Open, ..net }, "", "u").contains("wifi-security"));
    }
}
