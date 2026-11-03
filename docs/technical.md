# Technical description

## Flow

```
packages/*.yaml ──plan──► plan.json ──fetch──► output/ ──upload──► repository server
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
- `<file>` is the upstream file name. A repacked file gets `<package>_<version>_<arch>.deb`. A `url` download is `<config>.deb`, unless the config sets `filename`.
- The same file in several places is a hardlink. It uses disk space once.

The layout is the same as `storage/incoming/external` of the old download workflow.

### Beta and stable

- Beta gets every file.
- Stable gets a file only when its version is newer than the version of the same binary package in the published stable repository.
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

`packages/<name>.yaml`. The file name is the config name.

| Key | Required | Meaning |
|---|---|---|
| `name` | yes | Same as the file name. |
| `method` | yes | `apt`, `github` or `url`. |
| `source.url` | yes | Repository, GitHub project or file URL. An `http://` apt URL is tried as `https://` first. |
| `source.suite` | apt | Suite (`noble`, `stable`) or a flat repository (`./`). |
| `source.components` | no | apt components. Default: `main`. |
| `source.tag` | no | github: release tag. Default: latest release. |
| `source.sha256` | no | url: expected SHA256. |
| `filter` | apt | Which packages to take. See below. |
| `with_deps` | no | Also take the dependencies found in the same index. Default: true when `filter` has no `Name` or `Version`. |
| `releases` | yes | `all` or a list of releases. |
| `architectures` | yes | `amd64`, `arm64`, `armhf`, `riscv64`, `loong64`, `i386`. |
| `target` | no | `main`, `utils` or `desktop`. Default: `main`. |
| `install` | no | Main package names. For tests and documentation. |
| `assets` | no | github: asset name patterns. Default: patterns for the architecture. |
| `exclude` | no | github: asset name patterns to drop. |
| `filename` | no | url: output file name. |
| `repack` | no | `packages`, `epoch`, `suffix`: rebuild these packages with a new version. |
| `verify` | no | `signature`, `checksums`. Both default to true. |
| `include_debug` | no | Also mirror debug packages (`*-dbg`, `*-dbgsym`). Default: false. |
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

## Workflows

### Check (`.github/workflows/check.yml`)

Runs on pull requests and on pushes to `main`.

1. Unit tests.
2. Validate all configs.
3. Plan all configs.
4. Dry-run download of the changed configs. When more than 8 configs change, this step is skipped: use Sync with a dry run.

Check uses no secrets.

### Sync (`.github/workflows/sync.yml`)

Manual for now. Inputs: `only` (config names) and `dry_run` (default true).

- 4 shards. A config always lands in the same shard (hash of its name).
- Each shard plans, fetches and uploads its own configs.
- With `dry_run`, the shard does everything except the upload.

#### State

Each shard keeps the `manifest.json` of its last successful run in the GitHub Actions cache (`state-<live|dry>-shard-<n>-<run id>`).
A file is not downloaded again when the config, release, architecture, URL and upstream SHA256 match an entry in that manifest. The server already has it.
`url` files have no upstream hash, so they are always downloaded.
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

## Command line

```
python3 -m extpkg validate
python3 -m extpkg plan  [--only a,b] [--shard i/n] [--out plan.json]
python3 -m extpkg fetch --plan plan.json [--out output] [--cache dir]
python3 -m extpkg run   [--only a,b] [--shard i/n] [--out output] [--cache dir]
                        [--previous manifest.json] [--prune-cache] [--strict]
                        [--dry-run | --dest user@host:/path --port n --known-hosts file]
python3 -m extpkg upload --out output --dest user@host:/path [--dry-run]
```

Common options: `--packages`, `--keys`, `--build-dir`, `--jobs`, `--published`.
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
- A `url` file has a fixed name (`discord.deb`). The upload does not overwrite, so the server keeps the first version. A name with the version needs a code change: the version is known only after the download.
- Package types `source-patch` and `build` are planned, not implemented.
