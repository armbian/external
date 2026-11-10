"""Versions and files published in an Armbian repository (stable or beta)."""

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
        versions, descriptions, files = {}, {}, {}
        url = f"{self.url}/dists/{release}/{component}/binary-{arch}/Packages.gz"
        try:
            text = gzip.decompress(net.get_bytes(url)).decode("utf-8", "replace")
        except net.FetchError:
            text = ""
        for stanza in text.split("\n\n"):
            f = {}
            for line in stanza.splitlines():
                k, sep, v = line.partition(": ")
                if sep and not line.startswith(" "):
                    f[k] = v.strip()
            name, v = f.get("Package"), f.get("Version")
            if not name or not v:
                continue
            if name not in versions or debver.compare(v, versions[name]) > 0:
                versions[name] = v
            if "Description" in f:
                descriptions[name] = f["Description"]
            if "Filename" in f and "SHA256" in f:
                files[(name, v)] = (f"{self.url}/{f['Filename']}", f["SHA256"])
        with self._lock:
            self._cache[key] = (versions, descriptions, files)
        return self._cache[key]

    def _component(self, release, target):
        return "main" if target == "main" else f"{release}-{target}"

    def version(self, release, target, arch, package):
        """Newest published version of one binary package, or None."""
        return self._index(release, self._component(release, target), arch)[0].get(package)

    def description(self, release, target, arch, package):
        """Short description of one published binary package, or None."""
        return self._index(release, self._component(release, target), arch)[1].get(package)

    def file(self, release, target, arch, package, version):
        """(URL, SHA256) of one published binary package, or None."""
        return self._index(release, self._component(release, target), arch)[2].get((package, version))
