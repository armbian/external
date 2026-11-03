import unittest

from extpkg import retention


def entry(config, version, release="noble", arch="amd64", package=None, stable=True, name=None):
    package = package or config
    name = name or f"{package}_{version}_{arch}.deb"
    d = f"extra/{release}-desktop"
    return {"config": config, "release": release, "arch": arch, "package": package, "version": version,
            "beta": f"debs-beta/{d}/{name}", "stable": f"debs/{d}/{name}" if stable else None}


def run(previous, files, skipped=(), planned=None, keep=None):
    planned = planned or {x["config"] for x in files}
    return retention.plan_removal({"files": previous}, files, list(skipped), planned, keep or {})


class Retention(unittest.TestCase):
    def test_new_version_removes_old(self):
        carried, removed = run([entry("code", "1.144.0")], [entry("code", "1.144.1")])
        self.assertEqual(removed, ["debs-beta/extra/noble-desktop/code_1.144.0_amd64.deb",
                                   "debs/extra/noble-desktop/code_1.144.0_amd64.deb"])
        self.assertEqual(carried, [])

    def test_unchanged_stays(self):
        _, removed = run([entry("gh", "2.103.3")], [entry("gh", "2.103.3")])
        self.assertEqual(removed, [])

    def test_failed_run_keeps_old(self):
        carried, removed = run([entry("code", "1.144.0")], [],
                               skipped=[{"config": "code", "release": "noble", "arch": "amd64"}],
                               planned={"code"})
        self.assertEqual(removed, [])
        self.assertEqual(carried[0]["carried"], "failed")

    def test_not_planned_is_carried(self):
        carried, removed = run([entry("code", "1.144.0")], [entry("gh", "2.103.3")])
        self.assertEqual(removed, [])
        self.assertEqual(carried[0]["carried"], "not-planned")

    def test_keep_two(self):
        prev = [entry("code", "1.144.0"), entry("code", "1.143.0")]
        carried, removed = run(prev, [entry("code", "1.144.1")], keep={"code": 2})
        self.assertEqual([c["version"] for c in carried], ["1.144.0"])
        self.assertEqual(removed, ["debs-beta/extra/noble-desktop/code_1.143.0_amd64.deb",
                                   "debs/extra/noble-desktop/code_1.143.0_amd64.deb"])

    def test_shared_all_path_stays(self):
        # One _all.deb in one directory for arm64 and armhf. Only armhf has a new version.
        shared = "raspinfo_1_all.deb"
        prev = [entry("rpi", "1", arch="arm64", package="raspinfo", name=shared),
                entry("rpi", "1", arch="armhf", package="raspinfo", name=shared)]
        cur = [entry("rpi", "1", arch="arm64", package="raspinfo", name=shared),
               entry("rpi", "2", arch="armhf", package="raspinfo", name="raspinfo_2_all.deb")]
        _, removed = run(prev, cur)
        self.assertEqual(removed, [])

    def test_dropped_package_removed(self):
        prev = [entry("ff", "1", package="firefox-locale-xx"), entry("ff", "1", package="firefox")]
        _, removed = run(prev, [entry("ff", "2", package="firefox")])
        self.assertIn("debs-beta/extra/noble-desktop/firefox-locale-xx_1_amd64.deb", removed)

    def test_no_previous(self):
        self.assertEqual(retention.plan_removal(None, [entry("code", "1")], [], {"code"}, {}), ([], []))

    def test_safe_path(self):
        self.assertTrue(retention.safe_path("debs/extra/noble-utils/a_1_all.deb"))
        for bad in ("debs/../x.deb", "/debs/a.deb", "other/a.deb", "debs/a.txt", "debs//a.deb"):
            self.assertFalse(retention.safe_path(bad), bad)


if __name__ == "__main__":
    unittest.main()
