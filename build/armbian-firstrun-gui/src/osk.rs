//! Letter rows of the on-screen keyboard, from the XKB keymap of the active layout.

use xkbcommon::xkb;

/// Normal and shifted text of one key.
pub type Key = (String, String);

/// xkb keycodes (evdev + 8) of the three letter rows: AD01..AD12, AC01..AC11, AB01..AB10.
const ROWS: [std::ops::RangeInclusive<u32>; 3] = [24..=35, 38..=48, 52..=61];

const QWERTY: [&str; 3] = ["qwertyuiop", "asdfghjkl", "zxcvbnm"];

/// Text of a key at a shift level, or None for keys without text (dead keys, modifiers).
fn text(keymap: &xkb::Keymap, code: u32, level: u32) -> Option<String> {
    let sym = *keymap.key_get_syms_by_level(xkb::Keycode::new(code), 0, level).first()?;
    let s: String = xkb::keysym_to_utf8(sym).chars().filter(|c| *c != '\0').collect();
    (s.chars().count() == 1).then_some(s)
}

/// Letter rows for "layout" or "layout:variant". Keeps only keys that type a letter:
/// punctuation is on the 123 page. None when the keymap does not compile.
fn letters(kb: &str) -> Option<Vec<Vec<Key>>> {
    let (layout, variant) = kb.split_once(':').unwrap_or((kb, ""));
    let ctx = xkb::Context::new(xkb::CONTEXT_NO_FLAGS);
    let keymap = xkb::Keymap::new_from_names(&ctx, "evdev", "", layout, variant, None, xkb::KEYMAP_COMPILE_NO_FLAGS)?;
    let rows: Vec<Vec<Key>> = ROWS
        .iter()
        .map(|codes| {
            codes
                .clone()
                .filter_map(|code| {
                    let normal = text(&keymap, code, 0).filter(|s| s.chars().all(char::is_alphabetic))?;
                    let shifted = text(&keymap, code, 1).unwrap_or_else(|| normal.to_uppercase());
                    Some((normal, shifted))
                })
                .collect()
        })
        .collect();
    rows.iter().all(|r| !r.is_empty()).then_some(rows)
}

fn qwerty() -> Vec<Vec<Key>> {
    QWERTY.iter().map(|r| r.chars().map(|c| (c.to_string(), c.to_uppercase().to_string())).collect()).collect()
}

/// Keyboard pages for the active layout.
pub struct Layout {
    pub letters: Vec<Vec<Key>>,
    pub label: String,
    /// US letters when the layout has no Latin letters: user names need them.
    pub latin: Option<Vec<Vec<Key>>>,
}

pub fn layout(kb: &str) -> Layout {
    let name = kb.split_once(':').map_or(kb, |(l, _)| l).to_uppercase();
    match letters(kb) {
        Some(rows) if rows.iter().flatten().any(|(n, _)| n.chars().all(|c| c.is_ascii_alphabetic())) => {
            Layout { letters: rows, label: name, latin: None }
        }
        Some(rows) => Layout { letters: rows, label: name, latin: Some(letters("us").unwrap_or_else(qwerty)) },
        None => Layout { letters: letters("us").unwrap_or_else(qwerty), label: "US".into(), latin: None },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn row(l: &Layout, r: usize) -> String {
        l.letters[r].iter().map(|(n, _)| n.as_str()).collect()
    }

    #[test]
    fn layouts() {
        let us = layout("us");
        assert_eq!((row(&us, 0), row(&us, 1), row(&us, 2)), ("qwertyuiop".into(), "asdfghjkl".into(), "zxcvbnm".into()));
        assert!(us.latin.is_none());
        let de = layout("de");
        assert_eq!((row(&de, 0), row(&de, 1), row(&de, 2)), ("qwertzuiopü".into(), "asdfghjklöä".into(), "yxcvbnm".into()));
        assert_eq!(de.letters[0][10].1, "Ü");
        let fr = layout("fr");
        assert_eq!((row(&fr, 0), row(&fr, 1), row(&fr, 2)), ("azertyuiop".into(), "qsdfghjklmù".into(), "wxcvbn".into()));
        let ru = layout("ru");
        assert_eq!(row(&ru, 0), "йцукенгшщзхъ");
        assert_eq!(ru.label, "RU");
        assert_eq!(ru.latin.as_ref().map(|l| l[0].len()), Some(10));
        let dvorak = layout("us:dvorak");
        assert_eq!(row(&dvorak, 0), "pyfgcrl");
        assert_eq!(layout("no-such-layout").label, "US");
    }
}
