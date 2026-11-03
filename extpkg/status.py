"""Sync status on the server, for the repository update.

    <dest>/.sync/shard-<n>.json            running | done | failed
    <dest>/.sync/manifest-shard-<n>.json   manifest of the last successful run

The repository update publishes only when no shard is "running". A "running"
file older than a few hours means that the runner died.
"""

import datetime
import hashlib
import json
import os
import subprocess
import tempfile

from . import net

DIR = ".sync"


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _run_info(shard):
    env = os.environ
    url = ""
    if env.get("GITHUB_RUN_ID"):
        url = f"{env.get('GITHUB_SERVER_URL', 'https://github.com')}/{env.get('GITHUB_REPOSITORY')}" \
              f"/actions/runs/{env['GITHUB_RUN_ID']}"
    return {"shard": shard or "all", "run_id": env.get("GITHUB_RUN_ID", ""), "run_url": url,
            "runner": env.get("RUNNER_NAME", os.uname().nodename)}


def name(shard):
    return f"shard-{shard.split('/')[0]}" if shard else "shard-all"


class Status:
    def __init__(self, dest, shard, port=22, known_hosts=None, dry_run=True):
        self.dest, self.shard, self.dry_run = dest.rstrip("/"), shard, dry_run
        self.name = name(shard)
        self.ssh = ["ssh", "-p", str(port), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes"]
        if known_hosts:
            self.ssh += ["-o", f"UserKnownHostsFile={known_hosts}"]
        self.info = {**_run_info(shard), "started": _now()}

    def _put(self, files):
        """files: {name under .sync/: bytes}. One rsync call."""
        if self.dry_run:
            for n in files:
                net.log(f"dry-run: would write {self.dest}/{DIR}/{n}")
            return
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, DIR))
            for n, data in files.items():
                with open(os.path.join(tmp, DIR, n), "wb") as f:
                    f.write(data)
            # Write to a temp name and rename: a reader never sees half a file.
            cmd = ["rsync", "-r", "--mkpath", "--delay-updates", "-e", " ".join(self.ssh),
                   f"{tmp}/{DIR}/", f"{self.dest}/{DIR}/"]
            r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"status write failed (exit {r.returncode}): {r.stderr.strip()[-300:]}")

    def _state(self, state, **extra):
        doc = {"state": state, **self.info, **extra}
        if state != "running":
            doc["finished"] = _now()
        return json.dumps(doc, indent=1).encode()

    def running(self):
        self._put({f"{self.name}.json": self._state("running")})
        net.log(f"status: {self.name} running")

    def done(self, manifest_path, paths, size, removed):
        with open(manifest_path, "rb") as f:
            data = f.read()
        doc = self._state("done", paths=paths, bytes=size, removed=removed,
                          manifest=f"{DIR}/manifest-{self.name}.json",
                          manifest_sha256=hashlib.sha256(data).hexdigest())
        # Manifest first, then the state that points to it.
        self._put({f"manifest-{self.name}.json": data})
        self._put({f"{self.name}.json": doc})
        net.log(f"status: {self.name} done, manifest {hashlib.sha256(data).hexdigest()[:16]}")

    def failed(self, reason):
        self._put({f"{self.name}.json": self._state("failed", reason=str(reason)[:500])})
        net.log(f"status: {self.name} failed")

