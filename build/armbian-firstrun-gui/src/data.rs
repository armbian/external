//! System lists (time zones, locales, keyboard layouts) and location detection.
//! The sources are the same files that armbian-firstlogin uses.

use std::collections::BTreeSet;
use std::fs;
use std::process::Command;

/// One entry of a list: the value to write, and the text to show.
#[derive(Clone, Debug)]
pub struct Item {
    pub value: String,
    pub label: String,
    /// ISO 3166 country codes that use this entry.
    pub countries: Vec<String>,
}

/// Time zones from zone1970.tab and zone.tab, with their countries. UTC is added.
/// zone.tab has the zone of each country (Europe/Ljubljana), zone1970.tab only the main ones.
pub fn timezones() -> Vec<Item> {
    let mut items: Vec<Item> = vec![Item { value: "UTC".into(), label: "UTC".into(), countries: vec![] }];
    for file in ["/usr/share/zoneinfo/zone1970.tab", "/usr/share/zoneinfo/zone.tab"] {
        let text = fs::read_to_string(file).unwrap_or_default();
        for line in text.lines().filter(|l| !l.starts_with('#')) {
            let f: Vec<&str> = line.split('\t').collect();
            if f.len() < 3 {
                continue;
            }
            let cc: Vec<String> = f[0].split(',').map(String::from).collect();
            match items.iter_mut().find(|i| i.value == f[2]) {
                Some(i) => i.countries.extend(cc),
                None => items.push(Item { value: f[2].into(), label: f[2].replace('_', " "), countries: cc }),
            }
        }
    }
    items.sort_by(|a, b| a.label.cmp(&b.label));
    items
}

/// Add a zone that the list does not have (an alias such as Etc/UTC), when tzdata knows it.
pub fn add_timezone(items: &mut Vec<Item>, tz: &str) {
    if !tz.is_empty() && !items.iter().any(|i| i.value == tz) && std::path::Path::new("/usr/share/zoneinfo").join(tz).is_file() {
        items.push(Item { value: tz.into(), label: tz.replace('_', " "), countries: vec![] });
        items.sort_by(|a, b| a.label.cmp(&b.label));
    }
}

/// UTF-8 locales from /usr/share/i18n/SUPPORTED.
pub fn locales() -> Vec<Item> {
    let text = fs::read_to_string("/usr/share/i18n/SUPPORTED").unwrap_or_default();
    let mut seen = BTreeSet::new();
    for line in text.lines() {
        let mut f = line.split_whitespace();
        if let (Some(name), Some("UTF-8")) = (f.next(), f.next()) {
            seen.insert(name.to_string());
        }
    }
    seen.into_iter()
        .map(|name| {
            // ll_CC.UTF-8 or ll_CC@mod: the territory is after "_".
            let cc = name.split(['_', '.', '@']).nth(1).unwrap_or("").to_string();
            Item { label: name.clone(), value: name, countries: vec![cc] }
        })
        .collect()
}

/// Keyboard layouts and variants from the xkb rules. Value: "layout" or "layout:variant".
pub fn keyboards() -> Vec<Item> {
    let text = fs::read_to_string("/usr/share/X11/xkb/rules/evdev.xml").unwrap_or_default();
    // evdev.xml has a DOCTYPE.
    let opt = roxmltree::ParsingOptions { allow_dtd: true, ..Default::default() };
    let Ok(doc) = roxmltree::Document::parse_with_options(&text, opt) else { return vec![] };
    let child_text = |n: roxmltree::Node, tag: &str| -> String {
        n.children()
            .find(|c| c.has_tag_name("configItem"))
            .and_then(|c| c.children().find(|d| d.has_tag_name(tag)))
            .and_then(|d| d.text())
            .unwrap_or("")
            .to_string()
    };
    let countries = |n: roxmltree::Node| -> Vec<String> {
        n.children()
            .find(|c| c.has_tag_name("configItem"))
            .and_then(|c| c.children().find(|d| d.has_tag_name("countryList")))
            .map(|l| l.children().filter_map(|c| c.text()).map(|t| t.trim().to_uppercase()).filter(|t| !t.is_empty()).collect())
            .unwrap_or_default()
    };
    let mut items = Vec::new();
    for layout in doc.descendants().filter(|n| n.has_tag_name("layout")) {
        let name = child_text(layout, "name");
        let desc = child_text(layout, "description");
        if name.is_empty() {
            continue;
        }
        let cc = countries(layout);
        items.push(Item { value: name.clone(), label: format!("{desc} ({name})"), countries: cc.clone() });
        for variant in layout.descendants().filter(|n| n.has_tag_name("variant")) {
            let v = child_text(variant, "name");
            let vdesc = child_text(variant, "description");
            let mut vcc = countries(variant);
            if vcc.is_empty() {
                vcc = cc.clone();
            }
            items.push(Item { value: format!("{name}:{v}"), label: format!("{vdesc} ({name}:{v})"), countries: vcc });
        }
    }
    items.sort_by(|a, b| a.label.to_lowercase().cmp(&b.label.to_lowercase()));
    items
}

