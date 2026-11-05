import json
import os
import shutil
import subprocess
import tempfile
import unittest

import yaml

from extpkg import builder, config, net, pipeline, source

DSC = "https://deb.debian.org/debian/pool/main/f/fastfetch/fastfetch_2.69.0+dfsg-1.dsc"


def build_deb(path, package, version, arch="amd64"):
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(f"{tmp}/DEBIAN")
        with open(f"{tmp}/DEBIAN/control", "w") as fh:
            fh.write(f"Package: {package}\nVersion: {version}\nArchitecture: {arch}\n"
                     "Maintainer: test <test@example.com>\nDescription: test\n")
        subprocess.run(["dpkg-deb", "--root-owner-group", "-b", tmp, path], check=True, capture_output=True)


class Version(unittest.TestCase):
    def test_tag(self):
        self.assertEqual(source.tag_version("2.70.0"), "2.70.0")
        self.assertEqual(source.tag_version("v1.2.3"), "1.2.3")
        self.assertEqual(source.tag_version("mesa-26.0.1"), "26.0.1")
        self.assertEqual(source.tag_version("1.0-rc1"), "1.0~rc1")

    def test_packaging_only(self):
        self.assertEqual(source.version({}, "noble", "2.69.0+dfsg-1"), "2.69.0+dfsg-1+armbian1~noble")

    def test_upstream_on_packaging(self):
        up = {"version": "2.70.0"}
        self.assertEqual(source.version({"revision": 2}, "trixie", "2.69.0+dfsg-1", up), "2.70.0-1+armbian2~trixie")
        self.assertEqual(source.version({}, "noble", "1:26.0.8-1ubuntu0.3", {"version": "27.0.0~git2611031200.abc"}),
                         "1:27.0.0~git2611031200.abc-1ubuntu0.3+armbian1~noble")

    def test_url_version(self):
        self.assertEqual(source.url_version("1.0.70\n"), "1.0.70")
        self.assertEqual(source.url_version("v2.1.311"), "2.1.311")
        with self.assertRaises(net.FetchError):
            source.url_version("<html>")

    def test_local_packaging(self):
        self.assertEqual(source.version({}, "sid", None, {"version": "1.0"}), "1.0-0+armbian1~sid")


class Config(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def load(self, doc):
        path = os.path.join(self.dir, f"{doc['name']}.yaml")
        with open(path, "w") as f:
            yaml.safe_dump(doc, f)
        return config.load_one(path)

    def base(self, **kw):
        return {"name": "x", "method": "build", "releases": "all", "architectures": ["arm64"], **kw}

    def test_packaging(self):
        pkg = self.load(self.base(packaging={"url": "https://deb.debian.org/debian", "suite": "sid", "package": "x"}))
        self.assertEqual(pkg["packaging"]["components"], [])

    def test_needs_packaging_or_local_debian(self):
        with self.assertRaises(config.ConfigError):
            self.load(self.base(upstream={"url": "https://example.com/x.git", "ref": "v1"}))
        os.makedirs(os.path.join(self.dir, "x", "debian"))
        open(os.path.join(self.dir, "x", "debian", "control"), "w").close()
        self.load(self.base(upstream={"url": "https://example.com/x.git", "ref": "v1"}))

    def test_rejects(self):
        pk = {"url": "https://deb.debian.org/debian", "suite": "sid", "package": "x"}
        for bad in ({"architectures": ["armhf"]}, {"filter": "Name (% x)"}, {"source": {"url": "u"}},
                    {"repositories": ["testing"]}, {"repositories": []},
                    {"upstream": {"url": "u", "rebase": {"url": "v"}}}, {"revision": 0}):
            with self.subTest(bad=bad), self.assertRaises(config.ConfigError):
                self.load({**self.base(packaging=pk), **bad})

    def test_version_url(self):
        os.makedirs(os.path.join(self.dir, "x", "debian"))
        open(os.path.join(self.dir, "x", "debian", "control"), "w").close()
        self.load(self.base(upstream={"version_url": "https://example.com/stable"}))
        for bad in ({"version_url": "u", "url": "v"}, {"version_url": "u", "ref": "v1"}):
            with self.subTest(bad=bad), self.assertRaises(config.ConfigError):
                self.load(self.base(upstream=bad))

    def test_mirror_rejects_build_keys(self):
        with self.assertRaises(config.ConfigError):
            self.load({"name": "x", "method": "github", "source": {"url": "https://github.com/a/b"},
                       "releases": "all", "architectures": ["arm64"], "revision": 2})

    def test_local_hash(self):
        pkg = {"name": "x"}
        self.assertEqual(source.local_hash(pkg, self.dir), "")
        os.makedirs(os.path.join(self.dir, "x", "patches"))
        with open(os.path.join(self.dir, "x", "patches", "series"), "w") as f:
            f.write("a.patch\n")
        h1 = source.local_hash(pkg, self.dir)
        with open(os.path.join(self.dir, "x", "patches", "series"), "w") as f:
            f.write("b.patch\n")
        self.assertNotEqual(h1, source.local_hash(pkg, self.dir))


class Wraps(unittest.TestCase):
    def test_globs(self):
        with tempfile.TemporaryDirectory() as tree:
            os.makedirs(f"{tree}/subprojects")
            for n in ("venus-protocol", "xml-rs", "paste-1-rs", "zlib"):
                open(f"{tree}/subprojects/{n}.wrap", "w").close()
            self.assertEqual(builder._wraps(tree, ["venus-protocol", "*-rs"]), ["paste-1-rs", "venus-protocol", "xml-rs"])
            with self.assertRaises(builder.BuildError):
                builder._wraps(tree, ["nothing-*"])


class Changelog(unittest.TestCase):
    def test_entry(self):
        with tempfile.TemporaryDirectory() as tree:
            os.makedirs(f"{tree}/debian")
            with open(f"{tree}/debian/control", "w") as f:
                f.write("Source: fastfetch\n")
            with open(f"{tree}/debian/changelog", "w") as f:
                f.write("fastfetch (2.69.0+dfsg-1) unstable; urgency=medium\n")
            b = {"version": "2.70.0-1+armbian1~noble", "packaged": "2.69.0+dfsg-1",
                 "upstream": {"url": "u", "ref": "2.70.0", "commit": "17bb3fd2384bd814", "rebase": None}}
            builder._changelog(tree, b, "noble")
            text = open(f"{tree}/debian/changelog").read()
        self.assertTrue(text.startswith("fastfetch (2.70.0-1+armbian1~noble) noble; urgency=medium"))
        self.assertIn("fastfetch (2.69.0+dfsg-1) unstable", text)


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                   capture_output=True)


