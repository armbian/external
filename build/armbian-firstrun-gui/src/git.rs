//! Git account lookup: public SSH keys, display name and a public dotfiles repository.
//! The repository has a fixed name, armbian-dotfiles: a "dotfiles" repository is often
//! made for other systems.
//! Public data only: no sign-in, no token. A sign-in step (OAuth device flow) would
//! go before lookup() and add a token to the requests; private repositories need it.

use std::process::Command;

/// Name of the dotfiles repository of the account.
pub const REPO: &str = "armbian-dotfiles";

/// The API of a server.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Kind {
    GitHub,
    GitLab,
    /// Gitea and Forgejo, for example Codeberg.
    Gitea,
    /// Other server: GitLab or Gitea, the lookup finds out.
    Unknown,
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct Account {
    pub kind: Kind,
    pub host: String,
    pub user: String,
}

/// The name field, after parse().
#[derive(Debug, PartialEq, Eq)]
pub enum Input {
    /// A name, not an account: no "@" at the start.
    Name,
    /// Only "@" so far.
    Partial,
    Invalid(&'static str),
    Ok(Account),
}

/// What the lookup found for an account that exists.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Found {
    /// The display name from the profile. None: the profile has no name.
    pub name: Option<String>,
    pub keys: usize,
    pub dotfiles: bool,
    /// The profile picture as a PNG or JPEG file. None: no picture, or it did not load.
    pub avatar: Option<Vec<u8>>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Lookup {
    Found(Found),
    NotFound,
    Unreachable,
}

/// Name of the service for the labels: "GitHub", or the server name.
pub fn source_name(host: &str) -> String {
    match host {
        "github.com" => "GitHub".into(),
        "gitlab.com" => "GitLab".into(),
        "codeberg.org" => "Codeberg".into(),
        _ => host.into(),
    }
}

fn kind_of(host: &str) -> Kind {
    match host {
        "github.com" => Kind::GitHub,
        "gitlab.com" => Kind::GitLab,
        "codeberg.org" => Kind::Gitea,
        _ => Kind::Unknown,
    }
}

/// Remove spaces, a pasted "https://" and the "/" at the end.
fn clean(s: &str) -> &str {
    let s = s.trim();
    let s = s.strip_prefix("https://").or_else(|| s.strip_prefix("http://")).unwrap_or(s);
    s.trim_end_matches('/')
}

pub fn valid_user(u: &str) -> bool {
    (1..=100).contains(&u.len())
        && !u.starts_with(['-', '.'])
        && u.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-'))
}

/// A host name with an optional port. No path.
pub fn valid_host(h: &str) -> bool {
    let (name, port) = match h.rsplit_once(':') {
        Some((n, p)) => (n, Some(p)),
        None => (h, None),
    };
    let port_ok = port.is_none_or(|p| p.parse::<u16>().is_ok_and(|p| p > 0));
    let label_ok = |l: &str| !l.is_empty() && l.len() <= 63 && !l.starts_with('-') && !l.ends_with('-') && l.chars().all(|c| c.is_ascii_alphanumeric() || c == '-');
    port_ok && name.len() <= 253 && name.split('.').all(label_ok)
}

/// The account in the name field: "@user" on GitHub, or "@user@host" on another
/// server (GitLab, Gitea or Forgejo).
pub fn parse(text: &str) -> Input {
    let Some(rest) = text.trim().strip_prefix('@') else { return Input::Name };
    let (user, host) = match rest.split_once('@') {
        Some((u, h)) => (u, clean(h).to_lowercase()),
        None => (rest, "github.com".to_string()),
    };
    if user.is_empty() {
        return Input::Partial;
    }
    if !valid_user(user) {
        return Input::Invalid("Not a valid username");
    }
    if host.is_empty() {
        return Input::Partial;
    }
    if !valid_host(&host) {
        return Input::Invalid("Not a valid server");
    }
    Input::Ok(Account { kind: kind_of(&host), host, user: user.to_string() })
}

impl Account {
    pub fn keys_url(&self) -> String {
        format!("https://{}/{}.keys", self.host, self.user)
    }
    pub fn dotfiles_url(&self) -> String {
        format!("https://{}/{}/{REPO}.git", self.host, self.user)
    }
    /// The URL that a git clone asks first. HTTP 200: a public repository.
    fn refs_url(&self) -> String {
        format!("{}/info/refs?service=git-upload-pack", self.dotfiles_url())
    }
    /// Profile URLs, in the order to try them.
    pub fn profile_urls(&self) -> Vec<(Kind, String)> {
        let (h, u) = (&self.host, &self.user);
        let gitlab = (Kind::GitLab, format!("https://{h}/api/v4/users?username={u}"));
        let gitea = (Kind::Gitea, format!("https://{h}/api/v1/users/{u}"));
        match self.kind {
            Kind::GitHub => vec![(Kind::GitHub, format!("https://api.github.com/users/{u}"))],
            Kind::GitLab => vec![gitlab],
            Kind::Gitea => vec![gitea],
            Kind::Unknown => vec![gitlab, gitea],
        }
    }
}

/// Lines of a .keys file that are public keys.
pub fn count_keys(text: &str) -> usize {
    text.lines().map(str::trim).filter(|l| ["ssh-", "ecdsa-", "sk-"].iter().any(|p| l.starts_with(p))).count()
}

#[derive(Debug, PartialEq, Eq)]
pub enum Profile {
    /// The account exists: the display name and the picture URL, when the profile has them.
    Exists(Option<String>, Option<String>),
    Missing,
    /// No answer, or an answer that tells nothing (rate limit, sign-in needed, not this API).
    Unknown,
}

/// The profile from an API answer (HTTP code and body).
pub fn parse_profile(kind: Kind, code: u16, body: &str) -> Profile {
    if code == 404 {
        return Profile::Missing;
    }
    if code != 200 {
        return Profile::Unknown;
    }
    let Ok(json) = serde_json::from_str::<serde_json::Value>(body) else { return Profile::Unknown };
    let text = |v: Option<&serde_json::Value>| v.and_then(|v| v.as_str()).map(str::trim).filter(|s| !s.is_empty()).map(String::from);
    match kind {
        // GitLab: a list, empty when the user does not exist.
        Kind::GitLab => match json.as_array() {
            Some(a) if a.is_empty() => Profile::Missing,
            Some(a) => Profile::Exists(text(a[0].get("name")), text(a[0].get("avatar_url"))),
            None => Profile::Unknown,
        },
        Kind::GitHub if json.get("login").is_some() => Profile::Exists(text(json.get("name")), text(json.get("avatar_url"))),
        Kind::Gitea if json.get("login").is_some() => Profile::Exists(text(json.get("full_name")), text(json.get("avatar_url"))),
        _ => Profile::Unknown,
    }
}

/// Servers that a profile may name for its picture, beside the git server itself.
const AVATAR_HOSTS: [&str; 4] = ["avatars.githubusercontent.com", "secure.gravatar.com", "www.gravatar.com", "gravatar.com"];

/// The URL of a small picture: HTTPS only, on the git server or a known picture server.
/// The profile comes from the server: it must not send the device to other addresses.
/// A relative URL (GitLab uploads) is on the host. GitHub sends the size it is asked for.
pub fn avatar_url(acc: &Account, url: &str) -> Option<String> {
    let url = if url.starts_with('/') { format!("https://{}{url}", acc.host) } else { url.to_string() };
    let authority = url.strip_prefix("https://")?.split(['/', '?', '#']).next()?;
    if authority != acc.host && !AVATAR_HOSTS.contains(&authority) {
        return None;
    }
    let sep = if url.contains('?') { '&' } else { '?' };
    Some(if acc.kind == Kind::GitHub { format!("{url}{sep}s=96") } else { url })
}

/// The bytes of a file, at most 1 MB. None: no answer, or not HTTP 200.
/// No redirects: the picture server answers itself.
fn get_bytes(url: &str) -> Option<Vec<u8>> {
    let out = Command::new("curl")
        .args(["-sSf", "--proto", "=https", "--max-time", "5", "--max-filesize", "1000000", "-A", "armbian-firstrun-gui", url])
        .output()
        .ok()?;
    (out.status.success() && !out.stdout.is_empty()).then_some(out.stdout)
}

/// HTTP code and body, at most 1 MB. Code 0: no answer, or a transfer that did not
/// complete (time-out, too large): a part of a body tells nothing.
fn get(url: &str) -> (u16, String) {
    let out = Command::new("curl")
        .args(["-sS", "--max-time", "5", "--max-filesize", "1000000", "-A", "armbian-firstrun-gui", "-H", "Accept: application/json", "-w", "\n%{http_code}", url])
        .output();
    let Ok(out) = out.map_err(|_| ()).and_then(|o| if o.status.success() { Ok(o) } else { Err(()) }) else {
        return (0, String::new());
    };
    let text = String::from_utf8_lossy(&out.stdout);
    let (body, code) = text.rsplit_once('\n').unwrap_or(("", &text));
    (code.trim().parse().unwrap_or(0), body.to_string())
}

/// The profile from the answers of the APIs, in the order of profile_urls(). Code 0: no
/// answer, and the next API is not asked (same server). Also: whether the server answered.
/// Other server: missing only when every API says so. A 404 of one API alone can mean
/// "not this API", and an error of the other tells nothing.
pub fn profile_from(server: Kind, answers: impl IntoIterator<Item = (Kind, u16, String)>) -> (Profile, bool) {
    let (mut reached, mut all_missing) = (false, true);
    for (kind, code, body) in answers {
        if code == 0 {
            all_missing = false;
            break;
        }
        reached = true;
        match parse_profile(kind, code, &body) {
            Profile::Exists(name, avatar) => return (Profile::Exists(name, avatar), true),
            // A known service: its answer is final. Other server: try the next API.
            Profile::Missing if server != Kind::Unknown => return (Profile::Missing, true),
            Profile::Missing => {}
            Profile::Unknown => all_missing = false,
        }
    }
    (if reached && all_missing { Profile::Missing } else { Profile::Unknown }, reached)
}

fn profile(acc: &Account) -> (Profile, bool) {
    // Lazy: an API is asked only when the one before it answered.
    let answers = acc.profile_urls().into_iter().map(|(kind, url)| {
        let (code, body) = get(&url);
        (kind, code, body)
    });
    profile_from(acc.kind, answers)
}

/// A git server answers the first request of a clone with this line. A sign-in page
/// with HTTP 200 does not start with it.
pub fn is_ref_advertisement(code: u16, body: &str) -> bool {
    code == 200 && body.starts_with("001e# service=git-upload-pack")
}

/// Look up the account. Blocks for up to about 10 s: run it in a thread.
pub fn lookup(acc: &Account) -> Lookup {
    let (prof, keys, refs) = std::thread::scope(|s| {
        let keys = s.spawn(|| get(&acc.keys_url()));
        let refs = s.spawn(|| get(&acc.refs_url()));
        let prof = profile(acc);
        (prof, keys.join().unwrap_or_default(), refs.join().unwrap_or_default())
    });
    let ((prof, reached), (keys_code, keys_text), (refs_code, refs_text)) = (prof, keys, refs);
    let keys = if keys_code == 200 { count_keys(&keys_text) } else { 0 };
    let dotfiles = is_ref_advertisement(refs_code, &refs_text);
    match decide(&prof, reached, keys_code, dotfiles) {
        Lookup::Found(_) => {}
        other => return other,
    }
    let (name, avatar) = match prof {
        Profile::Exists(name, avatar) => (name, avatar),
        _ => (None, None),
    };
    let avatar = avatar.and_then(|u| avatar_url(acc, &u)).and_then(|u| get_bytes(&u));
    Lookup::Found(Found { name, keys, dotfiles, avatar })
}

/// The result from the answers. Found carries no details here: lookup() adds them.
pub fn decide(prof: &Profile, reached: bool, keys_code: u16, dotfiles: bool) -> Lookup {
    if !reached && keys_code == 0 && !dotfiles {
        return Lookup::Unreachable;
    }
    match prof {
        Profile::Exists(..) => Lookup::Found(Found::default()),
        // The profile tells nothing (for example the GitHub rate limit): the keys
        // file or the repository shows that the account exists.
        _ if keys_code == 200 || dotfiles => Lookup::Found(Found::default()),
        // The profile says absent: a known service, or every API of another server.
        // The keys file does not decide it: gitlab.com redirects it to the sign-in (302).
        Profile::Missing => Lookup::NotFound,
        // No clear answer: not kept, so that the next try asks again.
        _ => Lookup::Unreachable,
    }
}

/// The first line of the result card.
pub fn title(acc: &Account, r: &Lookup) -> String {
    let service = source_name(&acc.host);
    match r {
        Lookup::Found(_) => format!("{service} profile found"),
        Lookup::NotFound => format!("No account {} on {service}", acc.user),
        Lookup::Unreachable => format!("Could not reach {}", acc.host),
    }
}

/// The second line of the result card: what the account brings, or what to do.
pub fn detail(acc: &Account, r: &Lookup) -> String {
    match r {
        Lookup::Found(f) => {
            let name = f.name.clone().unwrap_or_else(|| acc.user.clone());
            let keys = match f.keys {
                0 => "no SSH keys".to_string(),
                1 => "1 SSH key".to_string(),
                n => format!("{n} SSH keys"),
            };
            let repo = if f.dotfiles { REPO.to_string() } else { format!("no {REPO}") };
            format!("{name} · {keys} · {repo}")
        }
        Lookup::NotFound => "Check the username, or remove the @ for a local account.".to_string(),
        Lookup::Unreachable => "Check the network, or remove the @ for a local account.".to_string(),
    }
}

/// A Linux username from a git login: lower case, only a-z, 0-9, - and _, at most
/// 32 characters. Empty when it does not start with a letter.
pub fn linux_username(login: &str) -> String {
    let name: String = login.to_lowercase().chars().filter(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || matches!(c, '-' | '_')).take(32).collect();
    if name.starts_with(|c: char| c.is_ascii_lowercase()) {
        name
    } else {
        String::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn acc(kind: Kind, host: &str, user: &str) -> Input {
        Input::Ok(Account { kind, host: host.into(), user: user.into() })
    }

    #[test]
    fn input() {
        assert_eq!(parse("Igor Pečovnik"), Input::Name);
        assert_eq!(parse(""), Input::Name);
        assert_eq!(parse(" @ "), Input::Partial);
        assert_eq!(parse("@anna@"), Input::Partial);
        assert_eq!(parse(" @igorpecovnik "), acc(Kind::GitHub, "github.com", "igorpecovnik"));
        assert_eq!(parse("@anna@codeberg.org"), acc(Kind::Gitea, "codeberg.org", "anna"));
        assert_eq!(parse("@some.one@GitLab.com"), acc(Kind::GitLab, "gitlab.com", "some.one"));
        assert_eq!(parse("@bob@https://git.example.org/"), acc(Kind::Unknown, "git.example.org", "bob"));
        assert_eq!(parse("@bob@git.example.org:3000"), acc(Kind::Unknown, "git.example.org:3000", "bob"));
        assert_eq!(parse("@bob@git.example.org/path"), Input::Invalid("Not a valid server"));
        assert_eq!(parse("@-bob"), Input::Invalid("Not a valid username"));
        assert_eq!(parse("@bo b"), Input::Invalid("Not a valid username"));
    }

    #[test]
    fn hosts() {
        assert!(valid_host("git.example.org"));
        assert!(valid_host("localhost:8080"));
        assert!(!valid_host("git.example.org:0"));
        assert!(!valid_host("git.example.org:99999"));
        assert!(!valid_host("-bad.org"));
        assert!(!valid_host("a..b"));
        assert!(!valid_host("a/b"));
        assert!(valid_user(&"a".repeat(100)));
        assert!(!valid_user(&"a".repeat(101)));
    }

    #[test]
    fn avatars() {
        let gh = Account { kind: Kind::GitHub, host: "github.com".into(), user: "u".into() };
        assert_eq!(avatar_url(&gh, "https://avatars.githubusercontent.com/u/1?v=4").as_deref(), Some("https://avatars.githubusercontent.com/u/1?v=4&s=96"));
        assert_eq!(avatar_url(&gh, "http://example.org/a.png"), None);
        let gl = Account { kind: Kind::GitLab, host: "gitlab.com".into(), user: "u".into() };
        assert_eq!(avatar_url(&gl, "/uploads/a.png").as_deref(), Some("https://gitlab.com/uploads/a.png"));
        assert_eq!(parse_profile(Kind::GitHub, 200, r#"{"login":"u","name":"A","avatar_url":"https://x/a"}"#), Profile::Exists(Some("A".into()), Some("https://x/a".into())));
    }

    #[test]
    fn avatar_hosts() {
        let gt = Account { kind: Kind::Unknown, host: "git.example.org".into(), user: "u".into() };
        assert_eq!(avatar_url(&gt, "https://git.example.org/avatars/1").as_deref(), Some("https://git.example.org/avatars/1"));
        assert_eq!(avatar_url(&gt, "https://secure.gravatar.com/avatar/x").as_deref(), Some("https://secure.gravatar.com/avatar/x"));
        assert_eq!(avatar_url(&gt, "https://169.254.169.254/latest"), None);
        assert_eq!(avatar_url(&gt, "https://git.example.org.evil/a"), None);
        assert_eq!(avatar_url(&gt, "https://user@git.example.org/a"), None);
    }

    #[test]
    fn unclear_is_not_absent() {
        let (u, gl, gt) = (Kind::Unknown, Kind::GitLab, Kind::Gitea);
        // Other server: the GitLab API is not there (404), the Gitea API fails (503).
        let (p, reached) = profile_from(u, [(gl, 404, String::new()), (gt, 503, String::new())]);
        assert_eq!(p, Profile::Unknown);
        assert_eq!(decide(&p, reached, 404, false), Lookup::Unreachable);
        // Both APIs say missing, and the keys file too: absent.
        let (p, reached) = profile_from(u, [(gl, 200, "[]".into()), (gt, 404, String::new())]);
        assert_eq!(p, Profile::Missing);
        assert_eq!(decide(&p, reached, 404, false), Lookup::NotFound);
        // The profile is missing, but the keys file answers: the account exists.
        assert!(matches!(decide(&Profile::Missing, true, 200, false), Lookup::Found(_)));
        // GitHub says 404: final for a known service.
        let (p, _) = profile_from(Kind::GitHub, [(Kind::GitHub, 404, String::new())]);
        assert_eq!(p, Profile::Missing);
        // No answer at all.
        assert_eq!(decide(&Profile::Unknown, false, 0, false), Lookup::Unreachable);
        // gitlab.com: the profile list is empty, the keys file redirects to the sign-in.
        let (p, reached) = profile_from(gl, [(gl, 200, "[]".into())]);
        assert_eq!(decide(&p, reached, 302, false), Lookup::NotFound);
    }

    #[test]
    fn refs() {
        assert!(is_ref_advertisement(200, "001e# service=git-upload-pack\n0000"));
        assert!(!is_ref_advertisement(200, "<html>Sign in</html>"));
        assert!(!is_ref_advertisement(401, "001e# service=git-upload-pack"));
    }

    #[test]
    fn sources() {
        assert_eq!(source_name("codeberg.org"), "Codeberg");
        assert_eq!(source_name("git.example.org"), "git.example.org");
    }

    #[test]
    fn urls() {
        let a = Account { kind: Kind::GitHub, host: "github.com".into(), user: "u".into() };
        assert_eq!(a.keys_url(), "https://github.com/u.keys");
        assert_eq!(a.dotfiles_url(), "https://github.com/u/armbian-dotfiles.git");
        assert_eq!(a.refs_url(), "https://github.com/u/armbian-dotfiles.git/info/refs?service=git-upload-pack");
        assert_eq!(a.profile_urls(), vec![(Kind::GitHub, "https://api.github.com/users/u".to_string())]);
        let a = Account { kind: Kind::GitLab, host: "gitlab.com".into(), user: "u".into() };
        assert_eq!(a.profile_urls(), vec![(Kind::GitLab, "https://gitlab.com/api/v4/users?username=u".to_string())]);
        let a = Account { kind: Kind::Gitea, host: "codeberg.org".into(), user: "u".into() };
        assert_eq!(a.profile_urls(), vec![(Kind::Gitea, "https://codeberg.org/api/v1/users/u".to_string())]);
        let a = Account { kind: Kind::Unknown, host: "git.example.org:3000".into(), user: "u".into() };
        let kinds: Vec<Kind> = a.profile_urls().into_iter().map(|(k, _)| k).collect();
        assert_eq!(kinds, vec![Kind::GitLab, Kind::Gitea]);
        assert_eq!(a.keys_url(), "https://git.example.org:3000/u.keys");
    }

    #[test]
    fn keys() {
        let text = "ssh-ed25519 AAAA\necdsa-sha2-nistp256 AAAA\nsk-ssh-ed25519@openssh.com AAAA\n\n<html>\nNot Found\n";
        assert_eq!(count_keys(text), 3);
        assert_eq!(count_keys(""), 0);
    }

    #[test]
    fn profiles() {
        assert_eq!(parse_profile(Kind::GitHub, 200, r#"{"login":"u","name":"Igor Pečovnik"}"#), Profile::Exists(Some("Igor Pečovnik".into()), None));
        assert_eq!(parse_profile(Kind::GitHub, 200, r#"{"login":"u","name":null}"#), Profile::Exists(None, None));
        assert_eq!(parse_profile(Kind::GitHub, 404, "{}"), Profile::Missing);
        assert_eq!(parse_profile(Kind::GitHub, 403, r#"{"message":"rate limit"}"#), Profile::Unknown);
        assert_eq!(parse_profile(Kind::GitLab, 200, r#"[{"username":"u","name":"Ana"}]"#), Profile::Exists(Some("Ana".into()), None));
        assert_eq!(parse_profile(Kind::GitLab, 200, "[]"), Profile::Missing);
        assert_eq!(parse_profile(Kind::GitLab, 200, "<html>"), Profile::Unknown);
        assert_eq!(parse_profile(Kind::Gitea, 200, r#"{"login":"u","full_name":""}"#), Profile::Exists(None, None));
        assert_eq!(parse_profile(Kind::Gitea, 200, r#"{"login":"u","full_name":"Bob B"}"#), Profile::Exists(Some("Bob B".into()), None));
    }

    #[test]
    fn statuses() {
        let a = Account { kind: Kind::GitHub, host: "github.com".into(), user: "u".into() };
        let f = Lookup::Found(Found { name: Some("Ana".into()), keys: 3, dotfiles: true, avatar: None });
        assert_eq!(title(&a, &f), "GitHub profile found");
        assert_eq!(detail(&a, &f), "Ana · 3 SSH keys · armbian-dotfiles");
        let f = Lookup::Found(Found { name: None, keys: 0, dotfiles: false, avatar: None });
        assert_eq!(detail(&a, &f), "u · no SSH keys · no armbian-dotfiles");
        assert_eq!(title(&a, &Lookup::NotFound), "No account u on GitHub");
        assert_eq!(title(&a, &Lookup::Unreachable), "Could not reach github.com");
    }

    #[test]
    fn linux_name() {
        assert_eq!(linux_username("IgorPecovnik"), "igorpecovnik");
        assert_eq!(linux_username("some.one"), "someone");
        assert_eq!(linux_username("a_b-c"), "a_b-c");
        assert_eq!(linux_username("42bob"), "");
        assert_eq!(linux_username(&"x".repeat(40)).len(), 32);
    }
}
