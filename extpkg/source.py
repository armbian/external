"""Resolve source builds (method: build).

A build takes:
  packaging  debian/ from a Debian or Ubuntu source package,
             or build/<name>/debian when the config has no packaging
  upstream   optional: code in place of the packaged code (a tag or a branch),
             optionally rebased onto another branch (a fork)
  patches    optional: build/<name>/patches/series

The plan resolves these and gives the build an identity. The build runs later,
in a container of the release (extpkg/builder.py).
"""

import datetime
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading

from . import apt, debver, github, net

# Bump when the build steps change: every package builds again.
RECIPE = 1

_cache = {}
_lock = threading.Lock()


def local_dir(pkg, packages_dir):
    """build/<name>/: patches/, and debian/ when the config has no packaging."""
    return os.path.join(packages_dir, pkg["name"])


def local_hash(pkg, packages_dir):
    """SHA256 of every file under build/<name>/, or "" when there is none."""
    root = local_dir(pkg, packages_dir)
    h = hashlib.sha256()
    found = False
    for d, dirs, names in os.walk(root):
        dirs.sort()
        for n in sorted(names):
            path = os.path.join(d, n)
            h.update(os.path.relpath(path, root).encode() + b"\0")
            with open(path, "rb") as f:
                h.update(f.read())
            found = True
    return h.hexdigest() if found else ""


def tag_version(tag):
    """v2.70.0 -> 2.70.0, mesa-26.0.1 -> 26.0.1, 1.0-rc1 -> 1.0~rc1."""
    m = re.search(r"\d.*", tag)
    if not m:
        raise ValueError(f"no version in tag {tag!r}: set upstream.version")
    return m.group(0).replace("-rc", "~rc")


