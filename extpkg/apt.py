"""Resolve packages from an apt repository.

Trust chain, as apt uses it: InRelease (or Release + Release.gpg) signed by a
key in keys/ or a system archive keyring -> SHA256 of the Packages index ->
SHA256 of each .deb. Every link is checked before a package is offered.
"""

import gzip
import hashlib
import lzma
import os
import re
import subprocess
import tempfile
import threading

from . import config, debver, net, query

FLAT_SUITES = ("./", "public")


class AptError(RuntimeError):
    pass


def _parse_stanzas(text):
    out, cur, last = [], {}, None
    for line in text.splitlines():
        if not line.strip():
            if cur:
                out.append(cur)
            cur, last = {}, None
            continue
        if line[0] in " \t" and last:
            cur[last] += "\n" + line.strip()
            continue
        key, _, value = line.partition(":")
        last = key.strip()
        cur[last] = value.strip()
    if cur:
        out.append(cur)
    return out


def _release_hashes(release_text):
    """Map path -> (sha256, size) from the SHA256 section of a Release file."""
    hashes, inside = {}, False
    for line in release_text.splitlines():
        if line.startswith("SHA256:"):
            inside = True
            continue
        if inside:
            if not line.startswith(" "):
                break
            digest, size, path = line.split()
            hashes[path] = (digest, int(size))
    return hashes


def _strip_clearsign(text):
    if "-----BEGIN PGP SIGNED MESSAGE-----" not in text:
        return text
    body = text.split("\n\n", 1)[1]
    return body.split("-----BEGIN PGP SIGNATURE-----", 1)[0]


class Keyring:
    """All keys in keys/ plus system archive keyrings, for gpgv."""

    SYSTEM = (
        "/usr/share/keyrings/ubuntu-archive-keyring.gpg",
        "/usr/share/keyrings/debian-archive-keyring.gpg",
    )

    def __init__(self, keys_dir):
        self.files = sorted(
            os.path.join(keys_dir, f) for f in os.listdir(keys_dir) if f.endswith(".gpg")
        ) if keys_dir and os.path.isdir(keys_dir) else []
        self.files += [k for k in self.SYSTEM if os.path.exists(k)]

    # OpenPGP hash algorithm IDs, for the clearsign "Hash:" header.
    HASH_NAMES = {"2": "SHA1", "8": "SHA256", "9": "SHA384", "10": "SHA512", "11": "SHA224"}

    def _gpgv(self, data, signature):
        with tempfile.TemporaryDirectory() as tmp:
            dpath = os.path.join(tmp, "data")
            with open(dpath, "wb") as f:
                f.write(data)
            # gpgv reads at most 40 keyring files and ignores the rest without
            # an error. Pass one keyring: the binary key files concatenated.
            kpath = os.path.join(tmp, "keyring.gpg")
            with open(kpath, "wb") as out:
                for k in self.files:
                    with open(k, "rb") as f:
                        out.write(f.read())
            cmd = ["gpgv", "--status-fd", "1", "--keyring", kpath]
            if signature is not None:
                spath = os.path.join(tmp, "sig")
                with open(spath, "wb") as f:
                    f.write(signature)
                cmd += [spath, dpath]
            else:
                cmd += [dpath]
            # NOTATION_DATA lines carry raw signature bytes: not always UTF-8.
            r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                               env={**os.environ, "LC_ALL": "C"})
            return [line.split()[1:] for line in r.stdout.splitlines() if line.startswith("[GNUPG:] ")]

    def verify(self, data, signature=None):
        """Accept as apt does: one valid signature from a trusted key, no bad one.

        A repository may sign with several keys (for example during a key
        rotation). A signature from a key that is not in the keyring is ignored.
        """
        if not net.have("gpgv"):
            raise AptError("gpgv is not installed")
        status = self._gpgv(data, signature)
        if signature is None:
            # Some repositories declare one hash in the clearsign header and sign
            # with another. The header is not signed: set it to the real one.
            for s in status:
                if s[0] == "ERRSIG" and len(s) > 3 and s[3] in self.HASH_NAMES:
                    fixed = re.sub(rb"^Hash: .*$", b"Hash: " + self.HASH_NAMES[s[3]].encode(),
                                   data, count=1, flags=re.M)
                    if fixed != data:
                        status = self._gpgv(fixed, None)
                    break
        kinds = {s[0] for s in status}
        return "VALIDSIG" in kinds and "BADSIG" not in kinds


