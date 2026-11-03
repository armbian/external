# Armbian external packages

Third-party Debian packages for the Armbian apt repository.

## Goal

One repository for each external package: its configuration, signing keys, fetch, build, patch and retention.
The publish workflow in armbian.github.io takes only finished, verified package sets from here.

## Package types

| Type | Action |
|---|---|
| `download` | Fetch a prebuilt package (GitHub release, apt repository, URL). Verify the signature or hash. |
| `repack` | Download, then change the binary package (control fields, files, scripts). |
| `source-patch` | Get the Debian source, apply our patches, rebuild. |
| `build` | Build from an upstream tag or tarball in a clean chroot. |

Our builds add `+armbianN` to the version.

## Layout (planned)

```
packages/<name>/package.yaml   # type, source, releases, architectures, target
packages/<name>/patches/       # source-patch and repack changes
keys/                          # upstream signing keys
state/versions.json            # last version and hash per package, release, architecture
policy.yaml                    # versions to keep per package
.github/workflows/             # PR check, sync (plan, fetch/build, hand-off)
```

## Hand-off

Each sync run writes a package set to the repository server, with `manifest.json` and a `.done` marker.
A failed sync never blocks a publish.
