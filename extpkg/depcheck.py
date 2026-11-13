"""Dependency check: can apt install our new packages on each release?

Nothing is installed and nothing runs on the target architecture: apt
resolves the dependencies with --simulate, for any architecture, on one
host. Per release and architecture:

- a temporary apt root (no root access, the host apt is not touched);
- sources: the distribution, the Armbian repository, and a local
  repository with our new files;
- apt-get install --simulate <package>=<our version>, per config.

The index lists live in a cache directory, so apt update only checks for
changes on the next run.
"""

import concurrent.futures as cf
import glob
import os
import shutil
import subprocess
import tempfile
import threading

from . import net

DEBIAN = "http://deb.debian.org/debian"
DEBIAN_SECURITY = "http://security.debian.org/debian-security"
UBUNTU = "http://archive.ubuntu.com/ubuntu"
UBUNTU_PORTS = "http://ports.ubuntu.com/ubuntu-ports"
ARMBIAN = "https://apt.armbian.com"
KEYRINGS = ("/usr/share/keyrings/debian-archive-keyring.gpg",
            "/usr/share/keyrings/ubuntu-archive-keyring.gpg")


def distro_of(release, build_dir):
    """'debian' or 'ubuntu', from armbian/build config/distributions/<release>/name."""
    if build_dir:
        path = os.path.join(build_dir, "config/distributions", release, "name")
        if os.path.exists(path):
            with open(path) as f:
                return "ubuntu" if f.read().lower().startswith("ubuntu") else "debian"
    return "debian" if release in ("bookworm", "trixie", "forky", "sid") else "ubuntu"


def _suite_exists(base, suite):
    try:
        net.get_bytes(f"{base}/dists/{suite}/InRelease")
        return True
    except net.FetchError:
        return False


def _sources(release, arch, distro):
    lines = []
    if distro == "debian":
        comps = "main contrib non-free non-free-firmware"
        lines.append(f"deb {DEBIAN} {release} {comps}")
        if release != "sid" and _suite_exists(DEBIAN, f"{release}-updates"):
            lines.append(f"deb {DEBIAN} {release}-updates {comps}")
        if release != "sid" and _suite_exists(DEBIAN_SECURITY, f"{release}-security"):
            lines.append(f"deb {DEBIAN_SECURITY} {release}-security {comps}")
    else:
        base = UBUNTU if arch in ("amd64", "i386") else UBUNTU_PORTS
        comps = "main restricted universe multiverse"
        lines.append(f"deb {base} {release} {comps}")
        if _suite_exists(base, f"{release}-updates"):
            lines.append(f"deb {base} {release}-updates {comps}")
    lines.append(f"deb {ARMBIAN} {release} main {release}-utils {release}-desktop")
    return lines


def _write_local_repo(repo_dir, debs):
    """Flat repository: Packages built from the control files."""
    stanzas = []
    for path in debs:
        r = subprocess.run(["dpkg-deb", "-f", path], capture_output=True, text=True, check=True)
        ctrl = r.stdout.rstrip("\n")
        rel = os.path.relpath(path, repo_dir)
        stanzas.append(f"{ctrl}\nFilename: ./{rel}\nSize: {os.path.getsize(path)}\n"
                       f"SHA256: {net.sha256_file(path)}\n")
    with open(os.path.join(repo_dir, "Packages"), "w") as f:
        f.write("\n".join(stanzas))