class Repo:
    def __init__(self, url, suite, components, keyring, verify_signature=True):
        self.url = url.rstrip("/")
        self.suite = suite
        # As apt: a suite that ends in "/" is a flat repository below the URL.
        self.flat = suite in FLAT_SUITES or suite.endswith("/")
        self.components = list(dict.fromkeys(components)) or ([] if self.flat else ["main"])
        self.keyring = keyring
        self.verify_signature = verify_signature
        self.signature = "unchecked"
        self._release = None
        self.by_hash = False
        self._lock = threading.Lock()
        self._packages = {}        # arch -> stanzas
        self._arch_locks = {}

    def _base(self):
        if self.flat:
            return self.url if self.suite == "./" else f"{self.url}/{self.suite.rstrip('/')}"
        return f"{self.url}/dists/{self.suite}"

    def _get(self, path):
        return net.get_bytes(f"{self._base()}/{path}")

    def release(self):
        with self._lock:
            return self._release_locked()

    def _release_locked(self):
        if self._release is not None:
            return self._release
        text, ok = None, False
        try:
            raw = self._get("InRelease")
            ok = self.keyring.verify(raw)
            text = _strip_clearsign(raw.decode("utf-8", "replace"))
        except net.FetchError:
            pass
        if not ok:
            # No InRelease, or its signature does not verify (seen on
            # repos.azul.com): Release with a detached Release.gpg signs the
            # same content.
            try:
                raw = self._get("Release")
                text = raw.decode("utf-8", "replace")
                ok = self.keyring.verify(raw, self._get("Release.gpg"))
            except net.FetchError:
                if text is None:
                    raise
        self.signature = "verified" if ok else "failed"
        if not ok and self.verify_signature:
            raise AptError(f"signature check failed for {self._base()} (add the key to keys/)")
        self._release = _release_hashes(text)
        self.by_hash = bool(re.search(r"^Acquire-By-Hash:\s*yes\s*$", text, re.M | re.I))
        return self._release

    def packages(self, arch):
        """Stanzas for one architecture. Fetched and checked once per run."""
        with self._lock:
            lock = self._arch_locks.setdefault(arch, threading.Lock())
        with lock:
            if arch not in self._packages:
                self._packages[arch] = self._fetch_packages(arch)
            return self._packages[arch]

    def sources(self):
        """Source stanzas of all components. Fetched and checked once per run."""
        return self.packages("source")

    def _fetch_packages(self, arch):
        hashes = self.release()
        out = []
        comps = self.components or [""]
        for comp in comps:
            if arch == "source":
                stem = f"{comp}/source/Sources" if comp else "Sources"
            else:
                stem = f"{comp}/binary-{arch}/Packages" if comp else "Packages"
            for ext, unpack in ((".xz", lzma.decompress), (".gz", gzip.decompress), ("", lambda b: b)):
                if stem + ext not in hashes:
                    continue
                want, size = hashes[stem + ext]
                raw = self._index(stem, ext, want, size)
                for st in _parse_stanzas(unpack(raw).decode("utf-8", "replace")):
                    st["_component"] = comp
                    out.append(st)
                break
            else:
                # The component lists nothing for this architecture.
                continue
        return out

    def _index(self, stem, ext, want, size):
        """Fetch one index and check it against Release.

        With Acquire-By-Hash, take the index by its hash, as apt does: that
        path never changes, so it always matches the Release that named it.
        A CDN can serve a new Release with an old Packages for some minutes
        after the repository changes (seen on packages.microsoft.com).
        """
        paths = []
        if self.by_hash:
            paths.append(f"{os.path.dirname(stem)}/by-hash/SHA256/{want}")
        paths.append(stem + ext)
        last = None
        for path in paths:
            try:
                raw = self._get(path)
            except net.FetchError as e:
                last = e
                continue
            if hashlib.sha256(raw).hexdigest() == want and len(raw) == size:
                return raw
            last = AptError(f"{self._base()}/{path}: index hash does not match Release")
        raise last

    def pool_url(self, filename):
        return f"{self.url}/{filename}"


