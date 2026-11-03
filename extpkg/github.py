"""Resolve .deb assets of a GitHub release."""

import fnmatch
import re
import threading

from . import net

# Same patterns as the old download workflow.
ARCH_PATTERNS = {
    "amd64": ["*amd64*.deb", "*x86_64*.deb", "*x64*.deb"],
    "arm64": ["*arm64*.deb", "*aarch64*.deb"],
    "armhf": ["*armhf*.deb", "*armv7*.deb", "*armv7l*.deb", "*armv6*.deb"],
    "riscv64": ["*riscv64*.deb"],
}
ALL_PATTERNS = ["*_all.deb"]

_cache = {}
_locks = {}
_guard = threading.Lock()


def _repo(url):
    m = re.search(r"github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", url)
    if not m:
        raise ValueError(f"not a GitHub repository URL: {url}")
    return m.group(1)


def release(url, tag=None):
    repo = _repo(url)
    key = (repo, tag)
    with _guard:
        lock = _locks.setdefault(key, threading.Lock())
    # One API call per repository and tag, also when threads ask at once.
    with lock:
        if key not in _cache:
            api = f"https://api.github.com/repos/{repo}/releases/" + (f"tags/{tag}" if tag else "latest")
            _cache[key] = net.get_json(api, net.github_headers())
    return _cache[key]


def resolve(pkg, release_name, arch, keyring=None):
    src = pkg["source"]
    rel = release(src["url"], src.get("tag"))
    patterns = pkg.get("assets") or (ARCH_PATTERNS.get(arch, []) + ALL_PATTERNS)
    exclude = pkg.get("exclude") or []
    out = []
    for a in rel.get("assets", []):
        name = a["name"]
        if not any(fnmatch.fnmatchcase(name, p) for p in patterns):
            continue
        if any(fnmatch.fnmatchcase(name, p) for p in exclude):
            continue
        digest = a.get("digest") or ""
        out.append({
            "package": None,     # read from the .deb after download
            "version": None,
            "arch": arch,
            "url": a["browser_download_url"],
            "filename": name,
            "sha256": digest[7:] if digest.startswith("sha256:") else None,
            "size": a.get("size"),
            "signature": "none",
            "tag": rel.get("tag_name"),
        })
    return out