class AptRoot:
    """apt for one release and architecture, with a local repository that grows."""

    def __init__(self, release, arch, distro, lists_dir, keyrings):
        self.tmp = tempfile.mkdtemp(prefix=f"depcheck-{release}-{arch}-")
        self.local = os.path.join(self.tmp, "repo")
        os.makedirs(lists_dir + "/partial", exist_ok=True)
        for d in ("etc/apt/trusted.gpg.d", "etc/apt/preferences.d", "etc/apt/apt.conf.d",
                  "var/cache/apt/archives/partial", "var/lib/dpkg", "repo"):
            os.makedirs(os.path.join(self.tmp, d), exist_ok=True)
        open(os.path.join(self.tmp, "var/lib/dpkg/status"), "w").close()
        open(os.path.join(self.local, "Packages"), "w").close()
        for k in keyrings:
            shutil.copy(k, os.path.join(self.tmp, "etc/apt/trusted.gpg.d", os.path.basename(k)))
        self.local_list = os.path.join(self.tmp, "etc/apt/local.list")
        with open(self.local_list, "w") as f:
            f.write(f"deb [trusted=yes] file:{self.local} ./\n")
        with open(os.path.join(self.tmp, "etc/apt/sources.list"), "w") as f:
            f.write("\n".join(_sources(release, arch, distro) + [f"deb [trusted=yes] file:{self.local} ./"]) + "\n")
        # Our new files win over the same package in the other sources.
        with open(os.path.join(self.tmp, "etc/apt/preferences.d/local"), "w") as f:
            f.write('Package: *\nPin: origin ""\nPin-Priority: 1001\n')
        # APT_CONFIG: read this file only, not the host /etc/apt/apt.conf.d
        # (there apt-file, for example, turns on the large Contents indexes).
        self.conf = os.path.join(self.tmp, "apt.conf")
        with open(self.conf, "w") as f:
            f.write(f'Dir "{self.tmp}/";\nDir::Etc::Parts "{self.tmp}/etc/apt/apt.conf.d";\n')
        self.opts = [
            "-o", f"Dir={self.tmp}",
            "-o", f"Dir::State::Lists={lists_dir}",
            "-o", f"Dir::State::status={self.tmp}/var/lib/dpkg/status",
            "-o", f"APT::Architecture={arch}",
            "-o", f"APT::Architectures={arch}",
            "-o", "Debug::NoLocking=1",
            "-o", "Acquire::Languages=none",
            "-o", "Acquire::GzipIndexes=true",
            "-o", "APT::Get::List-Cleanup=false",
            "-o", "APT::Install-Recommends=false",
            "-o", "APT::Sandbox::User=",
        ]
        self.debs = []

    def apt(self, *args, opts=()):
        return subprocess.run(["apt-get", "-q", *self.opts, *opts, *args], capture_output=True, text=True,
                              env={**os.environ, "LC_ALL": "C", "APT_CONFIG": self.conf})

    def update(self):
        """Distribution and Armbian indexes: the slow part, run early."""
        # Fail on any index error: else apt returns 0 and empty indexes make every dependency fail.
        return self.apt("update", "--error-on=any")

    def add(self, paths):
        """Add .deb files to the local repository and refresh only that source."""
        for src in paths:
            dst = os.path.join(self.local, os.path.basename(src))
            if not os.path.exists(dst):
                try:
                    os.link(src, dst)
                except OSError:
                    shutil.copy(src, dst)
                self.debs.append(dst)
        _write_local_repo(self.local, self.debs)
        return self.apt("update", opts=("-o", f"Dir::Etc::SourceList={self.local_list}",
                                        "-o", "Dir::Etc::SourceParts=-"))

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


def _targets(files, install):
    """package=version to install: the config's install list, else every package."""
    names = {x["package"] for x in files}
    want = [n for n in install if n in names] or sorted(names)
    best = {}
    for x in files:
        if x["package"] in want:
            best[x["package"]] = x["version"]
    return [f"{p}={v}" for p, v in sorted(best.items())]


def _why(r):
    """The cause first: dependencies that no source has."""
    lines = [line.strip() for line in (r.stdout + r.stderr).splitlines() if line.strip()]
    lines = [line for line in lines if not line.startswith("NOTE:")]
    cause = [line for line in lines if "not installable" in line or "no installation candidate" in line
             or "has no installation candidate" in line or "Unable to locate" in line]
    rest = [line for line in lines if line.startswith("E:")]
    return " ; ".join(cause + rest or lines[-3:])[:600]