def source_files(stanza):
    """[(name, sha256, size)] of a Sources stanza (.dsc, tarballs)."""
    out = []
    for line in stanza.get("Checksums-Sha256", "").splitlines():
        parts = line.split()
        if len(parts) == 3:
            out.append((parts[2], parts[0], int(parts[1])))
    return out


def resolve_source(pkg, keyring):
    """Newest source package <packaging.package>, and its repository."""
    src = pkg["packaging"]
    repo = _repo(src["url"], src["suite"], src["components"], keyring, pkg["verify"]["signature"])
    stanzas = [s for s in repo.sources() if s.get("Package") == src["package"]]
    if not stanzas:
        raise AptError(f"source package {src['package']} not found in {src['url']} {src['suite']}")
    return max(stanzas, key=lambda s: debver.Version(s["Version"])), repo


def _dep_names(field):
    names = []
    for clause in field.split(","):
        first = clause.split("|")[0].strip()
        if first:
            names.append(first.split()[0].split(":")[0])
    return names


def select(stanzas, filter_text, arch, with_deps=False):
    """Apply the filter, add dependencies when asked, keep the newest per name."""
    pred = query.compile_query(filter_text)
    by_name = {}
    for st in stanzas:
        if st.get("Architecture") not in (arch, "all"):
            continue
        by_name.setdefault(st["Package"], []).append(st)

    chosen = {name for name, sts in by_name.items() if any(pred(s) for s in sts)}
    if with_deps:
        todo = list(chosen)
        while todo:
            name = todo.pop()
            for st in by_name.get(name, []):
                for dep in _dep_names(st.get("Depends", "") + "," + st.get("Pre-Depends", "")):
                    if dep in by_name and dep not in chosen:
                        chosen.add(dep)
                        todo.append(dep)

    result = []
    for name in sorted(chosen):
        # A matched name takes its newest matching version (the filter may cap
        # the version). A name added as a dependency takes its newest version.
        sts = [s for s in by_name[name] if pred(s)] or by_name[name]
        result.append(max(sts, key=lambda s: debver.Version(s["Version"])))
    return result


_repos = {}
_repos_lock = threading.Lock()


def _repo(url, suite, components, keyring, verify_signature):
    """One Repo per repository in a run: configs and releases share its indexes."""
    key = (url, suite, tuple(components), verify_signature)
    with _repos_lock:
        if key not in _repos:
            _repos[key] = Repo(url, suite, components, keyring, verify_signature)
        return _repos[key]


def resolve(pkg, release, arch, keyring):
    """Return candidate dicts for one package config, release and architecture."""
    src = pkg["source"]
    url = src["url"]
    with_deps = pkg.get("with_deps", not query.has_name_or_version(pkg["filter"]))
    # The old pipeline upgraded http to https. Keep that, with http as fallback.
    urls = [url]
    if url.startswith("http://"):
        urls.insert(0, "https://" + url[len("http://"):])
    for i, u in enumerate(urls):
        repo = _repo(u, src["suite"], src["components"], keyring, pkg["verify"]["signature"])
        try:
            stanzas = repo.packages(arch)
            break
        except net.FetchError:
            if i == len(urls) - 1:
                raise
    picked = select(stanzas, pkg["filter"], arch, with_deps)
    if not pkg.get("include_debug"):
        picked = [st for st in picked if not config.is_debug(st["Package"])]
    out = []
    for st in picked:
        out.append({
            "package": st["Package"],
            "version": st["Version"],
            "arch": st["Architecture"],
            "url": repo.pool_url(st["Filename"]),
            "filename": os.path.basename(st["Filename"]),
            "sha256": st.get("SHA256") if pkg["verify"]["checksums"] else None,
            "size": int(st["Size"]) if st.get("Size") else None,
            "signature": repo.signature,
        })
    return out
