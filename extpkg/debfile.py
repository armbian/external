"""Read and repack .deb files with dpkg-deb."""

import os
import re
import shutil
import subprocess
import tempfile

from . import debver, net


class DebError(RuntimeError):
    pass


def control(path):
    """Return Package, Version and Architecture of a .deb."""
    r = subprocess.run(["dpkg-deb", "-f", path, "Package", "Version", "Architecture"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise DebError(f"{os.path.basename(path)} is not a valid .deb: {r.stderr.strip()}")
    fields = {}
    for line in r.stdout.splitlines():
        k, _, v = line.partition(":")
        fields[k.strip()] = v.strip()
    if not all(fields.get(k) for k in ("Package", "Version", "Architecture")):
        raise DebError(f"{os.path.basename(path)}: control is missing Package, Version or Architecture")
    return fields


def repack_version(version, epoch=None, suffix=""):
    """New version: optional new epoch, upstream version unchanged, suffix appended."""
    base = debver.without_epoch(version) + (suffix or "")
    if epoch is None:
        e, _, _ = debver.split(version)
        epoch = e or None
    return f"{epoch}:{base}" if epoch else base


def repack(path, new_version, out_dir):
    """Rebuild a .deb with a new Version. Return the new file path."""
    fields = control(path)
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "root")
        # fakeroot keeps file ownership through extract and build. Without it,
        # build with root:root ownership, as a normal package build does.
        if net.have("fakeroot"):
            script = ('dpkg-deb -R "$1" "$2" && '
                      'sed -i "s/^Version: .*/Version: $3/" "$2/DEBIAN/control" && '
                      'dpkg-deb -Zxz -b "$2" "$4"')
            cmd = ["fakeroot", "sh", "-c", script, "sh", path, root, new_version, tmp + "/out.deb"]
        else:
            cmd = ["sh", "-c",
                   'dpkg-deb -R "$1" "$2" && '
                   'sed -i "s/^Version: .*/Version: $3/" "$2/DEBIAN/control" && '
                   'dpkg-deb --root-owner-group -Zxz -b "$2" "$4"',
                   "sh", path, root, new_version, tmp + "/out.deb"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise DebError(f"repack of {os.path.basename(path)} failed: {r.stderr.strip()[-400:]}")
        dest = os.path.join(out_dir, deb_name(fields["Package"], new_version, fields["Architecture"]))
        shutil.move(tmp + "/out.deb", dest)
    got = control(dest)["Version"]
    if got != new_version:
        raise DebError(f"repack wrote version {got}, expected {new_version}")
    return dest


SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+~:-]*\.deb$")


def deb_name(package, version, arch):
    """Debian file name: <package>_<version without epoch>_<arch>.deb."""
    name = f"{package}_{debver.without_epoch(version)}_{arch}.deb"
    if not SAFE_NAME.match(name):
        raise DebError(f"unsafe file name from control fields: {name!r}")
    return name
