"""Resolve a package from a direct download URL."""


def resolve(pkg, release, arch, keyring=None):
    src = pkg["source"]
    # The old pipeline saved direct downloads as <config>.deb. Keep that name
    # unless the config sets one. A fixed name never changes, so a consumer
    # that copies with --ignore-existing keeps the first file it got.
    filename = pkg.get("filename") or f"{pkg['name']}.deb"
    return [{
        "package": None,
        "version": None,
        "arch": arch,
        "url": src["url"],
        "filename": filename,
        "sha256": src.get("sha256"),
        "size": None,
        "signature": "none",
    }]
