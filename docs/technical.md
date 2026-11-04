# Technical description

## Flow

```
mirror/*.yaml  ──plan──► plan.json ──fetch──► output/ ──upload──► repository server
                  (no download)      (download, check, sort)   (rsync over SSH)
```

1. **plan** expands each config to (release, architecture) entries and resolves the upstream files. It downloads indexes and release metadata only, once per repository, suite and architecture.
2. **fetch** downloads each file once, checks it, repacks it when the config says so, and places it in the output tree.
3. **upload** copies the output tree to the server while the downloads go on. It never replaces a file that is already there.

One failed source never stops the run. It becomes a "skipped" entry in the manifest and in the summary.

## Output

```
debs-beta/<dir>/<file>.deb
debs/<dir>/<file>.deb
manifest.json
plan.json
```

- `<dir>` is `extra/<release>-<target>`. For target `main`, `<dir>` is empty.
- `<file>` is the upstream file name. A repacked file gets `<package>_<version>_<arch>.deb`. A `url` download gets `<package>_<version>_<arch>.deb` from its control fields (an epoch stays, as `<epoch>%3a`), unless the config sets `filename`. A fixed name never updates: the upload does not overwrite.
- The same file in several places is a hardlink. It uses disk space once.

The layout is the same as `storage/incoming/external` of the old download workflow.

### Beta and stable

- Beta gets every file.
- Stable gets a file only when its version is newer than the version of the same binary package in the published stable repository.
- `repositories: [beta]` or `[stable]` limits a config to one repository. A change takes effect on the next run: files that the config no longer allows are removed. Files for a newly allowed repository come with the next new version.
  The tool reads `dists/<release>/<component>/binary-<arch>/Packages.gz` from `https://fi.mirror.armbian.de/apt`.
  `<component>` is `main` for target `main`, else `<release>-<target>`.
- Versions are compared as Debian versions, with epochs (`extpkg/debver.py`, a port of dpkg).

## Checks

| Method | Check |
|---|---|
| `apt` | `InRelease` must verify with a key in `keys/` or a system archive keyring. Then the `Packages` index must match its SHA256 in `Release`. Then each `.deb` must match its SHA256 and size in the index. |
| `github` | Each asset must match the SHA256 digest that GitHub publishes for it. |
| `url` | No upstream hash. Set `source.sha256` to pin one. |
| all | `dpkg-deb` must read the file. For `apt`, the control version must match the index. |

Signature rules, as apt uses them:

- One valid signature from a trusted key is enough. A signature from an unknown key is ignored. This allows key rotation (seen on the Mozilla PPA).
- A bad signature fails.
- If `InRelease` does not verify, the tool tries `Release` with `Release.gpg` (seen on `repos.azul.com`).
- If the clearsign `Hash:` header names a different algorithm than the signature uses, the header is corrected and checked again. The header is not part of the signed data.

`verify.signature: false` and `verify.checksums: false` turn a check off for one config. Use them only when upstream is broken, and say why in `notes`.

## Package config

`mirror/<name>.yaml` for built packages to download (`apt`, `github`, `url`), `build/<name>.yaml` for packages to build from source (`method: build`). The file name is the config name. A config in the wrong directory fails validation.

