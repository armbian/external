"""Plan and fetch external packages into the incoming/external layout.

Output tree (unchanged from the old download workflow):

    <out>/debs-beta/<dir>/<file>.deb   every package (beta repository)
    <out>/debs/<dir>/<file>.deb        only when newer than the published stable version
    <out>/manifest.json                one entry per placed file

<dir> is "extra/<release>-<target>", or empty for target "main".
"""

import concurrent.futures as cf
import datetime
import hashlib
import json
import os
import shutil
import threading

from . import apt, config, debfile, debver, github, net, published, retention, url

class SkipDebug(Exception):
    """A debug package from a source that cannot filter before download."""


RESOLVERS = {"apt": apt.resolve, "github": github.resolve, "url": url.resolve}
TOOL = "armbian-external/1"


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


# --- plan ----------------------------------------------------------------------

def plan(pkgs, releases_all, keys_dir, jobs=8, shard=None, full=False):
    """Resolve every (package, release, arch) to candidate files. No .deb download.

    full: the run covers every config of its shard (no --only). Retention then
    also removes the files of configs that were deleted.
    """
    keyring = apt.Keyring(keys_dir)
    work, covered = [], []
    for pkg in pkgs:
        if shard and _shard_of(pkg["name"], shard[1]) != shard[0]:
            continue
        covered.append(pkg["name"])   # disabled too: its old files go
        if not pkg["enabled"]:
            continue
        for rel, arch in config.expand(pkg, releases_all):
            work.append((pkg, rel, arch))

    prog = net.Progress("plan", len(work))

    def one(item):
        pkg, rel, arch = item
        entry = {"config": pkg["name"], "method": pkg["method"], "release": rel, "arch": arch,
                 "target": pkg["target"], "dir": config.component_dir(pkg, rel)}
        try:
            cands = RESOLVERS[pkg["method"]](pkg, rel, arch, keyring)
            if not cands:
                entry["skip"] = "no package matched"
            entry["candidates"] = cands
        except Exception as e:  # one broken upstream must not stop the run
            entry["skip"] = f"{type(e).__name__}: {e}"
            entry["candidates"] = []
        where = f"{pkg['name']} {rel}/{arch}"
        if entry.get("skip"):
            prog.step(f"{where}: SKIP {entry['skip'][:160]}")
        else:
            c = entry["candidates"]
            first = c[0]["package"] and f"{c[0]['package']} {c[0]['version']}" or c[0]["filename"]
            prog.step(f"{where}: {len(c)} file{'s' if len(c) != 1 else ''} ({first})")
        return entry

    with cf.ThreadPoolExecutor(jobs) as ex:
        entries = list(ex.map(one, work))
    files = sum(len(e["candidates"]) for e in entries)
    prog.done(f"{files} files, {sum(1 for e in entries if e.get('skip'))} skipped")
    return {"generated": _now(), "tool": TOOL, "releases": releases_all, "entries": entries,
            "covered": covered, "shard": list(shard) if shard else None, "full": full}


def _shard_of(name, count):
    return int(hashlib.sha1(name.encode()).hexdigest(), 16) % count


# --- fetch ---------------------------------------------------------------------

