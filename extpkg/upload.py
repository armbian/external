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