def _git(*args, cwd=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise net.FetchError(f"git {args[0]}: {r.stderr.strip()[-300:]}")
    return r.stdout


def _ref(url, ref):
    """(commit, 'tag' or 'branch'). A tag gives the commit it points to."""
    out = _git("ls-remote", url, f"refs/tags/{ref}", f"refs/tags/{ref}^{{}}", f"refs/heads/{ref}")
    refs = {name: sha for sha, name in (line.split("\t", 1) for line in out.splitlines() if "\t" in line)}
    for name in (f"refs/tags/{ref}^{{}}", f"refs/tags/{ref}"):
        if name in refs:
            return refs[name], "tag"
    if f"refs/heads/{ref}" in refs:
        return refs[f"refs/heads/{ref}"], "branch"
    raise net.FetchError(f"{url}: no tag or branch {ref!r}")


def latest_tag(url, pattern="*"):
    """Newest release tag that matches pattern. Pre-releases (rc, alpha, beta) are left out."""
    out = _git("ls-remote", "--tags", "--refs", url)
    best = None
    for line in out.splitlines():
        tag = line.split("\t", 1)[1][len("refs/tags/"):]
        if not fnmatch.fnmatchcase(tag, pattern):
            continue
        try:
            ver = tag_version(tag)
        except ValueError:
            continue
        if "~" in ver or re.search(r"(alpha|beta|rc|devel|branchpoint)", ver, re.I) or not re.match(r"^[0-9][0-9.]*$", ver):
            continue
        if best is None or debver.compare(ver, best[1]) > 0:
            best = (tag, ver)
    if not best:
        raise net.FetchError(f"{url}: no release tag matches {pattern!r}")
    return best[0]


def _read_file(url, ref, path):
    """One file of a branch, without a full clone."""
    with tempfile.TemporaryDirectory() as tmp:
        _git("clone", "-q", "--depth", "1", "--filter=blob:none", "--no-checkout", "--branch", ref, url, tmp)
        return _git("show", f"HEAD:{path}", cwd=tmp).strip()


def file_version(text):
    """27.0.0-devel -> 27.0.0, 26.3.0-rc1 -> 26.3.0~rc1."""
    return text.split()[0].replace("-devel", "").replace("-rc", "~rc")


def _commit_time(url, commit):
    """Commit time, from a fetch of that one commit without file contents."""
    with tempfile.TemporaryDirectory() as tmp:
        _git("init", "-q", tmp)
        _git("fetch", "-q", "--depth", "1", "--filter=blob:none", url, commit, cwd=tmp)
        return int(_git("log", "-1", "--format=%ct", "FETCH_HEAD", cwd=tmp).strip())


def _once(key, fn):
    with _lock:
        lock = _cache.setdefault(("lock", key), threading.Lock())
    with lock:
        if key not in _cache:
            _cache[key] = fn()
        return _cache[key]


def upstream(up):
    """{url, ref, commit, version, rebase} of the upstream code. Once per run.

    ref latest: the latest GitHub release, or on other hosts the newest
    release tag that matches upstream.tags (default *).

    A tag gives the version (v2.70.0 -> 2.70.0). A branch needs
    upstream.version, the next upstream release, or upstream.version_file, a
    file that holds it (mesa: VERSION). The snapshot then sorts below that
    release: <version>~git<YYYYMMDDHHMM>.<commit>.
    """
    def go():
        ref = up.get("ref", "latest")
        if ref == "latest":
            if "github.com/" in up["url"] and not up.get("tags"):
                ref = github.release(up["url"])["tag_name"]
            else:
                ref = latest_tag(up["url"], up.get("tags", "*"))
        commit, kind = _ref(up["url"], ref)
        rebase = None
        if up.get("rebase"):
            base_commit, _ = _ref(up["rebase"]["url"], up["rebase"]["ref"])
            rebase = {**up["rebase"], "commit": base_commit}
        version = up.get("version")
        if not version and up.get("version_file"):
            # The rebase base sets the version: the code is that branch plus the fork.
            src = rebase or {"url": up["url"], "ref": ref}
            version = file_version(_read_file(src["url"], src["ref"], up["version_file"]))
        if kind == "tag" and not rebase:
            ver = version or tag_version(ref)
        else:
            if not version:
                raise ValueError(f"{up['url']} {ref}: a branch or a rebase needs upstream.version or version_file")
            t = _commit_time(up["url"], commit)
            if rebase:
                t = max(t, _commit_time(rebase["url"], rebase["commit"]))
            stamp = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y%m%d%H%M")
            ver = f"{version}~git{stamp}.{commit[:10]}"
        return {"url": up["url"], "ref": ref, "commit": commit, "version": ver, "rebase": rebase,
                "meson_subprojects": up.get("meson_subprojects", [])}

    key = (up["url"], up.get("ref", "latest"), up.get("tags"), up.get("version"), up.get("version_file"),
           repr(up.get("rebase")), repr(up.get("meson_subprojects")))
    return _once(key, go)


def version(pkg, release, packaged=None, up=None):
    """Version of the built packages.

    packaging only:          <packaged version>+armbian<revision>~<release>
    upstream code:           <upstream version>-<packaged revision or 0>+armbian<revision>~<release>
    The release suffix gives each release its own file name: one repository
    pool holds all releases.
    """
    rev = pkg.get("revision", 1)
    if up:
        epoch, _, debrev = debver.split(packaged) if packaged else (0, "", "")
        base = (f"{epoch}:" if epoch else "") + f"{up['version']}-{debrev or '0'}"
    else:
        base = packaged
    return f"{base}+armbian{rev}~{release}"


def resolve(pkg, release, arch, keyring, packages_dir):
    """One candidate: the whole build for one release and architecture."""
    files, packaged, signature, dsc = [], None, "none", None
    if pkg.get("packaging"):
        st, repo = apt.resolve_source(pkg, keyring)
        packaged, signature = st["Version"], repo.signature
        for name, sha, size in apt.source_files(st):
            files.append({"name": name, "url": f"{repo.url}/{st['Directory']}/{name}", "sha256": sha, "size": size})
        dsc = next((f for f in files if f["name"].endswith(".dsc")), None)
        if not dsc:
            raise apt.AptError(f"source package {st['Package']} {packaged} has no .dsc")
    up = upstream(pkg["upstream"]) if pkg.get("upstream") else None
    ver = version(pkg, release, packaged, up)
    local = local_hash(pkg, packages_dir)
    # Config keys that change the build. releases, notes, install and the like do not.
    keys = {k: pkg.get(k) for k in ("packaging", "upstream", "revision", "build_depends", "include_debug")}
    local = hashlib.sha256((local + json.dumps(keys, sort_keys=True)).encode()).hexdigest()
    commits = [up["commit"][:12], up["rebase"]["commit"][:12] if up["rebase"] else ""] if up else []
    identity = "|".join([f"build{RECIPE}", dsc["sha256"][:16] if dsc else "-",
                         "+".join(c for c in commits if c) or "-", local[:16], ver])
    return [{
        "package": None,
        "version": None,          # read from each built .deb
        "arch": arch,
        "url": dsc["url"] if dsc else f"{up['url']}#{up['ref']}",
        "filename": dsc["name"] if dsc else pkg["name"],
        "sha256": None,
        "size": None,
        "signature": signature,
        "identity": identity,
        "build": {"files": files, "packaged": packaged, "upstream": up, "version": ver},
    }]
