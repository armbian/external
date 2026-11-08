"""Command line: validate, plan, fetch, run, upload."""

import argparse
import json
import os
import re
import sys

from . import builder, config, depcheck, net, pipeline, published, site, status, upload

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BETA_URL = "https://fi.mirror.armbian.de/beta"


def _common(p):
    p.add_argument("--configs", default=None,
                   help="config directory: mirror/ (default) or build/ (build commands)")
    p.add_argument("--keys", default=os.path.join(ROOT, "keys"), help="upstream signing keys")
    p.add_argument("--only", default="", help="comma separated package names")
    p.add_argument("--build-dir", default=os.environ.get("ARMBIAN_BUILD_DIR"),
                   help="armbian/build checkout, for the list of supported releases")
    p.add_argument("--jobs", type=int, default=8)


def _configs(args):
    return args.configs or os.path.join(ROOT, getattr(args, "default_configs", "mirror"))


def _load(args):
    names = [n for n in args.only.split(",") if n]
    pkgs = config.load_all(_configs(args), names or None)
    releases = config.supported_releases(args.build_dir)
    return pkgs, releases


def _plan(args, pkgs, releases):
    return pipeline.plan(pkgs, releases, args.keys, args.jobs, _shard(getattr(args, "shard", "")),
                         full=not args.only, packages_dir=_configs(args))


def _failed(manifest):
    """Skips that are errors. A source without a build for one arch is not."""
    return [s for s in manifest["skipped"] if s["reason"] != "no package matched"]


def _previous(args):
    """Manifest of the last successful upload, if given and readable."""
    if not args.previous or not os.path.exists(args.previous):
        return None
    with open(args.previous) as f:
        doc = json.load(f)
    net.log(f"previous: {len(doc.get('files', []))} files from {doc.get('generated', '?')}")
    return doc


def _shard(text):
    """i/n splits the configs. A plain name (build) only names the status file."""
    if not text or "/" not in text:
        return None
    i, n = text.split("/")
    return int(i), int(n)


def cmd_validate(args):
    """Both directories, or the one that --configs names."""
    dirs = [args.configs] if args.configs else [os.path.join(ROOT, d) for d in ("mirror", "build")]
    counts = [f"{len(config.load_all(d))} in {os.path.basename(os.path.normpath(d))}/" for d in dirs]
    releases = config.supported_releases(args.build_dir)
    print(f"package configs valid: {', '.join(counts)}; releases: {' '.join(releases)}")
    return 0


def cmd_plan(args):
    pkgs, releases = _load(args)
    doc = _plan(args, pkgs, releases)
    with open(args.out, "w") as f:
        json.dump(doc, f, indent=1)
    skipped = [e for e in doc["entries"] if e.get("skip")]
    files = sum(len(e["candidates"]) for e in doc["entries"])
    print(f"plan: {len(doc['entries'])} entries, {files} files, {len(skipped)} skipped -> {args.out}")
    for e in skipped:
        net.warn(f"{e['config']} {e['release']}/{e['arch']}: {e['skip']}")
    return 0


def cmd_fetch(args):
    pkgs, _ = _load(args)
    with open(args.plan) as f:
        doc = json.load(f)
    m = pipeline.fetch(doc, pkgs, args.out, args.cache, args.published, args.jobs, args.prune_cache, _previous(args))
    rep = pipeline.report(m)
    net.summary(rep)
    print(rep)
    return 1 if args.strict and _failed(m) else 0


def cmd_run(args):
    pkgs, releases = _load(args)
    live = bool(args.dest) and not args.dry_run
    # Tell the repository update that this shard is uploading.
    st = status.Status(args.dest, args.shard, args.port, args.known_hosts, dry_run=not live) if args.dest else None
    if st:
        st.running()
    try:
        rc = _run(args, pkgs, releases, st)
    except BaseException as e:
        if st:
            st.failed(f"{type(e).__name__}: {e}")
        raise
    return rc


