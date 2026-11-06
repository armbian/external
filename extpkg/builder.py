"""Build one package for one release and architecture (method: build).

Runs as root in a container of the release (debian:<release>, ubuntu:<release>),
on a runner of the architecture. Steps:

1. Packaging: unpack the source package (hashes checked against the signed
   index), or take build/<name>/debian.
2. Upstream: fetch the planned commit of the tag or branch, rebase it when the config asks, and put
   the packaging on top.
3. Patches: build/<name>/patches/series, then patches/<release>/series,
   applied with patch -p1.
4. Changelog entry with the Armbian version.
5. build_depends: a local apt repository with the files that the Build
   workflow built for those configs in its first stage.
6. apt-get build-dep. upstream.meson_subprojects: download those meson wraps,
   because Debian packaging builds with --wrap-mode=nodownload.
7. dpkg-buildpackage.

Output: <out>/<config>/<release>/<arch>/*.deb and build.json.
"""

import email.utils
import fnmatch
import glob
import json
import os
import shutil
import subprocess

from . import config, net, source

MAINTAINER = "Armbian <info@armbian.com>"


class BuildError(RuntimeError):
    pass


def _run(cmd, cwd=None, env=None):
    net.log("$ " + " ".join(cmd))
    r = subprocess.run(cmd, cwd=cwd, env={**os.environ, **(env or {})})
    if r.returncode != 0:
        raise BuildError(f"{cmd[0]} failed (exit {r.returncode})")


def _git(*args, cwd=None):
    _run(["git", "-c", "advice.detachedHead=false", *args], cwd=cwd)


def _packaging(b, work):
    """Download and unpack the source package. Return the unpacked tree."""
    dl = os.path.join(work, "dl")
    os.makedirs(dl)
    for f in b["files"]:
        path = os.path.join(dl, f["name"])
        digest, size = net.download(f["url"], path)
        if digest != f["sha256"] or size != f["size"]:
            raise BuildError(f"{f['name']}: SHA256 or size does not match the signed index")
    dsc = next(f["name"] for f in b["files"] if f["name"].endswith(".dsc"))
    tree = os.path.join(work, "packaging")
    # The hashes are checked above against the signed Sources index.
    _run(["dpkg-source", "--no-check", "-x", os.path.join(dl, dsc), tree])
    return tree


def _upstream(up, tree):
    """Clone the upstream code into tree. Rebase it when the config asks."""
    if up.get("version_url"):
        os.makedirs(tree)
        return
    if up["rebase"]:
        _git("clone", "-q", "--filter=blob:none", "--branch", up["ref"], up["url"], tree)
        _git("checkout", "-q", up["commit"], cwd=tree)
        _git("fetch", "-q", "--filter=blob:none", up["rebase"]["url"], up["rebase"]["commit"], cwd=tree)
        _git("-c", "user.name=Armbian", "-c", "user.email=info@armbian.com", "rebase", "-q", "FETCH_HEAD", cwd=tree)
    else:
        # Fetch the planned commit: a branch can move during the run.
        os.makedirs(tree)
        _git("init", "-q", cwd=tree)
        # origin: relative submodule URLs resolve against it.
        _git("remote", "add", "origin", up["url"], cwd=tree)
        _git("fetch", "-q", "--depth", "1", "origin", up["commit"], cwd=tree)
        _git("checkout", "-q", "FETCH_HEAD", cwd=tree)
    if up.get("submodules"):
        # The superproject commit pins each submodule commit.
        _git("-c", "protocol.file.allow=always", "submodule", "update", "-q", "--init", "--recursive", cwd=tree)
        # Each submodule keeps a .git file that points into the removed .git.
        for root, _, files in os.walk(tree):
            if ".git" in files and root != tree:
                os.remove(os.path.join(root, ".git"))
    shutil.rmtree(os.path.join(tree, ".git"))


def _replace_debian(tree, debian):
    """Our packaging replaces a debian/ that upstream ships."""
    shutil.rmtree(os.path.join(tree, "debian"), ignore_errors=True)
    shutil.copytree(debian, os.path.join(tree, "debian"))


def _patches(pkg, packages_dir, tree, release):
    """Common patches, then the patches of this release."""
    root = os.path.join(source.local_dir(pkg, packages_dir), "patches")
    for series in (os.path.join(root, "series"), os.path.join(root, release, "series")):
        if not os.path.exists(series):
            continue
        with open(series) as f:
            names = [line.split("#")[0].strip() for line in f]
        for name in filter(None, names):
            _run(["patch", "-p1", "--forward", "--no-backup-if-mismatch", "-i",
                  os.path.join(os.path.dirname(series), name)], cwd=tree)


def _changelog(tree, b, release):
    path = os.path.join(tree, "debian", "changelog")
    with open(os.path.join(tree, "debian", "control")) as f:
        name = next(line.split(":", 1)[1].strip() for line in f if line.startswith("Source:"))
    old = open(path).read() if os.path.exists(path) else ""
    what = []
    if b["upstream"]:
        up = b["upstream"]
        what.append(f"upstream {up['url']} {up['ref']} {up['commit'][:12]}".rstrip())
        if up["rebase"]:
            what.append(f"rebased onto {up['rebase']['url']} {up['rebase']['ref']} {up['rebase']['commit'][:12]}")
    if b["packaged"]:
        what.append(f"packaging {b['packaged']}")
    entry = (f"{name} ({b['version']}) {release}; urgency=medium\n\n"
             f"  * Armbian build: {', '.join(what) or 'local packaging'}.\n\n"
             f" -- {MAINTAINER}  {email.utils.formatdate(usegmt=False)}\n\n")
    with open(path, "w") as f:
        f.write(entry + old)


