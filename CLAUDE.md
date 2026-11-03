# Instructions for Claude

This repository downloads third-party Debian packages for the Armbian apt repository.
Read [docs/technical.md](docs/technical.md) before you change code.

## Add a package

Use the `add-external-package` skill. It follows [CONTRIBUTING.md](CONTRIBUTING.md).

## Rules

- Never upload. Use `--dry-run`. Only a person runs Sync with `dry_run=false`.
- Never add a signing key that you did not check. The key must hold the fingerprint that signs the repository, and the fingerprint must come from a second source (Launchpad API, vendor documentation).
- Never turn off `verify.signature` or `verify.checksums` without the user's approval.
- Work on a branch. Open a pull request. Do not push to `main`.
- Run `python3 -m unittest discover -s tests -t .` and `python3 -m extpkg validate` before each commit.
- End commit messages with `Signed-off-by:`.

## Style

Text, comments and commit messages: ASD-STE100 Simplified Technical English. One idea per sentence. Active voice. Keep it short.
