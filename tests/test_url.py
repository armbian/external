import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from extpkg import net, pipeline

URL = "https://example.com/download?format=deb"


def build_deb(path, version):
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(f"{tmp}/DEBIAN")
        with open(f"{tmp}/DEBIAN/control", "w") as fh:
            fh.write(f"Package: discord\nVersion: {version}\nArchitecture: amd64\n"
                     "Maintainer: test <test@example.com>\nDescription: test\n")
        subprocess.run(["dpkg-deb", "--root-owner-group", "-b", tmp, path], check=True, capture_output=True)


class NoPublished:
    def version(self, *args):
        return None


@unittest.skipUnless(shutil.which("dpkg-deb"), "needs dpkg-deb")
class UrlName(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.pkg = {"name": "discord", "method": "url", "target": "desktop", "source": {"url": URL}}
        self.entry = {"config": "discord", "release": "noble", "arch": "amd64", "target": "desktop",
                      "dir": "extra/noble-desktop"}
        self.versions = iter(["0.0.1", "0.0.2"])

    def fake_download(self, url, path, headers=None):
        build_deb(path, next(self.versions))
        return net.sha256_file(path), os.path.getsize(path)

    def fetcher(self, run):
        f = pipeline.Fetcher([self.pkg], f"{self.tmp}/out{run}", f"{self.tmp}/cache", NoPublished())
        f.progress = net.Progress("test", 1)
        return f

    def cand(self, identity):
        return {"url": URL, "filename": "discord.deb", "sha256": None, "identity": identity,
                "signature": "none", "fixed_url": True}

    def place(self, f, cand):
        with mock.patch.object(net, "download", self.fake_download):
            f.group([(self.entry, cand)])
        return f.files[-1]

    def test_versioned_name(self):
        x = self.place(self.fetcher(1), self.cand("url:a"))
        self.assertEqual(x["filename"], "discord_0.0.1_amd64.deb")
        self.assertEqual(x["beta"], "debs-beta/extra/noble-desktop/discord_0.0.1_amd64.deb")

    def test_epoch_gives_a_new_name(self):
        self.assertEqual(pipeline.url_name("discord", "0.0.1", "amd64"), "discord_0.0.1_amd64.deb")
        self.assertEqual(pipeline.url_name("discord", "2:0.0.1", "amd64"), "discord_2%3a0.0.1_amd64.deb")
        self.assertNotEqual(pipeline.url_name("discord", "1:0.0.1", "amd64"),
                            pipeline.url_name("discord", "2:0.0.1", "amd64"))

    def test_repacked_url_keeps_the_url_name(self):
        """A repack with an epoch: the url name, so the next run sees it unchanged."""
        self.pkg["repack"] = {"packages": ["discord"], "epoch": 9}
        x = self.place(self.fetcher(1), self.cand("url:a"))
        self.assertEqual(x["filename"], "discord_9%3a0.0.1_amd64.deb")
        self.assertFalse(pipeline._legacy_name(self.pkg, x))

    def test_new_identity_downloads_again(self):
        self.place(self.fetcher(1), self.cand("url:a"))
        x = self.place(self.fetcher(2), self.cand("url:b"))
        self.assertEqual(x["version"], "0.0.2")

    def test_no_identity_downloads_again(self):
        self.place(self.fetcher(1), self.cand(None))
        x = self.place(self.fetcher(2), self.cand(None))
        self.assertEqual(x["version"], "0.0.2")

    def test_fixed_name_is_renamed(self):
        old = {"config": "discord", "release": "noble", "arch": "amd64", "target": "desktop",
               "package": "discord", "version": "0.0.1", "deb_arch": "amd64", "filename": "discord.deb",
               "source": URL, "upstream_id": "url:a"}
        f = self.fetcher(1)
        f.previous[("discord", "noble", "amd64", URL, "url:a")] = old
        x = self.place(f, self.cand("url:a"))
        self.assertFalse(x.get("unchanged"))
        self.assertEqual(x["filename"], "discord_0.0.1_amd64.deb")

    def test_versioned_name_stays_unchanged(self):
        f = self.fetcher(1)
        f.previous[("discord", "noble", "amd64", URL, "url:a")] = {
            "config": "discord", "release": "noble", "arch": "amd64", "package": "discord",
            "version": "0.0.1", "deb_arch": "amd64", "filename": "discord_0.0.1_amd64.deb"}
        x = self.place(f, self.cand("url:a"))
        self.assertTrue(x.get("unchanged"))


if __name__ == "__main__":
    unittest.main()
