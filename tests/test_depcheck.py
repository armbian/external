import os
import tempfile
import unittest
from types import SimpleNamespace

from extpkg import depcheck


class Depcheck(unittest.TestCase):
    def test_distro_from_build(self):
        with tempfile.TemporaryDirectory() as d:
            for rel, name in (("noble", "Ubuntu noble 24.04"), ("trixie", "Debian 13 Trixie")):
                os.makedirs(f"{d}/config/distributions/{rel}")
                with open(f"{d}/config/distributions/{rel}/name", "w") as f:
                    f.write(name)
            self.assertEqual(depcheck.distro_of("noble", d), "ubuntu")
            self.assertEqual(depcheck.distro_of("trixie", d), "debian")
        self.assertEqual(depcheck.distro_of("bookworm", None), "debian")
        self.assertEqual(depcheck.distro_of("jammy", None), "ubuntu")

    def test_targets(self):
        files = [{"package": "chromium", "version": "2"}, {"package": "chromium-common", "version": "2"}]
        self.assertEqual(depcheck._targets(files, ["chromium"]), ["chromium=2"])
        self.assertEqual(depcheck._targets(files, ["other"]), ["chromium=2", "chromium-common=2"])

    def test_why_puts_cause_first(self):
        r = SimpleNamespace(stdout="NOTE: This is only a simulation!\n"
                                   " x : Depends: libc6 (>= 2.32) but it is not going to be installed\n"
                                   "     Depends: libcamera0.7 (>= 0.7.2) but it is not installable\n",
                            stderr="E: Unable to satisfy dependencies.\n")
        why = depcheck._why(r)
        self.assertTrue(why.startswith("Depends: libcamera0.7"), why)
        self.assertNotIn("NOTE", why)
        self.assertNotIn("|", why)


if __name__ == "__main__":
    unittest.main()
