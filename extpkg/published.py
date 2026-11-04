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
        versions, descriptions = {}, {}
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
            elif line.startswith("Description: ") and name:
                descriptions[name] = line[13:].strip()
        with self._lock:
            self._cache[key] = (versions, descriptions)
        return self._cache[key]

    def _component(self, release, target):
        return "main" if target == "main" else f"{release}-{target}"

    def version(self, release, target, arch, package):
        """Newest published version of one binary package, or None."""
        return self._index(release, self._component(release, target), arch)[0].get(package)

    def description(self, release, target, arch, package):
        """Short description of one published binary package, or None."""
        return self._index(release, self._component(release, target), arch)[1].get(package)