class Fetcher:
    def __init__(self, pkgs, out, cache, pub):
        self.pkgs = {p["name"]: p for p in pkgs}
        self.out = out
        self.cache = cache
        self.pub = pub
        self._locks = {}
        self._guard = threading.Lock()
        self.files = []
        self.skipped = []
        self._placed = {}
        self.progress = None
        self.bytes = 0
        self.used = set()   # cache paths this run used
        self.previous = {}  # (config, release, arch, source, sha256) -> manifest entry
        self.unchanged = 0
        self.sink = None    # called with [(path, size)] after each upstream file
        self.stop = None    # returns True to stop early (upload failed)

    def _lock(self, key):
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    def _download(self, cand):
        """Download once per URL into the cache. Verify size and SHA256."""
        key = hashlib.sha256(cand["url"].encode()).hexdigest()[:24]
        d = os.path.join(self.cache, key)
        path = os.path.join(d, cand["filename"])
        with self._guard:
            self.used.add(path)
        with self._lock(key):
            cand["_cached"] = os.path.exists(path)
            if not os.path.exists(path):
                os.makedirs(d, exist_ok=True)
                digest, size = net.download(cand["url"], path,
                                            net.github_headers() if "github.com" in cand["url"] else None)
                if cand.get("size") and size != cand["size"]:
                    os.unlink(path)
                    raise net.FetchError(f"{cand['filename']}: size {size}, index says {cand['size']}")
                if cand.get("sha256") and digest != cand["sha256"]:
                    os.unlink(path)
                    raise net.FetchError(f"{cand['filename']}: SHA256 does not match the source")
                with self._guard:
                    self.bytes += size
        return path

    def _place(self, src, repo, subdir, name):
        rel = os.path.join(repo, subdir, name) if subdir else os.path.join(repo, name)
        digest = net.sha256_file(src)
        # An _all.deb lands in one directory from several architectures.
        # Hold the path until the file is in place.
        with self._lock("place:" + rel):
            seen = self._placed.get(rel)
            if seen and seen != digest:
                raise RuntimeError(f"{rel}: two different files with one name")
            if seen:
                return rel, digest, False
            dest = os.path.join(self.out, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            try:
                os.link(src, dest)
            except OSError:
                shutil.copy2(src, dest)
            self._placed[rel] = digest
        return rel, digest, True

    def group(self, items):
        """All uses of one upstream file: download once, place every path.

        Then hand the new paths to the sink (the upload queue) together, so a
        file and its hardlinks go in one upload batch.
        """
        new_paths = []
        for entry, cand in items:
            new_paths += self._one_use(entry, cand)
        if new_paths and self.sink:
            self.sink(new_paths)

    def _one_use(self, entry, cand):
        pkg = self.pkgs[entry["config"]]
        base = {k: entry[k] for k in ("config", "release", "arch", "target")}
        where = f"{entry['config']} {entry['release']}/{entry['arch']}"
        if self.stop and self.stop():
            self.skipped.append({**base, "file": cand["filename"], "reason": "stopped: upload failed"})
            return []
        ident = cand.get("sha256") or cand.get("identity")
        prev = ident and self.previous.get((entry["config"], entry["release"], entry["arch"], cand["url"], ident))
        if prev:
            # Uploaded by an earlier run, and the server keeps it.
            with self._guard:
                rec = {k: v for k, v in prev.items() if k != "carried"}
                self.files.append({**rec, "unchanged": True})
                self.unchanged += 1
            self.progress.step(f"{where}: unchanged {prev['filename']}")
            return []
        try:
            x, created = self._one_file(pkg, entry, cand, base)
            check = ("sig+sha" if x["signature"] == "verified" else "sha") if x["checksum"] == "verified" \
                else ("sig" if x["signature"] == "verified" else "unverified")
            how = "cached" if cand.get("_cached") else "downloaded"
            size = net.human(x["size"])
            dest = f"stable+beta (published {x['published'] or 'none'})" if x["stable"] else "beta only"
            self.progress.step(f"{where}: {how} {x['filename']} {size} {check} -> {dest}")
            return [(p, x["size"]) for p in created]
        except SkipDebug as e:
            self.progress.step(f"{where}: debug package {e} not mirrored")
            return []
        except Exception as e:
            self.skipped.append({**base, "file": cand["filename"], "reason": f"{type(e).__name__}: {e}"})
            self.progress.step(f"{where}: FAILED {cand['filename']}: {type(e).__name__}: {e}")
            return []

    def _one_file(self, pkg, entry, cand, base):
        path = self._download(cand)
        fields = debfile.control(path)
        if fields["Architecture"] not in (entry["arch"], "all"):
            net.warn(f"{cand['filename']}: Architecture {fields['Architecture']}, wanted {entry['arch']}")
        if config.is_debug(fields["Package"]) and not pkg.get("include_debug"):
            raise SkipDebug(fields["Package"])
        if cand.get("version") and fields["Version"] != cand["version"]:
            raise debfile.DebError(f"{cand['filename']}: Version {fields['Version']}, index says {cand['version']}")

        name, version = cand["filename"], fields["Version"]
        rp = pkg.get("repack")
        if rp and fields["Package"] in rp["packages"]:
            new_version = debfile.repack_version(version, rp.get("epoch"), rp.get("suffix", ""))
            rdir = os.path.join(self.cache, "repack", entry["release"], entry["arch"])
            os.makedirs(rdir, exist_ok=True)
            with self._lock("repack:" + path):
                path = debfile.repack(path, new_version, rdir)
            with self._guard:
                self.used.add(path)
            name, version = os.path.basename(path), new_version

        have = self.pub.version(entry["release"], entry["target"], entry["arch"], fields["Package"])
        newer = have is None or debver.compare(version, have) > 0

        created = []
        beta_rel, digest, made = self._place(path, "debs-beta", entry["dir"], name)
        if made:
            created.append(beta_rel)
        stable_rel = None
        if newer:
            stable_rel, _, made = self._place(path, "debs", entry["dir"], name)
            if made:
                created.append(stable_rel)
        rec = {
            **base,
            "package": fields["Package"],
            "version": version,
            "upstream_version": fields["Version"],
            "deb_arch": fields["Architecture"],
            "filename": name,
            "sha256": digest,
            "size": os.path.getsize(path),
            "source": cand["url"],
            "signature": cand.get("signature", "none"),
            "checksum": "verified" if cand.get("sha256") else "none",
            "upstream_sha256": cand.get("sha256"),
            "upstream_id": cand.get("identity"),
            "published": have,
            "beta": beta_rel,
            "stable": stable_rel,
        }
        with self._guard:
            self.files.append(rec)
        return rec, created


def removable_configs(plan_doc, pkgs, previous):
    """(names, deleted): configs whose old files this run may remove.

    names: planned configs, disabled ones of this shard, and in a full run the
    deleted ones of this shard. deleted: the configs that no longer exist.
    """
    names = {e["config"] for e in plan_doc["entries"]} | set(plan_doc.get("covered", []))
    deleted = set()
    if plan_doc.get("full") and previous:
        shard = plan_doc.get("shard")
        known = {p["name"] for p in pkgs}
        for x in previous.get("files", []):
            if x["config"] not in known and (not shard or _shard_of(x["config"], shard[1]) == shard[0]):
                deleted.add(x["config"])
    return names | deleted, deleted


def prune_cache(cache, used):
    """Remove cached files that this run did not use. Return (files, bytes)."""
    n = size = 0
    for d, _, names in os.walk(cache, topdown=False):
        for name in names:
            path = os.path.join(d, name)
            if path not in used:
                size += os.path.getsize(path)
                os.unlink(path)
                n += 1
        if d != cache and not os.listdir(d):
            os.rmdir(d)
    return n, size


def fetch(plan_doc, pkgs, out, cache, pub_url=published.DEFAULT_URL, jobs=8, prune=False, previous=None,
          sink=None, stop=None, others=frozenset()):
    """Download, check and place. sink() gets the new paths of each upstream
    file as soon as they are placed (for upload while downloading)."""
    os.makedirs(out, exist_ok=True)
    os.makedirs(cache, exist_ok=True)
    f = Fetcher(pkgs, out, cache, published.Published(pub_url))
    f.sink, f.stop = sink, stop
    f.progress = net.Progress("fetch", sum(len(e["candidates"]) for e in plan_doc["entries"]))
    if previous:
        for x in previous.get("files", []):
            ident = x.get("upstream_sha256") or x.get("upstream_id")
            if ident:
                f.previous[(x["config"], x["release"], x["arch"], x["source"], ident)] = x
    groups = {}
    for e in plan_doc["entries"]:
        if e.get("skip"):
            f.skipped.append({**{k: e[k] for k in ("config", "release", "arch", "target")}, "reason": e["skip"]})
            continue
        for c in e["candidates"]:
            groups.setdefault(c["url"], []).append((e, c))
    # Largest files first: they take longest, and the upload starts on them early.
    order = sorted(groups.values(), key=lambda g: -(g[0][1].get("size") or 0))
    with cf.ThreadPoolExecutor(jobs) as ex:
        list(ex.map(f.group, order))
    f.progress.done(f"{len(f.files)} files ({f.unchanged} unchanged), {net.human(f.bytes)} downloaded, "
                    f"{len(f.skipped)} skipped")
    if prune:
        n, size = prune_cache(cache, f.used)
        net.log(f"cache: removed {n} unused files, {net.human(size)}")
    planned, deleted = removable_configs(plan_doc, pkgs, previous)
    keep = {p["name"]: p.get("keep", 1) for p in pkgs}
    carried, removed = retention.plan_removal(previous, f.files, f.skipped, planned, keep, deleted, others)
    if others is None:
        net.warn("other shards' manifests unknown: no old files removed in this run")
    if removed:
        net.log(f"retention: {len(removed)} old files to remove")
    manifest = {
        "generated": _now(),
        "tool": TOOL,
        "releases": plan_doc["releases"],
        "files": sorted(f.files + carried, key=lambda x: (x["config"], x["release"], x["arch"], x["filename"])),
        "skipped": sorted(f.skipped, key=lambda x: (x["config"], x["release"], x["arch"])),
        "removed": removed,
        "configs": sorted(planned),
    }
    with open(os.path.join(out, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)
    return manifest


# --- report ---------------------------------------------------------------------

def report(manifest):
    """Markdown summary: one row per config, release and architecture."""
    files = [x for x in manifest["files"] if not x.get("carried")]
    skipped = manifest["skipped"]
    groups = {}
    for x in files:
        groups.setdefault((x["config"], x["release"], x["arch"]), []).append(x)
    stable_n = sum(1 for x in files if x["stable"])
    lines = [
        f"### External packages: {len(files)} files ({stable_n} for stable), {len(skipped)} skipped",
        "",
        "| config | release | arch | files | stable | example | published | check |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for (cfg, rel, arch), xs in sorted(groups.items()):
        st = [x for x in xs if x["stable"]]
        ex = (st or xs)[0]
        sig = all(x["signature"] == "verified" for x in xs)
        sha = all(x["checksum"] == "verified" for x in xs)
        check = "sig+sha" if sig and sha else ("sig" if sig else ("sha" if sha else "none"))
        lines.append(f"| {cfg} | {rel} | {arch} | {len(xs)} | {len(st)} | "
                     f"{ex['package']} {ex['version']} | {ex['published'] or '-'} | {check} |")
    removed = manifest.get("removed", [])
    if removed:
        lines += ["", f"#### Old files to remove: {len(removed)}", ""]
        lines += [f"- `{r}`" for r in removed[:50]]
        if len(removed) > 50:
            lines.append(f"- ... and {len(removed) - 50} more")
    if skipped:
        lines += ["", "#### Skipped", "", "| config | release | arch | reason |", "|---|---|---|---|"]
        for sk in skipped:
            lines.append(f"| {sk['config']} | {sk['release']} | {sk['arch']} | {sk['reason'][:200]} |")
    return "\n".join(lines)
