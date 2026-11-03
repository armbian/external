"""Upload the output tree to the repository server.

Same rules as the old workflow: rsync into <dest>/debs and <dest>/debs-beta,
and never overwrite a file that is already there (--ignore-existing).
Differences: host keys are checked (known_hosts), and one rsync call for
both repositories that keeps hardlinks, so each file is sent once.
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
    """dest is user@host:/path/to/incoming/external.

    One rsync for debs/ and debs-beta/ together, with -H: a file placed in
    several directories is a hardlink here, and rsync sends it once and
    links it on the server. Separate calls would send it once per path.
    """
    files = plan_upload(out)
    if not files:
        net.log("nothing to upload")
        return 0
    ssh = ["ssh", "-p", str(port), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes"]
    if known_hosts:
        ssh += ["-o", f"UserKnownHostsFile={known_hosts}"]
    srcs = [f"{out.rstrip('/')}/./{r}" for r in ("debs", "debs-beta") if os.path.isdir(os.path.join(out, r))]
    cmd = ["rsync", "-rvHR", "--mkpath", "--ignore-existing", "--include=*/", "--include=*.deb",
           "--exclude=*", "--prune-empty-dirs", "--stats", "-e", " ".join(ssh), *srcs, f"{dest.rstrip('/')}/"]
    if dry_run:
        net.log("dry-run: " + " ".join(cmd))
        for f in files:
            net.log(f"dry-run: would upload {f} -> {dest.rstrip('/')}/{f}")
        return len(files)
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"rsync upload failed (exit {r.returncode})")
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


class StreamUploader:
    """Upload placed files in batches while the downloads go on.

    fetch() hands over the new paths of each upstream file at once, so a file
    and its hardlinks are in one batch: rsync -H sends the data once.
    A batch goes when it reaches batch_bytes, or batch_secs after its first file.
    """

    def __init__(self, out, dest, port=22, known_hosts=None, dry_run=True,
                 batch_bytes=500 << 20, batch_secs=30):
        import queue
        import threading
        self.out, self.dest = out.rstrip("/"), dest.rstrip("/")
        self.dry_run = dry_run
        self.batch_bytes, self.batch_secs = batch_bytes, batch_secs
        self.ssh = ["ssh", "-p", str(port), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes"]
        if known_hosts:
            self.ssh += ["-o", f"UserKnownHostsFile={known_hosts}"]
        self.q = queue.Queue()
        self.error = None
        self.batches = self.files = self.bytes = 0
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def add(self, items):
        """items: [(path relative to out, size)]"""
        self.q.put(items)

    def failed(self):
        return self.error is not None

    def _send(self, batch):
        import tempfile
        import time
        paths = sorted({p for p, _ in batch})
        # Bytes that rsync sends: hardlinks count once.
        inodes = {}
        for p in paths:
            st = os.stat(os.path.join(self.out, p))
            inodes[(st.st_dev, st.st_ino)] = st.st_size
        size = sum(inodes.values())
        self.batches += 1
        n = self.batches
        if self.dry_run:
            for p in paths:
                net.log(f"dry-run: would upload {p}")
            net.log(f"upload batch {n}: {len(paths)} paths, {net.human(size)} (dry-run)")
        else:
            start = time.monotonic()
            with tempfile.NamedTemporaryFile("w", suffix=".list") as lf:
                lf.write("\n".join(paths) + "\n")
                lf.flush()
                cmd = ["rsync", "-H", "--ignore-existing", f"--files-from={lf.name}",
                       "-e", " ".join(self.ssh), f"{self.out}/", f"{self.dest}/"]
                r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"upload batch {n} failed (exit {r.returncode}): {r.stderr.strip()[-300:]}")
            secs = max(time.monotonic() - start, 0.1)
            net.log(f"upload batch {n}: {len(paths)} paths, {net.human(size)} in {secs:.0f} s "
                    f"({net.human(size / secs)}/s)")
        self.files += len(paths)
        self.bytes += size

    def _run(self):
        import queue
        import time
        batch, size, first = [], 0, None
        done = False
        while not done:
            timeout = None if first is None else max(first + self.batch_secs - time.monotonic(), 0)
            try:
                items = self.q.get(timeout=timeout)
                if items is None:
                    done = True
                else:
                    batch += items
                    size += sum(s for _, s in items)
                    first = first or time.monotonic()
            except queue.Empty:
                pass
            due = first is not None and (size >= self.batch_bytes or time.monotonic() - first >= self.batch_secs)
            if batch and (due or done) and self.error is None:
                try:
                    self._send(batch)
                except Exception as e:  # stop the run: no state is saved
                    self.error = e
                    net.error(str(e))
                batch, size, first = [], 0, None

    def finish(self):
        """Send the rest. Raise when a batch failed."""
        self.q.put(None)
        self.thread.join()
        if self.error:
            raise RuntimeError(f"upload failed: {self.error}")
        net.log(f"upload: {self.files} paths, {net.human(self.bytes)} sent in {self.batches} batches"
                f"{' (dry-run)' if self.dry_run else ''}")
        return self.files