def _deps_repo(pkg, release, arch, deps, work):
    """Local apt repository with the build outputs of build_depends. Its versions win."""
    names = pkg.get("build_depends", [])
    if not names:
        return
    repo = os.path.join(work, "deps")
    os.makedirs(repo)
    for name in names:
        found = glob.glob(os.path.join(deps or "", name, release, arch, "*.deb"))
        # _all.deb files come from the first architecture of that build.
        found += [p for p in glob.glob(os.path.join(deps or "", name, release, "*", "*_all.deb"))
                  if os.path.basename(p) not in {os.path.basename(f) for f in found}]
        if not found:
            net.log(f"build_depends {name}: no build for {release}/{arch}, the release has its own")
            continue
        for path in found:
            shutil.copy2(path, repo)
    if not os.listdir(repo):
        return
    with open(os.path.join(repo, "Packages"), "w") as f:
        subprocess.run(["dpkg-scanpackages", "-m", "."], cwd=repo, stdout=f, check=True)
    with open("/etc/apt/sources.list.d/extpkg-deps.list", "w") as f:
        f.write(f"deb [trusted=yes] file:{repo} ./\n")
    with open("/etc/apt/preferences.d/extpkg-deps", "w") as f:
        f.write("Package: *\nPin: origin \"\"\nPin-Priority: 1001\n")
    _run(["apt-get", "update", "-qq"])


def _wraps(tree, patterns):
    """Wrap names in subprojects/ that match the patterns (globs, for example *-rs)."""
    names = sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(tree, "subprojects", "*.wrap")))
    out = [n for n in names if any(fnmatch.fnmatchcase(n, p) for p in patterns)]
    missing = [p for p in patterns if not any(fnmatch.fnmatchcase(n, p) for n in names)]
    if missing:
        raise BuildError(f"meson_subprojects: no wrap matches {missing}")
    return out


def _has_arch_any(tree):
    with open(os.path.join(tree, "debian", "control")) as f:
        archs = [line.split(":", 1)[1].split() for line in f if line.startswith("Architecture:")]
    return any(a != ["all"] for a in archs)


def build(plan_doc, pkgs, packages_dir, name, release, arch, out, jobs=None, deps=None):
    pkg = next((p for p in pkgs if p["name"] == name), None)
    entry = next((e for e in plan_doc["entries"]
                  if e["config"] == name and e["release"] == release and e["arch"] == arch), None)
    if not pkg or not entry or not entry.get("candidates"):
        raise BuildError(f"{name} {release}/{arch}: not in the plan ({entry and entry.get('skip')})")
    cand = entry["candidates"][0]
    b = cand["build"]
    # apt takes only absolute file: paths (local repository of build_depends).
    out, deps = os.path.abspath(out), deps and os.path.abspath(deps)
    dest = os.path.join(out, name, release, arch)
    work = os.path.join(out, ".work", name, release, arch)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)

    tree = os.path.join(work, "src")
    if b["files"]:
        packaging = _packaging(b, work)
        if b["upstream"]:
            _upstream(b["upstream"], tree)
            _replace_debian(tree, os.path.join(packaging, "debian"))
        else:
            os.rename(packaging, tree)
    else:
        _upstream(b["upstream"], tree)
        _replace_debian(tree, os.path.join(source.local_dir(pkg, packages_dir), "debian"))
    _patches(pkg, packages_dir, tree, release)
    _changelog(tree, b, release)

    # Architecture-independent packages come from the first architecture only:
    # two builds of one _all.deb differ, and one repository pool holds both.
    first = next(a for a in pkg["architectures"] if f"{release}/{a}" not in pkg.get("skip", []))
    files = []
    if arch == first or _has_arch_any(tree):
        mode = "-b" if arch == first else "-B"
        env = {"DEBIAN_FRONTEND": "noninteractive",
               "DEB_BUILD_OPTIONS": f"nocheck parallel={jobs or os.cpu_count()}"
                                    + ("" if pkg.get("include_debug") else " noautodbgsym noddebs")}
        _deps_repo(pkg, release, arch, deps, work)
        _run(["apt-get", "-y", "--no-install-recommends", "build-dep", "./"] + (["--arch-only"] if mode == "-B" else []),
             cwd=tree, env=env)
        subprojects = _wraps(tree, (b["upstream"] or {}).get("meson_subprojects") or [])
        if subprojects:
            _run(["meson", "subprojects", "download", *subprojects], cwd=tree)
        _run(["dpkg-buildpackage", mode, "-uc", "-us"], cwd=tree, env=env)
        os.makedirs(dest, exist_ok=True)
        for path in sorted(glob.glob(os.path.join(work, "*.deb"))):
            if config.is_debug(os.path.basename(path).split("_")[0]) and not pkg.get("include_debug"):
                continue
            shutil.move(path, os.path.join(dest, os.path.basename(path)))
            files.append(os.path.basename(path))
        if not files:
            raise BuildError("the build made no .deb files")
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, "build.json"), "w") as f:
        json.dump({"identity": cand["identity"], "version": b["version"], "files": files}, f, indent=1)
    shutil.rmtree(work, ignore_errors=True)
    net.log(f"build: {name} {release}/{arch} {b['version']}: {len(files)} files")
    return files
