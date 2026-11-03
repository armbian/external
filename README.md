# Armbian external packages

Third-party Debian packages for the Armbian apt repository.

## Goal

One repository for each external package: its configuration, signing keys, fetch, build, patch and retention.
The repository update takes finished, verified package sets from here.

## Output

The output tree keeps the layout of `incoming/external`:

```
debs-beta/extra/<release>-<target>/<file>.deb   every package
debs/extra/<release>-<target>/<file>.deb        only when newer than the published stable version
manifest.json                                   one entry per file: source, version, SHA256, checks
```

Target `main` writes to `debs[-beta]/` directly. File names are the upstream names.

## Usage

```sh
python3 -m extpkg validate                          # check packages/*.yaml
python3 -m extpkg plan --out plan.json              # resolve versions, no download
python3 -m extpkg run --dry-run --only code,gh      # download, verify, sort; no upload
python3 -m extpkg run --dest user@host:/path --known-hosts kh   # with upload
```

Set `ARMBIAN_BUILD_DIR` to an armbian/build checkout to take the supported releases from it.
Set `GITHUB_TOKEN` to avoid the GitHub API rate limit.

## Package config

`packages/<name>.yaml`:

| Key | Meaning |
|---|---|
| `method` | `apt` (signed apt repository), `github` (release assets), `url` (direct download) |
| `source` | `url`; for apt also `suite` and `components`; for github optional `tag`; for url optional `sha256` |
| `filter` | apt only. aptly query subset: `Name (% glob)`, `\|`, `,`, `$Version (< x)`, bare name |
| `releases` | `all` (supported releases) or a list |
| `architectures`, `target` | `target` is `main`, `utils` or `desktop` |
| `repack` | `packages`, `epoch`, `suffix`: rebuild those packages with a new version |
| `assets`, `exclude` | github only: asset name patterns |
| `verify` | `signature`, `checksums`: both default to true |

## Checks

- apt: `InRelease` (or `Release` + `Release.gpg`) must verify with a key in `keys/`. The index and every `.deb` must match their SHA256.
- github: the asset must match the SHA256 digest that GitHub publishes.
- url: no upstream hash. Pin one with `source.sha256`.
- Every file: `dpkg-deb` must read it. The version must match the index.

Versions are compared as Debian versions, with epochs.

## Package types (planned)

| Type | Action |
|---|---|
| `download` | Fetch a prebuilt package. This is what `method` does now. |
| `repack` | Change a binary package (version, control fields, files). Version change works now. |
| `source-patch` | Get the Debian source, apply our patches, rebuild. |
| `build` | Build from an upstream tag or tarball in a clean chroot. |

Our builds add `+armbianN` to the version.
