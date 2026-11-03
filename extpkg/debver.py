"""Debian version comparison, ported from dpkg (lib/dpkg/version.c)."""

from functools import total_ordering


def _order(c):
    if c.isdigit():
        return 0
    if c.isalpha():
        return ord(c)
    if c == "~":
        return -1
    return ord(c) + 256


def _verrevcmp(a, b):
    i = j = 0
    la, lb = len(a), len(b)
    while i < la or j < lb:
        first_diff = 0
        while (i < la and not a[i].isdigit()) or (j < lb and not b[j].isdigit()):
            ac = _order(a[i]) if i < la else 0
            bc = _order(b[j]) if j < lb else 0
            if ac != bc:
                return ac - bc
            i += 1
            j += 1
        while i < la and a[i] == "0":
            i += 1
        while j < lb and b[j] == "0":
            j += 1
        while i < la and a[i].isdigit() and j < lb and b[j].isdigit():
            if not first_diff:
                first_diff = ord(a[i]) - ord(b[j])
            i += 1
            j += 1
        if i < la and a[i].isdigit():
            return 1
        if j < lb and b[j].isdigit():
            return -1
        if first_diff:
            return first_diff
    return 0


def split(version):
    """Return (epoch, upstream, revision)."""
    version = version.strip()
    epoch = 0
    if ":" in version:
        e, version = version.split(":", 1)
        epoch = int(e)
    if "-" in version:
        upstream, revision = version.rsplit("-", 1)
    else:
        upstream, revision = version, ""
    return epoch, upstream, revision


def compare(a, b):
    """Return <0, 0 or >0, like dpkg --compare-versions."""
    ea, ua, ra = split(a)
    eb, ub, rb = split(b)
    if ea != eb:
        return ea - eb
    return _verrevcmp(ua, ub) or _verrevcmp(ra, rb)


def without_epoch(version):
    return version.split(":", 1)[1] if ":" in version else version


@total_ordering
class Version:
    """Sortable wrapper: sorted(versions, key=Version)."""

    def __init__(self, v):
        self.v = v

    def __eq__(self, other):
        return compare(self.v, other.v) == 0

    def __lt__(self, other):
        return compare(self.v, other.v) < 0

    def __repr__(self):
        return self.v
