import itertools
import shutil
import subprocess
import unittest

from extpkg import config, debfile, debver, query

VERSIONS = [
    "1.0", "1.0-1", "1.0-2", "1:0.9", "9:156.0+build1-0ubuntu0.24.04.1~mt1armbian1",
    "159.0+build1-0ubuntu0.24.04.1~mt1", "1:140.16.0+build1-0ubuntu0.24.04.1~mt1",
    "1:140.17.0+build3-0ubuntu0.24.04.1~mt1", "1.0~rc1", "1.0~~", "1.0+dfsg", "1.0a",
    "21.0.13.0.3-5", "21.0.13-3", "2.4.4-1", "1.144.1-1793549175", "0", "1.0.0",
]


class DebVer(unittest.TestCase):
    def test_known(self):
        self.assertGreater(debver.compare("1:140.16", "140.17"), 0)  # epoch wins
        self.assertLess(debver.compare("1.0~rc1", "1.0"), 0)
        self.assertGreater(debver.compare("9:156.0", "159.0"), 0)
        self.assertEqual(debver.compare("1.0", "1.0-0"), 0)

    @unittest.skipUnless(shutil.which("dpkg"), "dpkg not installed")
    def test_against_dpkg(self):
        for a, b in itertools.permutations(VERSIONS, 2):
            ours = debver.compare(a, b) > 0
            r = subprocess.run(["dpkg", "--compare-versions", a, "gt", b])
            self.assertEqual(ours, r.returncode == 0, f"{a} > {b}")


class Query(unittest.TestCase):
    def match(self, q, **pkg):
        return query.compile_query(q)(pkg)

    def test_glob_or(self):
        q = "Name (% chromium) | Name (% chromium-*)"
        self.assertTrue(self.match(q, Package="chromium"))
        self.assertTrue(self.match(q, Package="chromium-l10n"))
        self.assertFalse(self.match(q, Package="chromium2"))

    def test_space_inside(self):
        self.assertTrue(self.match("Name (% pi-bluetooth* ) | Name (% bluez-firmware)", Package="pi-bluetooth"))

    def test_version_and(self):
        q = "Name (% zulu21*), $Version (< 22.0)"
        self.assertTrue(self.match(q, Package="zulu21-jdk", Version="21.0.13-3"))
        self.assertTrue(self.match(q, Package="zulu21-jdk", Version="22.0"))   # '<' is '<=' in aptly
        self.assertFalse(self.match(q, Package="zulu21-jdk", Version="22.0.1"))

    def test_bare_name(self):
        self.assertTrue(self.match("unudhcpd", Package="unudhcpd"))
        self.assertFalse(query.has_name_or_version("unudhcpd"))
        self.assertTrue(query.has_name_or_version("Name (% x)"))

    def test_bad(self):
        with self.assertRaises(query.QueryError):
            query.compile_query("Name (% x")


class Debug(unittest.TestCase):
    def test_is_debug(self):
        for name in ("firefox-dbg", "thunderbird-gnome-support-dbg", "libfoo1-dbgsym"):
            self.assertTrue(config.is_debug(name), name)
        for name in ("firefox", "firefox-dev", "dbgview", "gdb"):
            self.assertFalse(config.is_debug(name), name)


class Expand(unittest.TestCase):
    def test_skip(self):
        pkg = {"releases": ["noble", "trixie"], "architectures": ["amd64", "armhf"], "skip": ["trixie/armhf"]}
        self.assertEqual(sorted(config.expand(pkg, [])),
                         [("noble", "amd64"), ("noble", "armhf"), ("trixie", "amd64")])


class Repack(unittest.TestCase):
    def test_version(self):
        self.assertEqual(debfile.repack_version("159.0+build1-0ubuntu0.24.04.1~mt1", 9, "armbian1"),
                         "9:159.0+build1-0ubuntu0.24.04.1~mt1armbian1")
        self.assertEqual(debfile.repack_version("1:2.0-1", None, "armbian1"), "1:2.0-1armbian1")


if __name__ == "__main__":
    unittest.main()
