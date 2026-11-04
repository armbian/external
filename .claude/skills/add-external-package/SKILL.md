---
name: add-external-package
description: Add a third-party Debian package source to armbian/external - find the best source (signed apt repository, GitHub release, URL), check and add its signing key, write mirror/<name>.yaml, test with a dry run, and open a pull request. Use when the user asks to add, mirror or include an external package.
---

# Add an external package

Follow these steps in order. Stop and ask the user when a step says so.

## 1. Collect

Ask for anything that is missing:

- The package or application name.
- The Armbian releases (`all` or a list) and architectures.
- Desktop application or tool (`target: desktop` or `utils`).

Check that the package is not already there: `grep -l "<name>" mirror/*.yaml build/*.yaml`.

## 2. Find the source

Search the upstream install instructions. Prefer, in this order:

1. A signed apt repository. Find the repository URL, the suite and the components.
   Check that it builds the needed architectures:
   `curl -fsSL <url>/dists/<suite>/InRelease | grep -E "^(Architectures|Components):"`.
2. A GitHub release with `.deb` assets for the needed architectures.
3. A direct URL. Tell the user that this source cannot be checked, and ask before you continue.

If upstream offers a different repository for each Ubuntu or Debian release, write one config for each (`<name>-<release>`), as `mirror/firefox-noble.yaml` does.

## 3. Signing key (apt)

1. Get the signing fingerprint:
   `curl -fsSL <url>/dists/<suite>/InRelease -o /tmp/InRelease && gpgv /tmp/InRelease 2>&1 | grep using`.
2. Look in `keys/` for that key:
   `for k in keys/*.gpg; do gpg --show-keys --with-colons "$k" | grep -q <fingerprint> && echo "$k"; done`.
   If it exists, go to step 4.
3. Confirm the fingerprint from a second source:
   - Launchpad PPA: `curl -fsSL https://api.launchpad.net/1.0/~<owner>/+archive/ubuntu/<ppa> | jq -r .signing_key_fingerprint`.
   - Vendor: the key URL or fingerprint in the vendor install instructions.
   If you cannot confirm it, stop and ask the user.
4. Get the key from the vendor URL or from `https://keyserver.ubuntu.com/pks/lookup?op=get&options=mr&search=0x<fingerprint>`.
5. Check that the key holds the fingerprint (`gpg --show-keys --with-colons <file> | grep ^fpr`).
   Store it in binary form: `gpg --dearmor < key.asc > keys/<vendor>.gpg`.
6. Write down where the key and the fingerprint come from. The pull request text needs it.

## 4. Write the config

Create `mirror/<name>.yaml`. A build from source goes to `build/<name>.yaml` instead (see `docs/technical.md`, section "Builds"). Copy the closest existing config. The keys are in `docs/technical.md` (section "Package config").

- apt: write a `filter` that takes only the needed packages. Use `Name (% <glob>)` and `|`. Debug packages (`*-dbg`, `*-dbgsym`) are left out by default; set `include_debug: true` only if the user asks.
- github: add `exclude` for assets that the architecture patterns take by mistake (for example `exclude: ['*polyfilled*', '*armv6l.deb']`).
- Do not set `verify.signature: false` or `verify.checksums: false`. If upstream needs it, stop and ask the user.

## 5. Test

```sh
python3 -m extpkg validate
python3 -m extpkg plan --only <name> --out /tmp/plan.json
GITHUB_TOKEN=$(gh auth token) python3 -m extpkg run --dry-run --only <name> --out /tmp/out-<name> --cache /tmp/cache
```

Check:

- `plan` has no `SKIP` line. "no package matched" is acceptable only for an architecture that upstream does not build. Tell the user which ones.
- Each `run` line says `sig+sha` (apt) or `sha` (github).
- `find /tmp/out-<name> -name '*.deb'` lists the expected packages, and only those.
- `dpkg-deb -f <file> Package Version Architecture` is correct for one file of each architecture.

If a check fails, fix the config and test again. Do not turn off a check.

## 6. Pull request

1. `git checkout -b add-<name>`.
2. Commit only `mirror/<name>.yaml` and the new key file. Message:
   ```
   Add <name>: <one line: what it is>

   Signed-off-by: <user name> <user email>
   ```
3. Push and open a pull request with:
   - the source URL and method;
   - for apt: the key fingerprint and where you confirmed it;
   - the dry-run result: files, architectures, any "no package matched".
4. Give the user the pull request URL. Never run Sync with `dry_run=false`.
