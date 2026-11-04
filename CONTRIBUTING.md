# Add an external package

One package source is one file: `packages/<name>.yaml`.
Open a pull request. The Check workflow validates it and does a dry-run download.

## 1. Choose the source

Use the first one that exists:

1. **apt repository** with a signed `InRelease` or `Release.gpg` (`method: apt`). Best: signature and hashes are checked.
2. **GitHub release** with `.deb` assets (`method: github`). The SHA256 digest is checked.
3. **Direct URL** (`method: url`). Nothing is checked. Pin `source.sha256` when the file is fixed.

## 2. Add the signing key (apt only)

Skip this step when `keys/` already has the key.

Find the key that signs the repository:

```sh
curl -fsSL <url>/dists/<suite>/InRelease -o InRelease
gpgv InRelease 2>&1 | grep "using"          # prints the signing key fingerprint
```

Get the key from a source that you trust, not from the repository alone:

- Launchpad PPA: `https://api.launchpad.net/1.0/~<owner>/+archive/ubuntu/<ppa>` gives `signing_key_fingerprint`.
  Fetch the key with `curl "https://keyserver.ubuntu.com/pks/lookup?op=get&options=mr&search=0x<fingerprint>"`.
- Vendor: the key URL in the vendor's install instructions.

Check that the key holds the signing fingerprint. Then store it in binary form:

```sh
gpg --show-keys --with-colons key.asc | grep ^fpr
gpg --dearmor < key.asc > keys/<name>.gpg
```

Say in the pull request where the key comes from.

## 3. Write the config

apt:

```yaml
name: zfs-noble
method: apt
source:
  url: https://ppa.launchpadcontent.net/arter97/zfs/ubuntu
  suite: noble
  components: [main]
filter: Name (% zfsutils-linux) | Name (% zfs-dkms)
releases: [noble]
architectures: [arm64, amd64]
target: utils
install: [zfsutils-linux, zfs-dkms]
```

github:

```yaml
name: gh
method: github
source:
  url: https://github.com/cli/cli
releases: all
architectures: [armhf, arm64, amd64]
target: utils
install: [gh]
```

url:

```yaml
name: discord
method: url
source:
  url: https://discord.com/api/download?platform=linux&format=deb
releases: [noble, trixie]
architectures: [amd64]
target: desktop
install: [discord]
```

Rules:

- `target: desktop` for desktop applications, `utils` for the rest. `main` is for packages that every image needs.
- `releases: all` only when the package works on every supported release.
- Use `exclude` or `assets` (github) and `filter` (apt) to take only the packages that you need.
- Do not turn off `verify.signature` or `verify.checksums`. If upstream is broken, say why in `notes`.
- Debug packages (`*-dbg`, `*-dbgsym`) are not mirrored. Set `include_debug: true` only when users need them.
- One version of each package stays on the server. Set `keep: 2` to keep the previous version too.

All keys: [docs/technical.md](docs/technical.md#package-config).

### Build from source

When no built package fits, use `method: build`. See [docs/technical.md](docs/technical.md#builds).

- Take the packaging from Debian or Ubuntu when it exists. Keep only the parts that differ in this repository.
- Put patches in `packages/<name>/patches/` with a `series` file. Patches are optional.
- Test with the Build workflow: run it by hand with `only: <name>` and `dry_run: true`.

## 4. Test

```sh
python3 -m extpkg validate
python3 -m extpkg plan --only <name> --out /tmp/plan.json
python3 -m extpkg run --dry-run --only <name> --out /tmp/out
```

Check the output:

- `plan`: no `SKIP` line, except "no package matched" for an architecture that upstream does not build.
- Dependencies: add `--depcheck` to `run`. Every check must say `ok`. The pull request check does the same.
- `run`: each line says `sig+sha` (apt) or `sha` (github). `unverified` is expected for `url` only.
- `/tmp/out/debs-beta/extra/<release>-<target>/` holds the expected files.

## 5. Pull request

- One package source in one pull request.
- Commit message: `Add <name>: <what it is>`.
- Pull request text: the source, the key origin (apt), and the result of the dry run.
