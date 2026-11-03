"""Upload the output tree to the repository server.

Same rules as the old workflow: rsync into <dest>/debs and <dest>/debs-beta,
and never overwrite a file that is already there (--ignore-existing).
Differences: host keys are checked (known_hosts), and one rsync call per
repository instead of one per file.
"""

import os
import subprocess

from . import net


def plan_upload(out):
    files = []
    for repo in ("debs", "debs-beta"):
        root = os.path.join(out, repo)
        for d, _, names in os.walk(root):
            for n in sorted(names):
                if n.endswith(".deb"):
                    files.append(os.path.relpath(os.path.join(d, n), out))
    return sorted(files)


def upload(out, dest, port=22, known_hosts=None, dry_run=True):
    """dest is user@host:/path/to/incoming/external."""
    files = plan_upload(out)
    if not files:
        net.log("nothing to upload")
        return 0
    ssh = ["ssh", "-p", str(port), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes"]
    if known_hosts:
        ssh += ["-o", f"UserKnownHostsFile={known_hosts}"]
    for repo in ("debs", "debs-beta"):
        if not os.path.isdir(os.path.join(out, repo)):
            continue
        cmd = ["rsync", "-rvc", "--mkpath", "--ignore-existing", "--include=*/", "--include=*.deb",
               "--exclude=*", "-e", " ".join(ssh), f"{out}/{repo}/", f"{dest.rstrip('/')}/{repo}/"]
        if dry_run:
            net.log("dry-run: " + " ".join(cmd))
            for f in files:
                if f.startswith(repo + "/"):
                    net.log(f"dry-run: would upload {f} -> {dest.rstrip('/')}/{f}")
            continue
        r = subprocess.run(cmd)
        if r.returncode != 0:
            raise RuntimeError(f"rsync of {repo} failed (exit {r.returncode})")
    return len(files)


def remove(paths, dest, port=22, known_hosts=None, dry_run=True):
    """Delete exactly these paths (relative to dest) on the server.

    rsync --delete-missing-args with --files-from: every listed path is
    missing in the empty source, so rsync deletes it on the destination.
    Nothing else is touched.
    """
    from . import retention

    bad = [p for p in paths if not retention.safe_path(p)]
    if bad:
        raise ValueError(f"refusing to remove unsafe paths: {bad[:5]}")
    if not paths:
        return 0
    if dry_run:
        for p in paths:
            net.log(f"dry-run: would remove {dest.rstrip('/')}/{p}")
        return len(paths)
    import tempfile
    ssh = ["ssh", "-p", str(port), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes"]
    if known_hosts:
        ssh += ["-o", f"UserKnownHostsFile={known_hosts}"]
    with tempfile.TemporaryDirectory() as tmp:
        empty = os.path.join(tmp, "src")
        # The parent directories exist in the source; only the files are missing.
        for p in paths:
            os.makedirs(os.path.join(empty, os.path.dirname(p)), exist_ok=True)
        listfile = os.path.join(tmp, "remove-list")
        with open(listfile, "w") as f:
            f.write("\n".join(paths) + "\n")
        cmd = ["rsync", "-v", "--delete-missing-args", f"--files-from={listfile}",
               "-e", " ".join(ssh), f"{empty}/", f"{dest.rstrip('/')}/"]
        r = subprocess.run(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"rsync remove failed (exit {r.returncode})")
    for p in paths:
        net.log(f"removed {p}")
    return len(paths)