def _run(args, pkgs, releases, st):
    if args.plan:
        # The plan that the builds used: a new plan could name newer sources.
        with open(args.plan) as f:
            doc = json.load(f)
    else:
        doc = _plan(args, pkgs, releases)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "plan.json"), "w") as f:
        json.dump(doc, f, indent=1)
    # With --dest, upload while downloading. Without it, a dry run lists the files.
    up = None
    if args.dest or args.dry_run:
        up = upload.StreamUploader(args.out, args.dest or "<dest>", args.port, args.known_hosts,
                                   dry_run=args.dry_run or not args.dest, streams=args.streams)
    # Before removing old files, see which paths the other shards still list.
    # A dry run only reports, so it does not need them.
    others = frozenset()
    if args.dest and not args.dry_run:
        others = status.other_paths(args.dest, args.shard, args.port, args.known_hosts)
    m = pipeline.fetch(doc, pkgs, args.out, args.cache, args.published, args.jobs, args.prune_cache,
                       _previous(args), sink=up.add if up else None, stop=up.failed if up else None,
                       others=others, built=args.built)
    if args.depcheck:
        _depcheck(args, pkgs, m)
    rep = pipeline.report(m) + depcheck.report(m.get("depcheck", []))
    net.summary(rep)
    print(rep)
    if up:
        up.finish()   # raises when a batch failed: no removal, no state
        upload.remove(m["removed"], args.dest or "<dest>", args.port, args.known_hosts,
                      dry_run=args.dry_run or not args.dest)
        if st:
            st.done(os.path.join(args.out, "manifest.json"), up.files, up.bytes, len(m["removed"]))
    else:
        net.warn("no --dest: output stays in " + args.out)
    # --strict: the upload is done; a skipped package or a failed dependency
    # check only sets the exit code.
    dep_failed = any(x["ok"] is False for x in m.get("depcheck", []))
    return 1 if args.strict and (_failed(m) or dep_failed) else 0


def _depcheck(args, pkgs, m):
    """Report only: results go into the manifest and the summary."""
    m["depcheck"] = depcheck.check(m, args.out, pkgs, args.build_dir, args.lists_cache, args.keys,
                                   extra_keyrings=[k for k in args.keyring if k])
    with open(os.path.join(args.out, "manifest.json"), "w") as f:
        json.dump(m, f, indent=1)


def cmd_depcheck(args):
    pkgs, _ = _load(args)
    with open(os.path.join(args.out, "manifest.json")) as f:
        m = json.load(f)
    _depcheck(args, pkgs, m)
    rep = depcheck.report(m["depcheck"])
    net.summary(rep)
    print(rep)
    return 1 if args.strict and any(x["ok"] is False for x in m["depcheck"]) else 0


def next_build_version(version, uploaded):
    """The planned version, or the next build number when it is uploaded.

    2.71.0-1+armbian1~forky -> 2.71.0-1+armbian1.1~forky -> ...armbian1.2~forky.
    dpkg sorts armbian1 < armbian1.1 < armbian2: a new revision still wins.
    """
    base, sep, rel = version.rpartition("~")
    if not sep:
        base, rel = version, ""
    numbered = re.compile(re.escape(base) + r"\.(\d+)" + re.escape(sep + rel) + "$")
    used = [int(m.group(1)) for m in map(numbered.match, uploaded) if m]
    if version not in uploaded and not used:
        return version
    return f"{base}.{max(used, default=0) + 1}{sep}{rel}"


