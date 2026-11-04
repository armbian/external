"""Resolve a package from a direct download URL."""

from . import net


def resolve(pkg, release, arch, keyring=None):
    src = pkg["source"]
    # Download name only. The fetch names the file after its control fields,
    # because the version is known only after the download.
    filename = pkg.get("filename") or f"{pkg['name']}.deb"
    # No upstream hash: identify the file by what the server says about it.
    # The final URL often holds the version (Discord redirects to it).
    identity = None
    if not src.get("sha256"):
        try:
            h = net.head(src["url"])
            if h["etag"] or h["modified"] or h["url"] != src["url"]:
                # Drop the query: CDN redirects carry a new signature each time.
                final = h["url"].split("?", 1)[0]
                identity = f"url:{final}|{h['etag']}|{h['modified']}|{h['length']}"
        except net.FetchError:
            pass
    return [{
        "package": None,
        "version": None,
        "arch": arch,
        "url": src["url"],
        "filename": filename,
        "sha256": src.get("sha256"),
        "size": None,
        "signature": "none",
        "identity": identity,
        "fixed_url": True,   # the URL does not change with the version
    }]
