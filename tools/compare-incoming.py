#!/usr/bin/env python3
"""Compare two incoming trees and show packages that the new tree is missing.

Usage: compare-incoming.py [--repos debs-beta] OLD NEW
  OLD  for example storage/incoming/external
  NEW  for example storage/incoming/external-next

debs-beta holds every package, so it is the completeness check (default).
debs holds only packages that were newer than the published stable version
at upload time: a package that is already published is not missing.
Use --repos debs,debs-beta to compare both.

A package is (repository, directory, package name, architecture). Versions
are ignored, except to report when the newest version in NEW is older than
the newest version in OLD. Exit code 1 when NEW is missing a package.
"""

import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict

NAME = re.compile(r"^([a-z0-9][a-z0-9+.-]+)_([^_]+)_([a-z0-9]+)\.deb$")


def control(path, cache):
    """(Package, Version, Architecture) of a .deb. Hardlinks are read once."""
    st = os.stat(path)
    key = (st.st_dev, st.st_ino)
    if key not in cache:
        fields = None
        if shutil.which("dpkg-deb"):
            r = subprocess.run(["dpkg-deb", "-f", path, "Package", "Version", "Architecture"],
                               capture_output=True, text=True)
            if r.returncode == 0:
                d = dict(line.split(": ", 1) for line in r.stdout.splitlines() if ": " in line)
                fields = (d.get("Package"), d.get("Version"), d.get("Architecture"))
        if not fields or not all(fields):
            m = NAME.match(os.path.basename(path))
            fields = m.groups() if m else (os.path.basename(path), "?", "?")
        cache[key] = fields
    return cache[key]


def scan(root, repos):
    """{(repo, dir, package, arch): [versions]}"""
    out, cache = defaultdict(list), {}
    for repo in repos:
        base = os.path.join(root, repo)
        for d, _, names in os.walk(base):
            for n in names:
                if not n.endswith(".deb"):
                    continue
                pkg, ver, arch = control(os.path.join(d, n), cache)
                out[(repo, os.path.relpath(d, base), pkg, arch)].append(ver)
    return out


def newest(versions):
    if not shutil.which("dpkg"):
        return sorted(versions)[-1]
    best = versions[0]
    for v in versions[1:]:
        if subprocess.run(["dpkg", "--compare-versions", v, "gt", best]).returncode == 0:
            best = v
    return best


def main():
    args = sys.argv[1:]
    repos = ["debs-beta"]
    if len(args) >= 2 and args[0] == "--repos":
        repos = args[1].split(",")
        args = args[2:]
    if len(args) != 2:
        sys.exit(__doc__)
    old_root, new_root = args
    print(f"old: {old_root}\nnew: {new_root}\nrepos: {','.join(repos)}\nscanning ...", flush=True)
    old, new = scan(old_root, repos), scan(new_root, repos)

    missing = sorted(k for k in old if k not in new)
    only_new = sorted(k for k in new if k not in old)
    older = []
    for k in sorted(set(old) & set(new)):
        o, n = newest(old[k]), newest(new[k])
        if o != n and newest([o, n]) == o:
            older.append((k, o, n))

    print(f"\npackages: old {len(old)}, new {len(new)}, "
          f"missing in new {len(missing)}, only in new {len(only_new)}, older in new {len(older)}")

    if missing:
        print("\n== Missing in new (repository/directory: package arch, newest old version)")
        by_dir = defaultdict(list)
        for repo, d, pkg, arch in missing:
            by_dir[f"{repo}/{d}"].append(f"{pkg} {arch} {newest(old[(repo, d, pkg, arch)])}")
        for d in sorted(by_dir):
            print(f"{d}:")
            for line in sorted(by_dir[d]):
                print(f"  {line}")

    if older:
        print("\n== Newest version in new is older than in old")
        for (repo, d, pkg, arch), o, n in older:
            print(f"  {repo}/{d}: {pkg} {arch}  old {o}  new {n}")

    if only_new:
        print(f"\n== Only in new: {len(only_new)} (first 20)")
        for repo, d, pkg, arch in only_new[:20]:
            print(f"  {repo}/{d}: {pkg} {arch}")

    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
