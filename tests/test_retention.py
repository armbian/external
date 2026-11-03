import unittest

import json
import os
import tempfile

from extpkg import pipeline, retention, status


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


class Removable(unittest.TestCase):
    PREV = {"files": [{"config": "gh"}, {"config": "rpi-off"}, {"config": "deleted"}, {"config": "other-shard"}]}
    PKGS = [{"name": "gh"}, {"name": "rpi-off"}, {"name": "other-shard"}]

    def plan(self, full):
        return {"entries": [{"config": "gh"}], "covered": ["gh", "rpi-off"], "shard": None, "full": full}

    def test_disabled_config_is_removable(self):
        names, deleted = pipeline.removable_configs(self.plan(False), self.PKGS, self.PREV)
        self.assertIn("rpi-off", names)
        self.assertNotIn("rpi-off", deleted)

    def test_deleted_config_only_in_full_run(self):
        names, deleted = pipeline.removable_configs(self.plan(True), self.PKGS, self.PREV)
        self.assertEqual(deleted, {"deleted"})
        names, deleted = pipeline.removable_configs(self.plan(False), self.PKGS, self.PREV)
        self.assertNotIn("deleted", names)

    def test_existing_config_of_another_shard_is_not_removable(self):
        names, _ = pipeline.removable_configs(self.plan(True), self.PKGS, self.PREV)
        self.assertNotIn("other-shard", names)


class CrossShard(unittest.TestCase):
    """armbian/external#17 review: a renamed config can move to another shard."""

    def test_path_listed_by_another_shard_stays(self):
        old = entry("code-old", "1.0")
        carried, removed = retention.plan_removal({"files": [old]}, [], [], {"code-old"}, {},
                                                  others={old["beta"], old["stable"]})
        self.assertEqual(removed, [])

    def test_deleted_config_waits_one_run(self):
        old = entry("code-old", "1.0")
        carried, removed = retention.plan_removal({"files": [old]}, [], [], {"code-old"}, {}, deleted={"code-old"})
        self.assertEqual(removed, [])
        self.assertEqual(carried[0]["carried"], "orphan-pending")
        # Next run: still deleted, no other shard lists the files: removed.
        carried, removed = retention.plan_removal({"files": carried}, [], [], {"code-old"}, {}, deleted={"code-old"})
        self.assertEqual(len(removed), 2)
        # Next run, but the renamed config's shard now lists them: kept.
        pending = [{**old, "carried": "orphan-pending"}]
        carried, removed = retention.plan_removal({"files": pending}, [], [], {"code-old"}, {},
                                                  deleted={"code-old"}, others={old["beta"], old["stable"]})
        self.assertEqual(removed, [])

    def test_unknown_other_shards_remove_nothing(self):
        carried, removed = retention.plan_removal({"files": [entry("code", "1.0")]}, [entry("code", "2.0")], [],
                                                  {"code"}, {}, others=None)
        self.assertEqual(removed, [])
        self.assertEqual(carried[0]["carried"], "pending-check")


class OtherPaths(unittest.TestCase):
    def test_reads_other_manifests(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(status.other_paths(d, "0/4"), set())      # no .sync yet
            os.makedirs(f"{d}/.sync")
            for n, path in (("0", "debs-beta/extra/noble-desktop/a_1_all.deb"),
                            ("1", "debs-beta/extra/noble-desktop/b_1_all.deb")):
                with open(f"{d}/.sync/manifest-shard-{n}.json", "w") as f:
                    json.dump({"files": [{"beta": path, "stable": None}]}, f)
            self.assertEqual(status.other_paths(d, "0/4"), {"debs-beta/extra/noble-desktop/b_1_all.deb"})


if __name__ == "__main__":
    unittest.main()