class Checker:
    """prepare() starts apt update for every release and architecture at once.
    submit() checks one config, release and architecture.
    """

    def __init__(self, pkgs, out, build_dir, lists_cache, keys_dir, extra_keyrings=(), jobs=4):
        self.install = {p["name"]: p.get("install", []) for p in pkgs}
        self.out, self.build_dir, self.lists_cache = out, build_dir, lists_cache
        self.keyrings = [k for k in KEYRINGS if os.path.exists(k)] + list(extra_keyrings)
        self.keyrings += sorted(glob.glob(os.path.join(keys_dir, "armbian*.gpg")))
        self.pool = cf.ThreadPoolExecutor(jobs)
        self.roots, self.ready, self.locks = {}, {}, {}
        self.futures, self.results = [], []
        self._lock = threading.Lock()

    def prepare(self, pairs):
        for release, arch in sorted(set(pairs)):
            root = AptRoot(release, arch, distro_of(release, self.build_dir),
                           os.path.join(self.lists_cache, f"{release}-{arch}"), self.keyrings)
            self.roots[(release, arch)] = root
            self.locks[(release, arch)] = threading.Lock()
            self.ready[(release, arch)] = self.pool.submit(root.update)
        net.log(f"depcheck: indexes for {len(self.roots)} release/arch pairs started")

    def submit(self, config, release, arch, files):
        """files: manifest entries of one config, release and architecture."""
        if (release, arch) in self.roots and files:
            self.futures.append(self.pool.submit(self._check, config, release, arch, files))

    def _check(self, config, release, arch, files):
        key = (release, arch)
        res = {"config": config, "release": release, "arch": arch, "ok": None, "packages": [], "message": ""}
        try:
            up = self.ready[key].result()
            if up.returncode != 0:
                res["message"] = "apt update failed: " + " ; ".join((up.stderr or up.stdout).strip().splitlines()[-3:])
            else:
                with self.locks[key]:
                    root = self.roots[key]
                    r = root.add([os.path.join(self.out, x["beta"] or x["stable"]) for x in files
                                  if x["beta"] or x["stable"]])
                    if r.returncode != 0:
                        res["message"] = "local repository: " + (r.stderr or r.stdout).strip()[-300:]
                    else:
                        res["packages"] = _targets(files, self.install.get(config, []))
                        r = root.apt("install", "--simulate", *res["packages"])
                        res["ok"] = r.returncode == 0
                        res["message"] = "" if res["ok"] else _why(r)
        except Exception as e:
            res["message"] = f"{type(e).__name__}: {e}"
        state = {True: "ok", False: "FAILED", None: "not checked"}[res["ok"]]
        net.log(f"depcheck {config} {release}/{arch}: {state}{(' - ' + res['message'][:200]) if res['message'] else ''}")
        with self._lock:
            self.results.append(res)

    def finish(self):
        for f in self.futures:
            f.result()
        self.pool.shutdown(wait=True)
        for root in self.roots.values():
            root.close()
        failed = sum(1 for x in self.results if x["ok"] is False)
        net.log(f"depcheck: {len(self.results)} checks, {failed} failed")
        return sorted(self.results, key=lambda x: (x["config"], x["release"], x["arch"]))


def check(manifest, out, pkgs, build_dir, lists_cache, keys_dir, jobs=4, extra_keyrings=()):
    """Check the new files of a finished output tree (no download running)."""
    skip = {p["name"] for p in pkgs if p.get("depcheck") is False}
    new = [x for x in manifest["files"] if not x.get("carried") and not x.get("unchanged")
           and x["config"] not in skip]
    groups = {}
    for x in new:
        groups.setdefault((x["config"], x["release"], x["arch"]), []).append(x)
    c = Checker(pkgs, out, build_dir, lists_cache, keys_dir, extra_keyrings, jobs)
    c.prepare({(r, a) for _, r, a in groups})
    for (cfg, rel, arch), files in sorted(groups.items()):
        c.submit(cfg, rel, arch, files)
    return c.finish()


def report(results):
    if not results:
        return ""
    failed = [x for x in results if x["ok"] is False]
    unknown = [x for x in results if x["ok"] is None]
    lines = ["", f"#### Dependency check: {len(results)} checks, {len(failed)} failed"
             + (f", {len(unknown)} not checked" if unknown else "")]
    if failed or unknown:
        lines += ["", "| config | release | arch | result |", "|---|---|---|---|"]
        for x in failed + unknown:
            lines.append(f"| {x['config']} | {x['release']} | {x['arch']} | {x['message'][:300]} |")
    return "\n".join(lines)