def commit(repo, name, text):
    with open(os.path.join(repo, name), "w") as f:
        f.write(text)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", name)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()


@unittest.skipUnless(shutil.which("git"), "needs git")
class Upstream(unittest.TestCase):
    """A fork rebased onto the branch it came from."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.base = os.path.join(self.tmp, "base")
        git(self.tmp, "init", "-q", "-b", "main", self.base)
        commit(self.base, "a", "1\n")
        self.fork = os.path.join(self.tmp, "fork")
        git(self.tmp, "clone", "-q", "-b", "main", self.base, self.fork)
        git(self.fork, "checkout", "-q", "-b", "feature")
        self.fork_head = commit(self.fork, "b", "fork\n")
        self.base_head = commit(self.base, "c", "new upstream\n")

    def up(self, **kw):
        return {"url": f"file://{self.fork}", "ref": "feature", "commit": self.fork_head,
                "rebase": {"url": f"file://{self.base}", "ref": "main", "commit": self.base_head}, **kw}

    def test_rebase(self):
        tree = os.path.join(self.tmp, "tree")
        builder._upstream(self.up(), tree)
        self.assertEqual(sorted(os.listdir(tree)), ["a", "b", "c"])

    def test_conflict_fails(self):
        commit(self.base, "b", "conflict\n")
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.base, capture_output=True, text=True).stdout.strip()
        up = self.up()
        up["rebase"]["commit"] = head
        with self.assertRaises(builder.BuildError):
            builder._upstream(up, os.path.join(self.tmp, "tree"))

    def test_version_file(self):
        self.assertEqual(source.file_version("27.0.0-devel\n"), "27.0.0")
        self.assertEqual(source.file_version("26.3.0-rc1"), "26.3.0~rc1")
        commit(self.base, "VERSION", "27.1.0-devel\n")
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.base, capture_output=True, text=True).stdout.strip()
        source._cache.clear()
        # Without rebase, the fork's own VERSION. With rebase, the base's.
        with self.assertRaises(net.FetchError):
            source.upstream({"url": f"file://{self.fork}", "ref": "feature", "version_file": "VERSION"})
        info = source.upstream({"url": f"file://{self.fork}", "ref": "feature", "version_file": "VERSION",
                                "meson_subprojects": ["venus-protocol"],
                                "rebase": {"url": f"file://{self.base}", "ref": "main"}})
        self.assertTrue(info["version"].startswith("27.1.0~git"))
        self.assertEqual(info["rebase"]["commit"], head)
        self.assertEqual(info["meson_subprojects"], ["venus-protocol"])

    def test_resolve_branch_version(self):
        source._cache.clear()
        info = source.upstream({"url": f"file://{self.fork}", "ref": "feature", "version": "2.0",
                                "rebase": {"url": f"file://{self.base}", "ref": "main"}})
        self.assertEqual(info["commit"], self.fork_head)
        self.assertEqual(info["rebase"]["commit"], self.base_head)
        self.assertRegex(info["version"], r"^2\.0~git\d{12}\.[0-9a-f]{10}$")
        with self.assertRaises(ValueError):
            source.upstream({"url": f"file://{self.fork}", "ref": "feature"})


@unittest.skipUnless(shutil.which("git"), "needs git")
class LatestTag(unittest.TestCase):
    def test_newest_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "r")
            git(tmp, "init", "-q", "-b", "main", repo)
            commit(repo, "a", "1")
            for tag in ("mesa-26.2.5", "mesa-26.2.10", "mesa-26.3.0-rc3", "18.0-branchpoint", "other-99.0"):
                git(repo, "tag", tag)
            self.assertEqual(source.latest_tag(f"file://{repo}", "mesa-*"), "mesa-26.2.10")
            self.assertEqual(source.latest_tag(f"file://{repo}"), "other-99.0")
            with self.assertRaises(net.FetchError):
                source.latest_tag(f"file://{repo}", "none-*")


class Matrix(unittest.TestCase):
    """build-matrix: dependencies build first, and together with what needs them."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        pk = {"url": "https://deb.debian.org/debian", "suite": "sid", "package": "x"}
        for name, extra in (("libdrm", {}), ("mesa", {"build_depends": ["libdrm"]})):
            with open(os.path.join(self.tmp, f"{name}.yaml"), "w") as f:
                yaml.safe_dump({"name": name, "method": "build", "packaging": pk, "releases": ["resolute"],
                                "architectures": ["amd64"], **extra}, f)
        self.plan = os.path.join(self.tmp, "plan.json")
        entries = [{"config": n, "release": "resolute", "arch": "amd64", "target": "main",
                    "candidates": [{"url": n, "identity": f"{n}-1", "build": {"version": "1"}}]}
                   for n in ("libdrm", "mesa")]
        with open(self.plan, "w") as f:
            json.dump({"entries": entries}, f)

    def run_matrix(self, previous_ids, version="0", live=True):
        prev = os.path.join(self.tmp, "prev.json")
        with open(prev, "w") as f:
            json.dump({"files": [{"config": n, "release": "resolute", "arch": "amd64", "source": n,
                                  "upstream_id": i, "filename": f"{n}.deb", "version": version}
                                 for n, i in previous_ids]}, f)
        return subprocess.run(["python3", "-m", "extpkg", "build-matrix", "--configs", self.tmp, "--plan", self.plan,
                               "--previous", prev] + (["--live"] if live else []), capture_output=True, text=True)

    def matrix(self, previous_ids):
        r = self.run_matrix([(n, f"{n}-1") for n in previous_ids])
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.loads(r.stdout)
        return [j["config"] for j in doc["deps"]], [j["config"] for j in doc["builds"]]

    def test_both_new(self):
        self.assertEqual(self.matrix([]), (["libdrm"], ["mesa"]))

    def test_mesa_changed_builds_libdrm_too(self):
        self.assertEqual(self.matrix(["libdrm"]), (["libdrm"], ["mesa"]))

    def test_libdrm_changed_alone(self):
        self.assertEqual(self.matrix(["mesa"]), (["libdrm"], []))

    def test_nothing_changed(self):
        self.assertEqual(self.matrix(["libdrm", "mesa"]), ([], []))

    def test_changed_inputs_need_a_new_version(self):
        # mesa-1 is planned; mesa-0 with the same version "1" is uploaded.
        r = self.run_matrix([("libdrm", "libdrm-1"), ("mesa", "mesa-0")], version="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Increase revision in build/mesa.yaml", r.stderr + r.stdout)
        # A dry run warns and builds.
        r = self.run_matrix([("libdrm", "libdrm-1"), ("mesa", "mesa-0")], version="1", live=False)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout)["builds"][0]["config"], "mesa")

    def test_dependency_with_dependencies_is_rejected(self):
        with open(os.path.join(self.tmp, "libdrm.yaml")) as f:
            doc = yaml.safe_load(f)
        doc["build_depends"] = ["mesa"]
        with open(os.path.join(self.tmp, "libdrm.yaml"), "w") as f:
            yaml.safe_dump(doc, f)
        with self.assertRaises(config.ConfigError):
            config.load_all(self.tmp)


