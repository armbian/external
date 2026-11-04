#!/usr/bin/env python3
"""Convert armbian/os external/*.conf (shell) into mirror/<name>.yaml.

Usage: tools/import-os.py <os checkout>/external mirror/

The old download workflow had per-package code paths. They become config:
- fastfetch: drop the polyfilled and armv6l assets
- haos-supervised-installer: take every .deb asset
- firefox-*: repack firefox with epoch 9 and suffix armbian1 (as published)
"""

import json
import os
import subprocess
import sys

import yaml

METHOD = {"aptly": "apt", "gh": "github", "direct": "url"}
FLAT = ("./", "public")
VARS = ("URL", "KEY", "RELEASE", "TARGET", "METHOD", "INSTALL", "GLOB", "ARCH", "TAG", "CHECKSUM",
        "SIGNATURES")


def source_conf(path):
    script = '. "$1"; for v in ' + " ".join(VARS) + '; do printf "%s\\0%s\\0" "$v" "${!v}"; done'
    out = subprocess.run(["bash", "-c", script, "bash", path], capture_output=True, check=True).stdout
    parts = out.decode().split("\0")[:-1]
    return dict(zip(parts[0::2], parts[1::2]))


def convert(name, c):
    method = METHOD[c.get("METHOD") or "aptly"]
    rel = c.get("RELEASE") or "all"
    pkg = {
        "name": name,
        "method": method,
        "source": {"url": c["URL"].replace("\\&", "&")},
        "releases": "all" if rel == "all" else rel.split(":"),
        "architectures": c["ARCH"].split(":"),
        "target": c.get("TARGET") or "main",
        "install": (c.get("INSTALL") or "").split(),
    }
    if method == "apt":
        key = c.get("KEY") or ""
        if key in FLAT:
            suite, comps = key, []
        else:
            parts = key.split()
            suite, comps = parts[0], list(dict.fromkeys(parts[1:])) or ["main"]
        pkg["source"]["suite"] = suite
        if comps:
            pkg["source"]["components"] = comps
        pkg["filter"] = c["GLOB"]
        verify = {}
        if c.get("CHECKSUM") == "ignore":
            verify["checksums"] = False
        if c.get("SIGNATURES") == "ignore":
            verify["signature"] = False
        if verify:
            pkg["verify"] = verify
    if method == "github" and c.get("TAG"):
        pkg["source"]["tag"] = c["TAG"]
    if name == "fastfetch":
        pkg["exclude"] = ["*polyfilled*", "*armv6l.deb"]
    if name == "haos-supervised-installer":
        pkg["assets"] = ["*.deb"]
    if name.startswith("firefox"):
        pkg["repack"] = {"packages": ["firefox"], "epoch": 9, "suffix": "armbian1"}
        pkg["notes"] = "Epoch 9 wins over the Ubuntu snap transitional package."
    return pkg


def main():
    src, dst = sys.argv[1], sys.argv[2]
    os.makedirs(dst, exist_ok=True)
    done, skipped = 0, []
    for f in sorted(os.listdir(src)):
        if not f.endswith(".conf"):
            if f.endswith(".conf.disabled"):
                skipped.append(f[: -len(".conf.disabled")])
            continue
        name = f[:-5]
        pkg = convert(name, source_conf(os.path.join(src, f)))
        with open(os.path.join(dst, name + ".yaml"), "w") as out:
            yaml.safe_dump(pkg, out, sort_keys=False, width=200)
        done += 1
    print(json.dumps({"converted": done, "disabled_not_imported": skipped}))


if __name__ == "__main__":
    main()
