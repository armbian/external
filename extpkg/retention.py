"""Decide which earlier uploads are out of date.

The previous manifest lists every file that the last successful run put on
the server. A file that is not in the current set is old: for example
yesterday's VS Code build. Old files are removed after the new upload.
"""

from . import debver


def _paths(entry):
    return [p for p in (entry.get("beta"), entry.get("stable")) if p]


def safe_path(path):
    """Only .deb files under debs/ or debs-beta/, no '..'."""
    parts = path.split("/")
    return (parts[0] in ("debs", "debs-beta") and path.endswith(".deb")
            and ".." not in parts and "" not in parts and not path.startswith("/"))


def plan_removal(previous, files, skipped, planned_configs, keep, deleted=(), others=frozenset()):
    """Return (carried, removed).

    previous         manifest of the last successful run (or None)
    files            file entries of this run
    skipped          skipped entries of this run
    planned_configs  config names whose old files this run may remove
    keep             {config: number of versions to keep}, default 1
    deleted          configs that no longer exist (subset of planned_configs)
    others           paths that other shards list in their last manifest,
                     or None when they could not be read

    carried  previous entries to keep in the new manifest
    removed  server paths to delete

    A path that another shard lists is never removed: two configs in two
    shards can place the same file (for example after a rename).
    A deleted config waits one run ("orphan-pending"): by then every shard
    has published its manifest, also the shard of a renamed config.
    When the other manifests are unknown, nothing is removed.
    """
    if not previous:
        return [], []
    current_paths = {p for x in files for p in _paths(x)}
    # A failure in this run protects everything of that config, release and arch.
    protected = {(s["config"], s["release"], s["arch"]) for s in skipped}
    current = {}
    for x in files:
        current.setdefault((x["config"], x["release"], x["arch"], x["package"]), []).append(x["version"])

    carried, old = [], {}
    for x in previous.get("files", []):
        if x["config"] not in planned_configs:
            carried.append({**x, "carried": "not-planned"})   # keep tracking it
            continue
        if all(p in current_paths for p in _paths(x)):
            continue                 # still current
        if (x["config"], x["release"], x["arch"]) in protected:
            carried.append({**x, "carried": "failed"})        # do not touch
            continue
        if x["config"] in deleted and x.get("carried") != "orphan-pending":
            carried.append({**x, "carried": "orphan-pending"})  # remove next run
            continue
        old.setdefault((x["config"], x["release"], x["arch"], x["package"]), []).append(x)

    candidates = []
    for key, entries in old.items():
        if key not in current:
            # No current version of this package: upstream dropped it.
            keep_n = 0
        else:
            keep_n = max(keep.get(key[0], 1) - len(current[key]), 0)
        entries.sort(key=lambda e: debver.Version(e["version"]), reverse=True)
        for e in entries[:keep_n]:
            carried.append({**e, "carried": "keep"})
        candidates += entries[keep_n:]

    if others is None:
        # Other shards unknown: remove nothing, keep tracking for the next run.
        for e in candidates:
            carried.append({**e, "carried": e.get("carried") or "pending-check"})
        return carried, []
    removed = set()
    for e in candidates:
        removed.update(p for p in _paths(e) if p not in current_paths and p not in others)
    # Paths that a carried entry still uses stay.
    in_use = {p for x in carried for p in _paths(x)}
    return carried, sorted(p for p in removed if p not in in_use and safe_path(p))
