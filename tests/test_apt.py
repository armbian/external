import hashlib
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


if __name__ == "__main__":
    unittest.main()
