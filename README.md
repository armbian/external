# Armbian external packages

Third-party Debian packages for the Armbian apt repository: VS Code, Chromium, Firefox, ZFS, Raspberry Pi userspace, and more.

This repository holds the package list, the upstream signing keys and the tool that downloads, checks and sorts the packages.
The Armbian repository update takes the result and publishes it.

## What it produces

```
debs-beta/extra/<release>-<target>/   every package, for the beta repository
debs/extra/<release>-<target>/        packages newer than the published stable version
manifest.json                         source, version and SHA256 of each file
```

## Quick start

```sh
python3 -m extpkg validate                       # check the package configs
python3 -m extpkg run --dry-run --only gh        # download and check one package, no upload
```

## Add a package

Read [CONTRIBUTING.md](CONTRIBUTING.md). With Claude Code, run the `add-external-package` skill.

## More

- [docs/technical.md](docs/technical.md): checks, config reference, workflows, state, variables and secrets.