/// The result of the location lookup.
#[derive(Clone, Debug, Default)]
pub struct Location {
    pub timezone: String,
    pub country_code: String,
}

fn curl(url: &str) -> Option<String> {
    let out = Command::new("curl").args(["--max-time", "5", "-s", url]).output().ok()?;
    out.status.success().then(|| String::from_utf8_lossy(&out.stdout).trim().to_string()).filter(|s| !s.is_empty())
}

/// Same services as armbian-firstlogin, over HTTPS: ipinfo.io for the address, ipwhois.app for the location.
/// Returns (online, location). Online without a location: the location service failed.
pub fn detect() -> (bool, Option<Location>) {
    let Some(ip) = curl("https://ipinfo.io/ip") else { return (false, None) };
    let loc = curl(&format!("https://ipwhois.app/json/{ip}"))
        .and_then(|t| serde_json::from_str::<serde_json::Value>(&t).ok())
        .map(|json| {
            let s = |k: &str| json.get(k).and_then(|v| v.as_str()).unwrap_or("").to_string();
            Location { timezone: s("timezone"), country_code: s("country_code") }
        })
        .filter(|l| !l.timezone.is_empty());
    (true, loc)
}

/// Best locale for a country: the language that has the country code as its name
/// (de_DE, sl_SI), else the first locale of the country, else English.
pub fn locale_for(list: &[Item], cc: &str) -> Option<String> {
    let of_country: Vec<&Item> = list.iter().filter(|i| i.countries.iter().any(|c| c == cc)).collect();
    let lang = cc.to_lowercase();
    of_country
        .iter()
        .find(|i| i.value.starts_with(&format!("{lang}_{cc}.")))
        .or_else(|| of_country.iter().find(|i| i.value.starts_with("en_")))
        .or_else(|| of_country.first())
        .map(|i| i.value.clone())
}

/// Best keyboard for a country: the layout with the country code as its name, else the
/// first layout (without a variant) of the country.
pub fn keyboard_for(list: &[Item], cc: &str) -> Option<String> {
    let lower = cc.to_lowercase();
    list.iter()
        .find(|i| i.value == lower)
        .or_else(|| list.iter().find(|i| !i.value.contains(':') && i.countries.iter().any(|c| c == cc)))
        .map(|i| i.value.clone())
}

/// Current system values: (time zone, locale, keyboard).
pub fn system_defaults() -> (String, String, String) {
    let tz = fs::read_link("/etc/localtime")
        .ok()
        .and_then(|p| p.to_str().and_then(|s| s.split("zoneinfo/").nth(1)).map(String::from))
        .unwrap_or_else(|| "UTC".into());
    let var = |file: &str, key: &str| -> Option<String> {
        fs::read_to_string(file).ok()?.lines().find_map(|l| {
            l.strip_prefix(&format!("{key}=")).map(|v| v.trim_matches('"').to_string())
        })
    };
    let locale = var("/etc/default/locale", "LANG").unwrap_or_else(|| "en_US.UTF-8".into());
    let layout = var("/etc/default/keyboard", "XKBLAYOUT").unwrap_or_else(|| "us".into());
    let variant = var("/etc/default/keyboard", "XKBVARIANT").unwrap_or_default();
    let kb = if variant.is_empty() { layout } else { format!("{layout}:{variant}") };
    (tz, locale, kb)
}