class NoPublished:
    def version(self, *args):
        return None


@unittest.skipUnless(shutil.which("dpkg-deb"), "needs dpkg-deb")
class Publish(unittest.TestCase):
    """Place the files of a build, as the publish job does."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.pkg = {"name": "fastfetch", "method": "build", "target": "utils"}
        self.entry = {"config": "fastfetch", "release": "noble", "arch": "amd64", "target": "utils",
                      "dir": "extra/noble-utils"}
        self.cand = {"url": DSC, "filename": "fastfetch_2.69.0+dfsg-1.dsc", "sha256": None,
                     "identity": "build1|a|b|-|2.70.0-1+armbian1~noble", "signature": "verified",
                     "build": {"version": "2.70.0-1+armbian1~noble"}}

    def built(self, identity, packages=("fastfetch",)):
        d = os.path.join(self.tmp, "built", "fastfetch", "noble", "amd64")
        os.makedirs(d, exist_ok=True)
        files = []
        for p in packages:
            name = f"{p}_2.70.0-1+armbian1~noble_amd64.deb"
            build_deb(os.path.join(d, name), p, "2.70.0-1+armbian1~noble")
            files.append(name)
        with open(os.path.join(d, "build.json"), "w") as f:
            json.dump({"identity": identity, "version": "2.70.0-1+armbian1~noble", "files": files}, f)

    def fetcher(self, previous=None):
        f = pipeline.Fetcher([self.pkg], os.path.join(self.tmp, "out"), os.path.join(self.tmp, "cache"), NoPublished())
        f.progress = net.Progress("test", 1)
        f.built = os.path.join(self.tmp, "built")
        f.previous = pipeline.index_previous(previous)
        return f

    def test_places_every_file(self):
        self.built(self.cand["identity"], ("fastfetch", "fastfetch-extra"))
        f = self.fetcher()
        f.group([(self.entry, self.cand)])
        self.assertEqual(sorted(x["beta"] for x in f.files), [
            "debs-beta/extra/noble-utils/fastfetch-extra_2.70.0-1+armbian1~noble_amd64.deb",
            "debs-beta/extra/noble-utils/fastfetch_2.70.0-1+armbian1~noble_amd64.deb"])
        self.assertEqual({x["upstream_id"] for x in f.files}, {self.cand["identity"]})

    def test_repositories(self):
        self.built(self.cand["identity"])
        for repos, beta, stable in ((["beta"], True, False), (["stable"], False, True), (["stable", "beta"], True, True)):
            with self.subTest(repos=repos):
                self.pkg["repositories"] = repos
                f = self.fetcher()
                f.out = os.path.join(self.tmp, "out-" + "-".join(repos))
                f.group([(self.entry, self.cand)])
                self.assertEqual(bool(f.files[0]["beta"]), beta)
                self.assertEqual(bool(f.files[0]["stable"]), stable)

    def test_other_identity_is_not_built(self):
        self.built("build1|old")
        f = self.fetcher()
        f.group([(self.entry, self.cand)])
        self.assertEqual(f.files, [])
        self.assertEqual(f.skipped[0]["reason"], "build output is from another plan")

    def test_unchanged_follows_repositories(self):
        """A file built for both repositories, then the config says beta only."""
        self.built(self.cand["identity"])
        f = self.fetcher()
        f.group([(self.entry, self.cand)])
        self.assertTrue(f.files[0]["stable"])
        self.pkg["repositories"] = ["beta"]
        g = self.fetcher({"files": f.files})
        g.group([(self.entry, self.cand)])
        self.assertTrue(g.files[0]["unchanged"])
        self.assertIsNone(g.files[0]["stable"])
        self.assertTrue(g.files[0]["beta"])
        from extpkg import retention
        _, removed = retention.plan_removal({"files": f.files}, g.files, [], {"fastfetch"}, {})
        self.assertEqual(removed, [f.files[0]["stable"]])

    def test_unchanged_carries_every_file(self):
        self.built(self.cand["identity"], ("fastfetch", "fastfetch-extra"))
        f = self.fetcher()
        f.group([(self.entry, self.cand)])
        g = self.fetcher({"files": f.files})
        g.built = None
        g.group([(self.entry, self.cand)])
        self.assertEqual(len(g.files), 2)
        self.assertTrue(all(x["unchanged"] for x in g.files))


if __name__ == "__main__":
    unittest.main()
