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


class RetryFailures(unittest.TestCase):
    """Earlier failures with unchanged files: check again, or keep."""

    def files(self, stable):
        return {"files": [{"config": "ff", "release": "resolute", "arch": "arm64",
                           "stable": "pool/ff.deb" if stable else None, "beta": "pool/ff.deb"}]}

    PREV = {"depcheck": [
        {"config": "ff", "release": "resolute", "arch": "arm64", "ok": False, "packages": ["ff=1"], "message": "x"},
        {"config": "ok", "release": "resolute", "arch": "arm64", "ok": True, "packages": ["ok=1"], "message": ""},
    ]}

    def test_stable_files_are_checked_again(self):
        retry, carried = depcheck.retry_failures(self.files(True), self.PREV, {}, set())
        self.assertEqual([x["packages"] for x in retry], [["ff=1"]])
        self.assertEqual(carried, [])

    def test_beta_only_files_stay_failed(self):
        retry, carried = depcheck.retry_failures(self.files(False), self.PREV, {}, set())
        self.assertEqual(retry, [])
        self.assertEqual([(x["config"], x["ok"]) for x in carried], [("ff", False)])

    def test_new_files_replace_the_old_failure(self):
        groups = {("ff", "resolute", "arm64"): [{}]}
        self.assertEqual(depcheck.retry_failures(self.files(True), self.PREV, groups, set()), ([], []))

    def test_config_gone_or_skipped(self):
        self.assertEqual(depcheck.retry_failures({"files": []}, self.PREV, {}, set()), ([], []))
        self.assertEqual(depcheck.retry_failures(self.files(True), self.PREV, {}, {"ff"}), ([], []))

    def test_no_previous(self):
        self.assertEqual(depcheck.retry_failures(self.files(True), None, {}, set()), ([], []))
