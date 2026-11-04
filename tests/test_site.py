import json
import os
import shutil
import subprocess
import tempfile
import unittest

from extpkg import debfile, site

PKG = {"name": "tool", "method": "github", "source": {"url": "https://github.com/x/tool"},
       "releases": ["noble", "trixie"], "architectures": ["arm64", "amd64"], "target": "utils",
       "install": ["tool"]}


def entry(release, arch, stable, **extra):
    return {"config": "tool", "release": release, "arch": arch, "package": "tool", "version": "1.0",
            "deb_arch": arch, "stable": "debs/x.deb" if stable else None, "beta": "debs-beta/x.deb", **extra}


class Site(unittest.TestCase):
    def manifest(self, files, skipped=()):
        return {"shard-0": {"generated": "now", "releases": ["noble", "trixie"],
                            "files": files, "skipped": list(skipped)}}

    def test_states(self):
        files = [entry("noble", "arm64", True, description="A tool"), entry("noble", "amd64", False),
                 entry("trixie", "amd64", False, published="1.0"),
                 entry("trixie", "arm64", True, carried="keep")]
        skipped = [{"config": "tool", "release": "trixie", "arch": "arm64", "reason": "no package matched"}]
        p = site.collect([PKG], self.manifest(files, skipped))["packages"][0]
        self.assertEqual(p["description"], "A tool")
        self.assertEqual(p["releases"]["noble"]["arm64"]["state"], "stable")
        self.assertEqual(p["releases"]["noble"]["amd64"]["state"], "beta")
        self.assertEqual(p["releases"]["trixie"]["arm64"]["state"], "none")      # carried: old version
        self.assertEqual(p["releases"]["trixie"]["amd64"]["state"], "stable")   # stable has it
        self.assertEqual(p["status"], "ready")

    def test_missing_is_partial(self):
        p = site.collect([PKG], self.manifest([entry("noble", "arm64", True)]))["packages"][0]
        self.assertEqual(p["releases"]["trixie"]["arm64"]["state"], "missing")
        self.assertEqual(p["status"], "partial")

    def test_ready_and_describe(self):
        files = [entry(r, a, True) for r in ("noble", "trixie") for a in ("arm64", "amd64")]
        p = site.collect([PKG], self.manifest(files), lambda *k: "from index")["packages"][0]
        self.assertEqual(p["status"], "ready")
        self.assertEqual(p["description"], "from index")
        self.assertEqual(p["binaries"], ["tool"])

    def test_newest_version(self):
        files = [entry("noble", "arm64", True, version=v) for v in ("1.9", "1.10")]
        p = site.collect([PKG], self.manifest(files))["packages"][0]
        self.assertEqual(p["releases"]["noble"]["arm64"]["version"], "1.10")

    def test_disabled_and_missing(self):
        data = site.collect([{**PKG, "enabled": False}, {**PKG, "name": "other"}], self.manifest([]))
        self.assertEqual([p["status"] for p in data["packages"]], ["missing", "disabled"])

    def test_write_escapes_script(self):
        files = [entry("noble", "arm64", True, description="<!--<script></script><b> @GENERATED@")]
        data = site.collect([PKG], self.manifest(files))
        with tempfile.TemporaryDirectory() as d:
            site.write(data, d)
            page = open(os.path.join(d, "index.html")).read()
            self.assertNotIn("<!--<script>", page)
            self.assertNotIn("</script><b>", page)
            self.assertIn("\\u003cb> @GENERATED@", page)
            self.assertEqual(json.load(open(os.path.join(d, "packages.json")))["packages"][0]["name"], "tool")


@unittest.skipUnless(shutil.which("dpkg-deb"), "needs dpkg-deb")
class Control(unittest.TestCase):
    def test_description_first_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(f"{tmp}/root/DEBIAN")
            with open(f"{tmp}/root/DEBIAN/control", "w") as fh:
                fh.write("Package: tool\nVersion: 1.0\nArchitecture: all\nMaintainer: t <t@example.com>\n"
                         "Homepage: https://example.com\nDescription: A tool\n Long text: with a colon.\n")
            subprocess.run(["dpkg-deb", "--root-owner-group", "-b", f"{tmp}/root", f"{tmp}/t.deb"],
                           check=True, capture_output=True)
            f = debfile.control(f"{tmp}/t.deb")
        self.assertEqual((f["Description"], f["Homepage"]), ("A tool", "https://example.com"))
        self.assertNotIn("Long text", f)