| Key | Required | Meaning |
|---|---|---|
| `name` | yes | Same as the file name. |
| `method` | yes | `apt`, `github` or `url`: take built packages. `build`: build from source, see [Builds](#builds). |
| `source.url` | yes | Repository, GitHub project or file URL. An `http://` apt URL is tried as `https://` first. |
| `source.suite` | apt | Suite (`noble`, `stable`) or a flat repository (`./`). |
| `source.components` | no | apt components. Default: `main`. |
| `source.tag` | no | github: release tag. Default: latest release. |
| `source.sha256` | no | url: expected SHA256. |
| `filter` | apt | Which packages to take. See below. |
| `with_deps` | no | Also take the dependencies found in the same index. Default: true when `filter` has no `Name` or `Version`. Careful: a vendor archive may carry its own base packages (the Raspberry Pi archive has `libc6`). Prefer naming the packages in `filter`. |
| `releases` | yes | `all` or a list of releases. |
| `architectures` | yes | `amd64`, `arm64`, `armhf`, `riscv64`, `loong64`, `i386`. |
| `target` | no | `main`, `utils` or `desktop`. Default: `main`. |
| `install` | no | Main package names. For tests and documentation. |
| `assets` | no | github: asset name patterns. Default: patterns for the architecture. |
| `exclude` | no | github: asset name patterns to drop. |
| `filename` | no | url: fixed output file name. Avoid it: the server then keeps the first version. |
| `repack` | no | `packages`, `epoch`, `suffix`: rebuild these packages with a new version. |
| `verify` | no | `signature`, `checksums`. Both default to true. |
| `include_debug` | no | Also mirror debug packages (`*-dbg`, `*-dbgsym`). Default: false. |
| `skip` | no | `release/arch` pairs to leave out, for example `trixie/armhf`. Say why in `notes`. |
| `depcheck` | no | false: leave the config out of the dependency check (it needs a source that the check does not have). Say why in `notes`. |
| `repositories` | no | `stable`, `beta` or both. Default: both. Old configs: `REPOSITORY=S`, `B`, `BS`. |
| `keep` | no | Versions of each package to keep on the server, per release and architecture. Default: 1. |
| `enabled` | no | false skips the config. Default: true. |
| `notes` | no | Free text. Say why an exception exists. |

### Filter

A subset of the aptly query syntax:

```
Name (% firefox*)                        glob on the package name
Name (% chromium) | Name (% chromium-*)  or
Name (% zulu21*), $Version (< 22.0)      and, with a version condition
unudhcpd                                 exact package name
```

Version operators: `=`, `<<`, `<=`, `<`, `>>`, `>=`, `>`. As in aptly, `<` means `<=` and `>` means `>=`.
For each matched name, the newest matching version is taken.

### GitHub asset patterns

| Architecture | Patterns |
|---|---|
| amd64 | `*amd64*.deb`, `*x86_64*.deb`, `*x64*.deb` |
| arm64 | `*arm64*.deb`, `*aarch64*.deb` |
| armhf | `*armhf*.deb`, `*armv7*.deb`, `*armv7l*.deb`, `*armv6*.deb` |
| riscv64 | `*riscv64*.deb` |
| all | `*_all.deb` |

### Repack

```yaml
repack:
  packages: [firefox]
  epoch: 9
  suffix: armbian1
```

The new version is `<epoch>:<upstream version without epoch><suffix>`, for example `9:159.0+build1-0ubuntu0.24.04.1~mt1armbian1`.
Firefox needs epoch 9 to win over the Ubuntu snap transitional package.

### Releases

`releases: all` means the releases whose `config/distributions/<release>/support` in armbian/build is not `eos`.
Set `ARMBIAN_BUILD_DIR` to a checkout. Without it, the tool uses a fixed list in `extpkg/config.py`.

## Builds

`method: build` builds packages from source for the Armbian repository. It takes three parts. Only one of packaging and upstream is required.

### Compared to a Launchpad PPA

For developers who maintain a PPA:

| | Launchpad PPA | Build here |
|---|---|---|
| Result | A separate archive per person or team | The Armbian repository: `<release>-<target>`, stable, beta or both |
| Releases | Ubuntu | Debian and Ubuntu, from one config |
| In git | The full `debian/` for each series | A reference to a Debian or Ubuntu source package, and our patches |
| Upload | A signed source package. Launchpad builds it | Nothing by hand. GitHub runners build binary packages. The Armbian repository signs them when it publishes |
| Architectures | All that Launchpad builds | `amd64`, `arm64` |
| Trigger | Each upload | Daily. Only builds whose sources, patches or config changed |
| Version | Set by hand or by a script | Automatic: `<upstream>-<revision>+armbian<n>~<release>` |
| Build dependencies | Other PPAs or the archive | `build_depends`: built in the same run |
| Review | None | Pull request, Check workflow, dry-run build |

To move a package from a PPA:

1. Find the newest Debian or Ubuntu source package of it. Use it as `packaging`. Do not copy its `debian/` into this repository.
2. Set `upstream` when the PPA builds newer code than that package.
3. Put each change to the packaging or the code in `build/<name>/patches/`. Put a change for one release in `patches/<release>/`.
4. Run the Build workflow by hand with `only: <name>` and `dry_run: true`. Fix each release that fails, or leave it out with `skip`.

| Part | Where | Use |
|---|---|---|
| Packaging | `packaging:` a Debian or Ubuntu source package, or `build/<name>/debian/` | `debian/` directory. The source package also gives the code when there is no `upstream`. |
| Upstream | `upstream:` a git tag or branch | Code in place of the packaged code. Its own `debian/` is replaced. |
| Patches | `build/<name>/patches/series`, then `patches/<release>/series` | Optional. Applied with `patch -p1` after packaging and upstream. For code that we do not control or fork. Release patches apply to that release only, for example `trixie/` for an older LLVM. |

```yaml
name: fastfetch
method: build
packaging:                 # newest source package in this suite
  url: https://deb.debian.org/debian
  suite: sid
  components: [main]
  package: fastfetch
upstream:                  # optional
  url: https://github.com/fastfetch-cli/fastfetch
  ref: latest              # latest GitHub release (default), a tag or a branch
releases: all
architectures: [arm64, amd64]
target: utils
install: [fastfetch]
```

| Key | Meaning |
|---|---|
| `packaging.url`, `.suite`, `.components`, `.package` | apt repository and source package. Signature and hashes are checked, as for `apt`. |
| `upstream.url`, `.ref` | git repository and tag or branch. `latest` (default): the latest GitHub release, or on other hosts the newest release tag. |
| `upstream.tags` | Pattern for `latest`, for example `mesa-*`. Release candidates are left out. |
| `upstream.version` | For a branch: the next upstream release, for example `27.0.0`. |
| `upstream.version_file` | For a branch: a file that holds that version, for example `VERSION` (`27.0.0-devel` gives `27.0.0`). Read from the rebase base when `rebase` is set. |
| `upstream.rebase.url`, `.ref` | Optional, off by default. A fork: rebase it onto this branch before each build. A conflict fails the build, and the last good packages stay. |
| `upstream.meson_subprojects` | Meson wraps to download before the build: names or globs, for example `*-rs`. Debian packaging builds with `--wrap-mode=nodownload`. Meson uses a wrap only when the system has no copy. |
| `revision` | Armbian revision. Default 1. Increase it when the patches or the build keys change, but the sources do not. A live run fails when changed inputs give a version that is already uploaded: the upload never replaces a file. A dry run warns. |
| `build_depends` | Other build configs whose packages this build needs, for example `libdrm` for `mesa`. One level only. |

Architectures: `amd64` and `arm64`, on native GitHub runners.

Version of the built packages:

| Build | Version |
|---|---|
| Packaging only | `<packaged version>+armbian<revision>~<release>` |
| Upstream tag | `<tag version>-<packaged revision>+armbian<revision>~<release>` |
| Upstream branch or rebase | `<upstream.version>~git<YYYYMMDDHHMM>.<commit>-<packaged revision>+armbian<revision>~<release>` |

`~<release>` gives each release its own file name. One repository pool holds all releases.

A build runs again only when its identity changes: the source package hash, the upstream commits, the files under `build/<name>/`, the build keys of the config (`packaging`, `upstream`, `revision`, `build_depends`, `include_debug`), or the version.
Architecture-independent packages (`_all.deb`) come from the first architecture only.

`build_depends`: the dependency builds first, in the same run. Its packages go into a local apt repository in the container, and they win over the release's own versions. A dependency always builds again with a config that needs it. When the dependency has no build for a release, the release's own version is used.

### Build steps

`extpkg build` runs as root in the container of the release:

1. Packaging: download the source package and check its hashes against the signed `Sources` index. Unpack it with `dpkg-source -x`. Without `packaging`: take `build/<name>/debian/`.
2. Upstream: clone the tag or branch. With `rebase`: rebase onto the base branch. Then replace upstream's `debian/` with the packaging.
3. Patches: `patches/series`, then `patches/<release>/series`, with `patch -p1`.
4. Changelog: a new entry with the Armbian version.
5. `build_depends`: a local apt repository with their packages.
6. `apt-get build-dep`, then `meson subprojects download` for `upstream.meson_subprojects`.
7. `dpkg-buildpackage -b` (first architecture) or `-B` (others), with `nocheck`. Debug packages are left out unless `include_debug` is set.

### Recipes

Rebuild a Debian package for every release (packaging only):

```yaml
packaging: {url: https://deb.debian.org/debian, suite: sid, components: [main], package: libdrm}
```

Newer upstream release on Debian packaging, one patch for all releases (`fastfetch`):

```yaml
packaging: {url: https://deb.debian.org/debian, suite: sid, components: [main], package: fastfetch}
upstream: {url: https://github.com/fastfetch-cli/fastfetch}     # ref: latest
```

Fork branch, version from a file, optional rebase onto the original branch (`mesa`):

```yaml
upstream:
  url: https://gitlab.freedesktop.org/mojyack/mesa.git
  ref: t210-develop
  version_file: VERSION
  meson_subprojects: [venus-protocol]
  # rebase:                       # switch: uncomment to rebase before each build
  #   url: https://gitlab.freedesktop.org/mesa/mesa.git
  #   ref: main
build_depends: [libdrm, directx-headers, cbindgen]
repositories: [beta]
```

Local packaging, no Debian package (`cbindgen`): no `packaging` key. `build/cbindgen/debian/` holds `control`, `rules` and `source/format`. The builder writes the changelog.

A release with older tools: put a patch in `patches/<release>/`. Example: `build/mesa/patches/trixie/llvm-19.patch`.

A build dependency that a release lacks: a build config for it, limited to that release with `releases`, and named in `build_depends`. Example: `libdrm` for trixie and resolute.

### Write a patch

A patch applies to the tree after the packaging, the upstream code and the earlier patches. Paths start with `a/` and `b/`, for example `a/debian/rules`.
A patch can change `debian/` or the code. To drop a patch of the source package, change `debian/patches/series` (example: `build/mesa/patches/drop-lp2143073.patch`).

### Test a build locally

```sh
python3 -m extpkg plan --configs build --only mesa --out plan.json
docker run --rm -v "$PWD:/src" -w /src debian:trixie sh -c '
  apt-get update && apt-get install -y python3 python3-yaml git ca-certificates dpkg-dev build-essential fakeroot patch xz-utils
  for c in libdrm directx-headers cbindgen; do python3 -m extpkg build --plan plan.json --config $c --release trixie --arch amd64 --out deps; done
  python3 -m extpkg build --plan plan.json --config mesa --release trixie --arch amd64 --out built --deps deps'
```

`_all.deb` files come from the first architecture in `architectures`. On an amd64 host, put `amd64` first for a local test.

## Workflows

### Check (`.github/workflows/check.yml`)

Runs on pull requests and on pushes to `main`.

1. Unit tests.
2. Validate all configs.
3. Plan all configs.
4. Dry-run download of the changed configs. When more than 8 configs change, this step is skipped: use Sync with a dry run.

Method `build` configs are planned only. The Build workflow builds them.

Check uses no secrets.

### Build (`.github/workflows/build.yml`)

Runs daily, by hand, and on pull requests that change `build/`, `extpkg/` or the workflow. Manual inputs: `only` and `dry_run` (default true).
Pull requests are always dry runs. Scheduled runs are dry runs until the repository variable `BUILD_LIVE` is `true`.

1. **plan**: resolve the sources. List the builds whose identity is not in the last manifest.
2. **deps**: the configs that others name in `build_depends`.
3. **build**: the other configs, with the deps outputs. Both stages: one job per config, release and architecture. Container `debian:<release>` or `ubuntu:<release>`, runner `ubuntu-24.04` (amd64) or `ubuntu-24.04-arm` (arm64). `apt-get build-dep`, then `dpkg-buildpackage`. Tests are not run (`nocheck`).
4. **publish**: place the built files in the Sync layout, upload, and remove old versions. Status and manifest go to `.sync/shard-build.json` and `.sync/manifest-shard-build.json`, next to the Sync shards.

A failed build skips only its own release and architecture. Its old files stay.

### Sync (`.github/workflows/sync.yml`)

Runs every 2 hours (live), and by hand. Manual inputs: `only` (config names) and `dry_run` (default true).

- 4 shards. A config always lands in the same shard (hash of its name).
- Each shard plans, fetches and uploads its own configs.
- With `dry_run`, the shard does everything except the upload.

#### State

Each shard keeps the `manifest.json` of its last successful run in the GitHub Actions cache (`state-<live|dry>-shard-<n>-<run id>`).
A file is not downloaded again when the config, release, architecture, URL and upstream SHA256 match an entry in that manifest. The server already has it.
Without an upstream hash, the identity is:

- `url`: the final URL after redirects (without the query), `ETag`, `Last-Modified` and size, from a `HEAD` request in the plan;
- `github` assets without a digest (older releases): asset ID, update time and size.

A file with the same identity is not downloaded again. It is still unverified.
State is saved only after a successful run. Dry runs and live runs keep separate state.

#### Upload

The upload starts during the download. After an upstream file is downloaded, checked and placed in every directory, its new paths go to an upload queue. A batch goes to the server every 30 s, or at 500 MB.

Up to 3 batches go at the same time (`--streams`): one SSH stream to the repository server reaches only 10-18 MB/s.

Each batch is one `rsync -H --files-from`. A file placed in several directories (releases, `debs` and `debs-beta`) is a hardlink, so rsync sends its data once and links it on the server. Without `-H` a full run sends 40 GiB; with it, 12 GiB.

If a batch fails, the run stops downloading, removes nothing and saves no state.

#### Status for the repository update

Each shard writes its state to the server, next to the packages:

```
<UPLOAD_PATH>/.sync/shard-<n>.json            "running", "done" or "failed"
<UPLOAD_PATH>/.sync/manifest-shard-<n>.json   manifest of the last successful run
```

`shard-<n>.json` holds the run ID and URL, the runner, start and finish times. When the state is `done`, it also holds the number of paths, the bytes sent, the number of removed files and `manifest_sha256`: the fingerprint of the set that the shard put on the server.

- `running` is written before the first download. If it cannot be written, the run stops.
- `done` is written after the upload and the removal of old versions. The manifest is written first.
- `failed` is written when the run stops with an error, or when the job fails or is cancelled.
- Each file is written to a temporary name and renamed, so a reader never sees half a file.

Rules for the repository update:

- Publish only when no `shard-<n>.json` is `running`.
- A `running` file older than the Sync timeout (2 h) means the runner died. Treat it as `failed`.
- After a `failed` shard, the files of its last `done` run are still on the server.
- Copy only `*.deb`. The `.sync/` directory is not a package directory.

#### Old versions

The upload never replaces files. Without a cleanup, each new upstream version (for example a daily VS Code build) adds a file.

After a successful upload, the run removes the files that it uploaded earlier and that are no longer current:

- The previous manifest of the shard lists every file that the last run put on the server.
- A file in the previous manifest and not in the current set is old. The newest `keep` versions stay. The rest are removed.
- The removal deletes only the listed paths, with `rsync --delete-missing-args --files-from`. Each path must be under `debs/` or `debs-beta/` and end in `.deb`.

The run removes nothing when:

- a download or check of that config, release and architecture failed in this run;
- the path is still in use (an `_all.deb` for several architectures);
- the config is not in this run (`--only`, another shard). Its entries stay in the state.

The run does remove the files of a config that is disabled (`enabled: false`), and in a full run (no `--only`) the files of a config that was deleted from `mirror/`.

Shards share the server directories:

- Before a removal, a live run reads the other shards' manifests (`.sync/manifest-shard-*.json`). It never removes a path that another shard lists: two configs in two shards can place the same file, for example after a rename. If the manifests cannot be read, the run removes nothing and keeps the entries for the next run.
- A deleted config waits one run (`orphan-pending`). By then every shard has published its manifest, also the shard that a renamed config moved to.

A dry run prints `would remove` lines. Files that this tool did not upload are never touched.

#### Runners

| | GitHub-hosted | Self-hosted |
|---|---|---|
| Select | default | `RUNNER_LABELS` |
| Before the job | nothing (public repositories get 145 GB disks, 88 GB free) | `armbian/actions/runner-clean` |
| Download cache | per job | `CACHE_DIR/shard-<n>`, pruned each run |

Missing tools (`gpgv`, `dpkg-deb`, `fakeroot`, `rsync`, `ssh`, `python3-yaml`) are installed. `sudo` is used only when it exists.

### Variables

| Variable | Use | Default |
|---|---|---|
| `RUNNER_LABELS` | JSON runner labels, for example `["self-hosted","Linux","X64"]` | `"ubuntu-latest"` |
| `CACHE_DIR` | Persistent download cache on self-hosted runners | per job |
| `UPLOAD_PATH` | Destination directory on the server | `storage/incoming/external-next` |

### Secrets

Needed for an upload only. Organisation secrets, shared with armbian.github.io.

| Secret | Use |
|---|---|
| `KEY_UPLOAD` | Private SSH key of the upload user |
| `KNOWN_HOSTS_ARMBIAN_UPLOAD` | Host key of the server. Host keys are checked. |
| `HOST_UPLOAD` | Server name |
| `HOST_UPLOAD_USER` | SSH user |
| `HOST_UPLOAD_PORT` | SSH port. Default: 22. |

`GITHUB_TOKEN` comes from Actions. It raises the GitHub API rate limit.

### Dependency check

Can apt install a package on the Armbian release? `extpkg depcheck` (or `run --depcheck`) answers this for the new files of a run, without installing anything:

- One temporary apt root per release and architecture. It does not touch the host apt and needs no root access. `APT_CONFIG` keeps the host apt configuration out.
- Sources: the distribution (Debian or Ubuntu, from `config/distributions/<release>/name` in armbian/build, with `-updates` and `-security`), the Armbian repository, and a local repository with the new files. The local files win (pin 1001).
- `apt-get install --simulate <package>=<version>` for the `install` packages of each config. apt resolves dependencies for any architecture, so one x86 runner checks all of them.
- Index lists are kept compressed in `.cache/apt-lists` (about 650 MB for all releases and architectures). The next `apt update` only checks for changes.

Where it runs:

| Workflow | Scope | On failure |
|---|---|---|
| Check (pull requests) | changed configs, up to 8 | the check fails |
| Dependency check (daily) | files that changed upstream since the last check | one open issue, label `depcheck` |

A failing package that does not change upstream is not checked again. Fix its config, then close the issue.

### Package site (`.github/workflows/pages.yml`)

A GitHub Pages site lists every config and its state: https://external.armbian.com/

- Runs after each successful Sync or Build run on `main`, and after a config change.
- Input: the configs and the manifests of the last live runs, from the `state-live-*` caches. Dry runs never show.
- Output: `index.html` (one file, search and filters) and `packages.json` (the same data).
- Description: the `Description` field of the main package. Older manifest entries lack it: the site then reads the Armbian stable and beta indexes.

| State | Meaning |
|---|---|
| Ready | files for every release and architecture that upstream builds |
| Partial | some files missing or failed |
| Missing | no files |
| Disabled | `enabled: false` |

Per release and architecture: "stable" when the stable repository has the version or gets it from this run, else "beta".

## Command line

```
python3 -m extpkg validate
python3 -m extpkg plan  [--only a,b] [--shard i/n] [--out plan.json]
python3 -m extpkg fetch --plan plan.json [--out output] [--cache dir]
python3 -m extpkg run   [--only a,b] [--shard i/n] [--out output] [--cache dir]
                        [--previous manifest.json] [--prune-cache] [--strict]
                        [--dry-run | --dest user@host:/path --port n --known-hosts file]
python3 -m extpkg upload --out output --dest user@host:/path [--dry-run]
python3 -m extpkg depcheck --out output [--lists-cache dir] [--keyring file] [--strict]
python3 -m extpkg build-matrix --plan plan.json [--previous manifest.json]
python3 -m extpkg build --plan plan.json --config name --release r --arch a [--out built]
python3 -m extpkg run --configs build --shard build --plan plan.json --built built ...
python3 -m extpkg site --manifest dir/manifest.json ... [--out site] [--published url ...]
```

`--configs`: the config directory. Default: `mirror/`; `build/` for `build-matrix` and `build`. `validate` checks both.

Common options: `--configs`, `--keys`, `--build-dir`, `--jobs`, `--published`.
`--strict` exits 1 when a download or check fails. "No package matched" is not a failure.

## Code

| File | Content |
|---|---|
| `extpkg/config.py` | Load and check package configs, expand releases |
| `extpkg/apt.py` | apt repositories: signatures, indexes, filter |
| `extpkg/github.py` | GitHub releases |
| `extpkg/url.py` | Direct downloads |
| `extpkg/query.py` | Filter parser |
| `extpkg/debver.py` | Debian version compare |
| `extpkg/debfile.py` | Read and repack `.deb` files |
| `extpkg/published.py` | Versions in the published stable repository |
| `extpkg/pipeline.py` | Plan, fetch, manifest, report |
| `extpkg/upload.py` | rsync upload |
| `extpkg/source.py` | Method build: resolve packaging, upstream and patches; version and identity |
| `extpkg/builder.py` | Method build: build in a container of the release |
| `extpkg/site.py` | Package site: configs and manifests to `index.html` and `packages.json` |
| `tools/import-os.py` | One-time import of `armbian/os/external/*.conf` |

## Differences from the old pipeline

The old pipeline was `infrastructure-download-external.yml` in armbian.github.io, with configs in `armbian/os/external`.

| Old | Now |
|---|---|
| aptly mirror with `-ignore-signatures` | Signature, index hash and `.deb` hash checked |
| GitHub assets not checked | GitHub SHA256 digest checked |
| Epoch dropped from the new version only: stable never updates firefox or thunderbird | Full Debian version compare |
| Firefox repack checked the name `firefox`; configs are `firefox-noble`, `firefox-resolute`: no repack | Repack is config |
| One container job per package, release and architecture (about 300 jobs) | 4 jobs, parallel downloads inside |
| Every run downloads everything | Only files that changed upstream |
| `StrictHostKeyChecking=no` | Host keys checked |
| Exceptions in code (fastfetch, haos, firefox) | Exceptions in config (`exclude`, `assets`, `repack`) |

Keys added or replaced during the port, each checked against the signer of its repository:
`raspberrypi.gpg` (new), `xtradeb-apps.gpg` (new, Chromium PPA), `arter97-zfs.gpg` (new, ZFS PPA), `google-chrome.gpg` (refreshed, rotated key).

## Known limits

- `url` sources have no upstream hash, unless the config pins one.
- Old versions are removed only for files that this tool uploaded. Files from the old pipeline need a one-time cleanup.
- Method build: `amd64` and `arm64` only, on native runners. No emulation.
- Method build: one packaging source for all releases. Differences between releases go into `patches/<release>/`.
- Method build: `build_depends` is one level deep. A dependency cannot have dependencies.
- Method build: tests do not run (`nocheck`).
- Method build: a cargo build in local packaging (`cbindgen`) downloads its crates at build time, pinned by `Cargo.lock`.
- Method build: GitHub-hosted runners only. Self-hosted runners need runner labels, a cleanup of root-owned files, and no pull request builds.