def cmd_build_matrix(args):
    """Builds that the plan needs, as {"deps": [...], "builds": [...]}.

    A build is needed when its identity is not in the previous manifest.
    deps: the configs that other configs name in build_depends. They build
    first, and always together with a config that needs them.
    """
    pkgs, _ = _load(args)
    with open(args.plan) as f:
        doc = json.load(f)
    prev = pipeline.index_previous(_previous(args))
    by_name = {p["name"]: p for p in pkgs}
    dep_names = {d for p in pkgs for d in p.get("build_depends", [])}
    entries = {}
    for e in doc["entries"]:
        if e.get("skip"):
            net.warn(f"{e['config']} {e['release']}/{e['arch']}: {e['skip']}")
        elif e["config"] in by_name:
            entries[(e["config"], e["release"], e["arch"])] = e
    needed = {k for k, e in entries.items() if not pipeline.previous_of(prev, e, e["candidates"][0])}
    # Same version, other inputs (a new Debian packaging, a moved tag): same
    # file names. The upload never replaces a file. Give the build the next
    # build number: <base>.<n>~<release>. The identity keeps the planned
    # version, so the next run finds this build in the manifest.
    uploaded = {}
    for xs in prev.values():
        for x in xs:
            uploaded.setdefault((x["config"], x["release"], x["arch"]), set()).add(x["version"])
    renumbered = False
    for key in sorted(needed):
        b = entries[key]["candidates"][0]["build"]
        new = next_build_version(b["version"], uploaded.get(key, set()))
        if new != b["version"]:
            net.warn(f"{key[0]} {key[1]}/{key[2]}: the build inputs changed, but version {b['version']} "
                     f"is in the last manifest. Build {new}.")
            b["version"] = new
            renumbered = True
    if renumbered:
        with open(args.plan, "w") as f:
            json.dump(doc, f, indent=1)
    for name, rel, arch in list(needed):
        for dep in by_name[name].get("build_depends", []):
            if (dep, rel, arch) not in entries:
                net.warn(f"{name} {rel}/{arch}: build_depends {dep} has no build for {rel}/{arch}")
                continue
            needed.add((dep, rel, arch))

    def job(key):
        e = entries[key]
        return {"config": e["config"], "release": e["release"], "arch": e["arch"],
                "version": e["candidates"][0]["build"]["version"],
                "runner": config.RUNNERS[e["arch"]],
                "image": f"{depcheck.distro_of(e['release'], args.build_dir)}:{e['release']}"}
    out = {"deps": [job(k) for k in sorted(needed) if k[0] in dep_names],
           "builds": [job(k) for k in sorted(needed) if k[0] not in dep_names]}
    print(json.dumps(out))
    net.log(f"build-matrix: {len(out['deps'])} dependency builds, {len(out['builds'])} builds")
    return 0


def cmd_build(args):
    pkgs, _ = _load(args)
    with open(args.plan) as f:
        doc = json.load(f)
    builder.build(doc, pkgs, _configs(args), args.config, args.release, args.arch, args.out, deps=args.deps)
    return 0


def cmd_status(args):
    """Mark a shard failed, for a job that was cancelled or failed outside the tool."""
    st = status.Status(args.dest, args.shard, args.port, args.known_hosts, dry_run=False)
    if args.state == "failed":
        st.failed(args.reason)
    else:
        st.running()
    return 0


def cmd_site(args):
    pkgs = config.load_all(os.path.join(ROOT, "mirror")) + config.load_all(os.path.join(ROOT, "build"))
    manifests = {}
    for path in args.manifest:
        if os.path.exists(path):
            with open(path) as f:
                manifests[os.path.basename(os.path.dirname(os.path.abspath(path)))] = json.load(f)
        else:
            net.warn(f"{path}: not found")
    repos = [published.Published(u) for u in args.published or [published.DEFAULT_URL, BETA_URL]]

    def describe(*key):
        return next((d for d in (r.description(*key) for r in repos) if d), None)

    data = site.collect(pkgs, manifests, describe if args.published != [""] else None)
    site.write(data, args.out)
    print(f"site: {len(data['packages'])} packages, {len(manifests)} manifests -> {args.out}")
    return 0


