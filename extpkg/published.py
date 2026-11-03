"""Versions currently published in the Armbian stable repository."""

import gzip
import threading

from . import debver, net

DEFAULT_URL = "https://fi.mirror.armbian.de/apt"


class Published:
    def __init__(self, url=DEFAULT_URL):
        self.url = url.rstrip("/")
        self._cache = {}
        self._lock = threading.Lock()

    def _index(self, release, component, arch):
        key = (release, component, arch)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        versions = {}
        url = f"{self.url}/dists/{release}/{component}/binary-{arch}/Packages.gz"
        try:
            text = gzip.decompress(net.get_bytes(url)).decode("utf-8", "replace")
        except net.FetchError:
            text = ""
        name = None
        for line in text.splitlines():
            if line.startswith("Package: "):
                name = line[9:].strip()
            elif line.startswith("Version: ") and name:
                v = line[9:].strip()
                if name not in versions or debver.compare(v, versions[name]) > 0:
                    versions[name] = v
                name = None
        with self._lock:
            self._cache[key] = versions
        return versions

    def version(self, release, target, arch, package):
        """Newest published version of one binary package, or None."""
        component = "main" if target == "main" else f"{release}-{target}"
        return self._index(release, component, arch).get(package)
