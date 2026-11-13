import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest

from extpkg import apt, net

NEW = b"Package: code\nVersion: 2\n"
OLD = b"Package: code\nVersion: 1\n"
WANT = hashlib.sha256(NEW).hexdigest()


class FakeRepo(apt.Repo):
    """The CDN serves the old index at the normal path, the new one by hash."""

    def __init__(self, by_hash, by_hash_exists=True):
        super().__init__("https://example.org", "stable", ["main"], keyring=None)
        self.by_hash = by_hash
        self.by_hash_exists = by_hash_exists

    def _get(self, path):
        if "/by-hash/SHA256/" in path:
            if not self.by_hash_exists:
                raise net.FetchError("404")
            return NEW if path.endswith(WANT) else b""
        return OLD


class Index(unittest.TestCase):
    def test_by_hash_wins_over_stale_path(self):
        self.assertEqual(FakeRepo(True)._index("main/binary-amd64/Packages", "", WANT, len(NEW)), NEW)

    def test_stale_path_without_by_hash_fails(self):
        with self.assertRaises(apt.AptError):
            FakeRepo(False)._index("main/binary-amd64/Packages", "", WANT, len(NEW))

    def test_missing_by_hash_falls_back(self):
        with self.assertRaises(apt.AptError):   # falls back to the (stale) normal path
            FakeRepo(True, by_hash_exists=False)._index("main/binary-amd64/Packages", "", WANT, len(NEW))


class Flat(unittest.TestCase):
    def test_suite_with_slash_is_flat(self):
        # Sublime Text: Release in apt/stable/, files relative to the URL.
        r = apt.Repo("https://download.sublimetext.com/", "apt/stable/", [], None)
        self.assertTrue(r.flat)
        self.assertEqual(r._base(), "https://download.sublimetext.com/apt/stable")
        self.assertEqual(r.pool_url("files/a.deb"), "https://download.sublimetext.com/files/a.deb")


def _gpg(home, *args, data=None):
    return subprocess.run(["gpg", "--homedir", home, "--batch", "--quiet", *args],
                          input=data, capture_output=True, check=True).stdout


class Select(unittest.TestCase):
    STANZAS = [
        {"Package": "nvidia-open", "Version": "1", "Architecture": "amd64",
         "Depends": "nvidia-kernel-open-dkms | nvidia-kernel-dkms"},
        {"Package": "nvidia-kernel-open-dkms", "Version": "1", "Architecture": "amd64", "Depends": "dkms (>= 3)"},
        {"Package": "nvidia-kernel-dkms", "Version": "1", "Architecture": "amd64", "Depends": "dkms"},
        {"Package": "dkms", "Version": "3", "Architecture": "all"},
    ]

    def names(self, **kw):
        return [st["Package"] for st in apt.select(self.STANZAS, "Name (= nvidia-open)", "amd64", True, **kw)]

    def test_with_deps_takes_the_first_alternative(self):
        self.assertEqual(self.names(), ["dkms", "nvidia-kernel-open-dkms", "nvidia-open"])

    def test_exclude_leaves_out_dependencies(self):
        self.assertEqual(self.names(exclude=["dkms"]), ["nvidia-kernel-open-dkms", "nvidia-open"])

    def test_deps_of_the_picked_version_only(self):
        old = {"Package": "nvidia-open", "Version": "0", "Architecture": "amd64", "Depends": "nvidia-kernel-dkms"}
        names = [st["Package"] for st in apt.select(self.STANZAS + [old], "Name (= nvidia-open)", "amd64", True)]
        self.assertNotIn("nvidia-kernel-dkms", names)

    def test_exclude_glob(self):
        self.assertEqual(self.names(exclude=["nvidia-kernel-*"]), ["nvidia-open"])


@unittest.skipUnless(shutil.which("gpg") and shutil.which("gpgv"), "needs gpg and gpgv")
class Signature(unittest.TestCase):
    def test_more_than_40_key_files(self):
        # gpgv ignores keyring files after the 40th. The signer is the last file.
        with tempfile.TemporaryDirectory() as tmp:
            home, keys = os.path.join(tmp, "home"), os.path.join(tmp, "keys")
            os.mkdir(home, 0o700)
            os.mkdir(keys)
            for uid in ("other@example.org", "signer@example.org"):
                _gpg(home, "--passphrase", "", "--quick-gen-key", uid, "ed25519", "sign", "never")
            other = _gpg(home, "--export", "other@example.org")
            for i in range(44):
                with open(os.path.join(keys, f"k{i:02}.gpg"), "wb") as f:
                    f.write(other)
            with open(os.path.join(keys, "zz.gpg"), "wb") as f:
                f.write(_gpg(home, "--export", "signer@example.org"))
            signed = _gpg(home, "--local-user", "signer@example.org", "--clearsign", data=b"Suite: stable\n")
            self.assertTrue(apt.Keyring(keys).verify(signed))


if __name__ == "__main__":
    unittest.main()