def cmd_upload(args):
    n = upload.upload(args.out, args.dest, args.port, args.known_hosts, dry_run=args.dry_run)
    print(f"{'would upload' if args.dry_run else 'uploaded'} {n} files")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="extpkg", description="Armbian external packages")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate", help="check package configs")
    _common(p)
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("plan", help="resolve versions and files; no .deb download")
    _common(p)
    p.add_argument("--shard", default="", help="i/n: take part i of n packages")
    p.add_argument("--out", default="plan.json")
    p.set_defaults(fn=cmd_plan)

    for name, fn, help_text in (("fetch", cmd_fetch, "download a plan into the output tree"),
                                ("run", cmd_run, "plan, fetch and optionally upload")):
        p = sub.add_parser(name, help=help_text)
        _common(p)
        p.add_argument("--out", default="output", help="output tree (debs/, debs-beta/, manifest.json)")
        p.add_argument("--cache", default=".cache/downloads", help="download cache")
        p.add_argument("--published", default=published.DEFAULT_URL, help="Armbian stable repository")
        p.add_argument("--strict", action="store_true", help="exit 1 when a download or check fails")
        p.add_argument("--previous", default="",
                       help="manifest of the last successful upload: skip files it already has")
        p.add_argument("--prune-cache", action="store_true",
                       help="remove cached files this run did not use (for a persistent cache)")
        p.set_defaults(fn=fn)
        if name == "fetch":
            p.add_argument("--plan", default="plan.json")
        else:
            p.add_argument("--shard", default="", help="i/n: take part i of n packages")
            p.add_argument("--dest", default="", help="user@host:/path/incoming/external")
            p.add_argument("--port", type=int, default=22)
            p.add_argument("--known-hosts", default=None)
            p.add_argument("--dry-run", action="store_true", help="do everything except the upload")
            p.add_argument("--streams", type=int, default=3, help="upload batches at the same time")
            p.add_argument("--depcheck", action="store_true", help="check dependencies of new files (report only)")
            p.add_argument("--lists-cache", default=".cache/apt-lists", help="apt index lists for --depcheck")
            p.add_argument("--keyring", action="append", default=[], help="extra apt keyring for --depcheck")
            p.add_argument("--built", default=None, help="build outputs (--configs build)")
            p.add_argument("--plan", default="", help="use this plan, do not make a new one (--configs build)")

    p = sub.add_parser("build-matrix", help="list the builds that a plan needs, as JSON")
    _common(p)
    p.add_argument("--plan", default="plan.json")
    p.add_argument("--previous", default="", help="manifest of the last successful upload")
    p.add_argument("--live", action="store_true",
                   help="fail when changed inputs reuse an uploaded version (else warn)")
    p.set_defaults(fn=cmd_build_matrix, default_configs="build")

    p = sub.add_parser("build", help="build one package for one release and architecture")
    _common(p)
    p.add_argument("--plan", default="plan.json")
    p.add_argument("--config", required=True)
    p.add_argument("--release", required=True)
    p.add_argument("--arch", required=True)
    p.add_argument("--out", default="built")
    p.add_argument("--deps", default=None, help="build outputs of build_depends configs")
    p.set_defaults(fn=cmd_build, default_configs="build")

    p = sub.add_parser("depcheck", help="check dependencies of the new files in an output tree")
    _common(p)
    p.add_argument("--out", default="output")
    p.add_argument("--lists-cache", default=".cache/apt-lists")
    p.add_argument("--keyring", action="append", default=[], help="extra apt keyring")
    p.add_argument("--strict", action="store_true", help="exit 1 when a check fails")
    p.set_defaults(fn=cmd_depcheck)

    p = sub.add_parser("status", help="write the sync status of a shard on the server")
    p.add_argument("--dest", required=True)
    p.add_argument("--shard", default="")
    p.add_argument("--state", choices=["failed", "running"], required=True)
    p.add_argument("--reason", default="")
    p.add_argument("--port", type=int, default=22)
    p.add_argument("--known-hosts", default=None)
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("site", help="write the package list web page")
    p.add_argument("--manifest", action="append", default=[],
                   help="manifest of a live run; its directory names it (repeat)")
    p.add_argument("--out", default="site")
    p.add_argument("--published", action="append", default=[],
                   help="Armbian repository for descriptions of older manifest entries "
                        "(repeat; default: stable and beta; '' for none)")
    p.set_defaults(fn=cmd_site)

    p = sub.add_parser("upload", help="upload an output tree")
    p.add_argument("--out", default="output")
    p.add_argument("--dest", required=True)
    p.add_argument("--port", type=int, default=22)
    p.add_argument("--known-hosts", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_upload)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except config.ConfigError as e:
        net.error(str(e))
        return 2


if __name__ == "__main__":
    sys.exit(main())
