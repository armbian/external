"""Command line: validate, plan, fetch, run, upload."""

import argparse
import json
import os
import sys

from . import config, net, pipeline, published, upload

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _common(p):
    p.add_argument("--packages", default=os.path.join(ROOT, "packages"), help="package configs")
    p.add_argument("--keys", default=os.path.join(ROOT, "keys"), help="upstream signing keys")
    p.add_argument("--only", default="", help="comma separated package names")
    p.add_argument("--build-dir", default=os.environ.get("ARMBIAN_BUILD_DIR"),
                   help="armbian/build checkout, for the list of supported releases")
    p.add_argument("--jobs", type=int, default=8)


def _load(args):
    names = [n for n in args.only.split(",") if n]
    pkgs = config.load_all(args.packages, names or None)
    releases = config.supported_releases(args.build_dir)
    return pkgs, releases


def _failed(manifest):
    """Skips that are errors. A source without a build for one arch is not."""
    return [s for s in manifest["skipped"] if s["reason"] != "no package matched"]


def _shard(text):
    if not text:
        return None
    i, n = text.split("/")
    return int(i), int(n)


def cmd_validate(args):
    pkgs, releases = _load(args)
    print(f"{len(pkgs)} package configs valid; releases: {' '.join(releases)}")
    return 0


def cmd_plan(args):
    pkgs, releases = _load(args)
    doc = pipeline.plan(pkgs, releases, args.keys, args.jobs, _shard(args.shard))
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
    m = pipeline.fetch(doc, pkgs, args.out, args.cache, args.published, args.jobs)
    rep = pipeline.report(m)
    net.summary(rep)
    print(rep)
    return 1 if args.strict and _failed(m) else 0


def cmd_run(args):
    pkgs, releases = _load(args)
    doc = pipeline.plan(pkgs, releases, args.keys, args.jobs, _shard(args.shard))
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "plan.json"), "w") as f:
        json.dump(doc, f, indent=1)
    m = pipeline.fetch(doc, pkgs, args.out, args.cache, args.published, args.jobs)
    rep = pipeline.report(m)
    net.summary(rep)
    print(rep)
    if args.dest:
        upload.upload(args.out, args.dest, args.port, args.known_hosts, dry_run=args.dry_run)
    elif not args.dry_run:
        net.warn("no --dest: output stays in " + args.out)
    else:
        for f in upload.plan_upload(args.out):
            net.log(f"dry-run: would upload {f}")
    return 1 if args.strict and _failed(m) else 0


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
        p.set_defaults(fn=fn)
        if name == "fetch":
            p.add_argument("--plan", default="plan.json")
        else:
            p.add_argument("--shard", default="", help="i/n: take part i of n packages")
            p.add_argument("--dest", default="", help="user@host:/path/incoming/external")
            p.add_argument("--port", type=int, default=22)
            p.add_argument("--known-hosts", default=None)
            p.add_argument("--dry-run", action="store_true", help="do everything except the upload")

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
