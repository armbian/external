"""Upstream bumps: find build configs whose pinned upstream tag has a newer release.

A config with a tag in upstream.ref is a candidate. upstream.bump: off skips it.
upstream.bump_group puts several configs into one pull request.
The tag pattern is upstream.tags, else the prefix of the pinned tag (v1.2.0 gives v*).
"""

import json
import os
import re

from . import config, debver, net, source

MARKER = "<!-- extpkg-bump: {} -->"


def default_pattern(ref):
    """v1.2.0 -> v*, mesa-26.0 -> mesa-*, 251123 -> *."""
    m = re.match(r"^(\D*)", ref)
    return f"{m.group(1)}*"


def _eligible(pkg):
    up = pkg.get("upstream") or {}
    ref = str(up.get("ref", "latest"))
    return (pkg["method"] == "build" and up.get("url") and ref != "latest"
            and not up.get("rebase") and up.get("bump", "pr") not in ("off", False))


def find(directory, names=None, tags_of=source.remote_tags):
    """Configs with a newer upstream release tag: a list of dicts, sorted by config."""
    tags_cache = {}
    found = []
    for pkg in config.load_all(directory, names):
        if not _eligible(pkg):
            continue
        up = pkg["upstream"]
        old = str(up["ref"])
        try:
            if up["url"] not in tags_cache:
                tags_cache[up["url"]] = tags_of(up["url"])
        except net.FetchError as e:
            net.warn(f"{pkg['name']}: {e}")
            continue
        tags = tags_cache[up["url"]]
        if old not in tags:
            continue  # a branch
        new = source.newest_tag(tags, up.get("tags") or default_pattern(old))
        if not new or debver.compare(source.tag_version(new), source.tag_version(old)) <= 0:
            continue
        found.append({"config": pkg["name"], "url": up["url"], "old": old, "new": new,
                      "group": up.get("bump_group") or pkg["name"],
                      "path": os.path.join(directory, f"{pkg['name']}.yaml")})
    return sorted(found, key=lambda b: b["config"])


def apply(path, old, new):
    """Set upstream.ref from old to new in place. Comments and key order stay.
    A revision above 1 goes back to 1: the new upstream version sorts higher."""
    with open(path) as f:
        text = f.read()
    ref_line = re.compile(r"^(\s+ref:\s*)(['\"]?)" + re.escape(old) + r"\2(\s*(?:#.*)?)$", re.M)
    text, n = ref_line.subn(lambda m: f"{m.group(1)}{m.group(2)}{new}{m.group(2)}{m.group(3)}", text)
    if n != 1:
        raise config.ConfigError(f"{path}: expected one 'ref: {old}' line, found {n}")
    text = re.sub(r"^revision:\s*\d+\s*$", "revision: 1", text, flags=re.M)
    with open(path, "w") as f:
        f.write(text)


def _changes(b):
    url = b["url"].removesuffix(".git")
    if "github.com/" in url:
        return f"[{b['old']}...{b['new']}]({url}/compare/{b['old']}...{b['new']})"
    return ""


def groups(bumps):
    """One pull request per group: branch, title, body, configs and bumps."""
    by = {}
    for b in bumps:
        by.setdefault(b["group"], []).append(b)
    out = []
    for key, items in sorted(by.items()):
        if len(items) == 1 and items[0]["config"] == key:
            title = f"{key}: update upstream to {items[0]['new']}"
        else:
            title = f"{key}: update upstream of {len(items)} packages"
        rows = "\n".join(f"| {b['config']} | {b['old']} | {b['new']} | {_changes(b)} |" for b in items)
        marker = MARKER.format(" ".join(f"{b['config']}={b['new']}" for b in items))
        body = ("Newer upstream release tags. The build check of this pull request builds them.\n\n"
                "| Config | Old | New | Changes |\n| --- | --- | --- | --- |\n"
                f"{rows}\n\n{marker}\n")
        out.append({"key": key, "branch": f"bump/{key}", "title": title, "body": body, "marker": marker,
                    "configs": [b["config"] for b in items], "bumps": items})
    return out


def write_plan(path, plan):
    with open(path, "w") as f:
        json.dump(plan, f, indent=1)


def apply_group(plan_path, key):
    """Apply the bumps of one group of a plan file."""
    with open(plan_path) as f:
        plan = json.load(f)
    group = next((g for g in plan if g["key"] == key), None)
    if group is None:
        raise config.ConfigError(f"{plan_path}: no group {key!r}")
    for b in group["bumps"]:
        apply(b["path"], b["old"], b["new"])
    return group
