# Armbian external packages

Third-party Debian packages for the Armbian apt repository: VS Code, Chromium, Firefox, ZFS, Raspberry Pi userspace, mesa, and more.

Package list with versions per release and architecture: https://github.armbian.com/external/

This repository holds the package list, the upstream signing keys and the tool that downloads, builds, checks and sorts the packages.
The Armbian repository update takes the result and publishes it.

## Layout

```
mirror/<name>.yaml        built packages to download: apt repository, GitHub release, URL
build/<name>.yaml         packages to build from source: Debian or Ubuntu packaging,
build/<name>/patches/       optional upstream code and optional patches
build/<name>/debian/        own packaging, when Debian and Ubuntu have none
keys/                     upstream signing keys
extpkg/                   the tool
```

## Workflows

| Workflow | Configs | Runs | Dry run |
|---|---|---|---|
| Sync | `mirror/` | every 2 hours | by hand: `dry_run` (default true) |
| Build | `build/` | daily, pull requests | always for pull requests; scheduled runs until `BUILD_LIVE` is `true` |
| Check | both | pull requests | always |
| Package site | both | after Sync and Build | - |

## What it produces

```
debs-beta/extra/<release>-<target>/   every package, for the beta repository
debs/extra/<release>-<target>/        packages newer than the published stable version
manifest.json                         source, version and SHA256 of each file
```

A config can limit itself to one repository: `repositories: [beta]`.

## Quick start

```sh
python3 -m extpkg validate                                 # check all configs
python3 -m extpkg run --dry-run --only gh                  # download and check one package, no upload
python3 -m extpkg plan --configs build --only fastfetch    # resolve the sources of one build
```

A build runs in a container of the release. See [docs/technical.md](docs/technical.md#test-a-build-locally).

## Add a package

Read [CONTRIBUTING.md](CONTRIBUTING.md). With Claude Code, run the `add-external-package` skill.

## More

- [docs/technical.md](docs/technical.md): checks, config reference, builds, workflows, state, variables and secrets.
