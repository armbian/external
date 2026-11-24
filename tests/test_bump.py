import json
import os
import shutil
import tempfile
import unittest

from extpkg import bump, cli, config, source

CONTROL = "Source: x\n\nPackage: x\nArchitecture: all\nDescription: x\n"


def write_config(directory, name, upstream, extra=""):
    os.makedirs(os.path.join(directory, name, "debian"))
    with open(os.path.join(directory, name, "debian", "control"), "w") as f:
        f.write(CONTROL)
    path = os.path.join(directory, f"{name}.yaml")
    with open(path, "w") as f:
        f.write(f"name: {name}\nmethod: build\n# upstream code\nupstream:\n{upstream}{extra}"
                "releases:\n- forky\narchitectures:\n- amd64\n")
    return path


TAGS = {
    "https://github.com/o/app": ["v1.0.0", "v1.1.0", "v1.2.0-rc1", "benchmark-m4"],
    "https://github.com/o/tool": ["v0.2.0", "v0.3.0"],
    "https://github.com/o/same": ["v2.0.0"],
    "https://github.com/o/branch": ["v9.0.0"],
    "https://example.org/date.git": ["251123", "260101"],
}


class Pattern(unittest.TestCase):
    def test_default_pattern(self):
        self.assertEqual(bump.default_pattern("v1.2.0"), "v*")
        self.assertEqual(bump.default_pattern("mesa-26.0"), "mesa-*")
        self.assertEqual(bump.default_pattern("251123"), "*")

    def test_newest_tag(self):
        tags = ["v1.0.0", "v1.10.0", "v1.9.0", "v2.0.0-rc1", "mise-cache-core-v2026.11.14"]
        self.assertEqual(source.newest_tag(tags, "v*"), "v1.10.0")
        self.assertIsNone(source.newest_tag(["benchmark"], "v*"))


class Find(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(tempfile.mkdtemp(), "build")
        os.makedirs(self.dir)
        self.addCleanup(shutil.rmtree, os.path.dirname(self.dir))
        write_config(self.dir, "app", "  url: https://github.com/o/app\n  ref: v1.0.0  # pinned\n"
                     "  bump_group: suite\n", "revision: 4\n")
        write_config(self.dir, "tool", "  url: https://github.com/o/tool\n  ref: v0.2.0\n  bump_group: suite\n")
        write_config(self.dir, "same", "  url: https://github.com/o/same\n  ref: v2.0.0\n")
        write_config(self.dir, "branch", "  url: https://github.com/o/branch\n  ref: main\n")
        write_config(self.dir, "skipped", "  url: https://github.com/o/tool\n  ref: v0.2.0\n  bump: off\n")
        write_config(self.dir, "latest", "  url: https://github.com/o/tool\n")
        write_config(self.dir, "date", "  url: https://example.org/date.git\n  ref: '251123'\n")

    def find(self):
        return bump.find(self.dir, tags_of=TAGS.__getitem__)

    def test_find(self):
        found = {b["config"]: (b["old"], b["new"], b["group"]) for b in self.find()}
        self.assertEqual(found, {"app": ("v1.0.0", "v1.1.0", "suite"), "tool": ("v0.2.0", "v0.3.0", "suite"),
                                 "date": ("251123", "260101", "date")})

    def test_groups(self):
        plan = bump.groups(self.find())
        self.assertEqual([(g["branch"], g["configs"]) for g in plan],
                         [("bump/date", ["date"]), ("bump/suite", ["app", "tool"])])
        self.assertEqual(plan[0]["title"], "date: update upstream to 260101")
        self.assertEqual(plan[1]["title"], "suite: update upstream of 2 packages")
        self.assertIn("app=v1.1.0 tool=v0.3.0", plan[1]["marker"])
        self.assertIn("https://github.com/o/app/compare/v1.0.0...v1.1.0", plan[1]["body"])

    def test_apply_keeps_comments(self):
        plan_path = os.path.join(self.dir, "bump.json")
        bump.write_plan(plan_path, bump.groups(self.find()))
        bump.apply_group(plan_path, "suite")
        bump.apply_group(plan_path, "date")
        with open(os.path.join(self.dir, "app.yaml")) as f:
            text = f.read()
        self.assertIn("# upstream code\n", text)
        self.assertIn("  ref: v1.1.0  # pinned\n", text)
        self.assertIn("revision: 1\n", text)
        with open(os.path.join(self.dir, "date.yaml")) as f:
            self.assertIn("  ref: '260101'\n", f.read())
        self.assertEqual(config.load_one(os.path.join(self.dir, "tool.yaml"))["upstream"]["ref"], "v0.3.0")
        self.assertEqual(self.find(), [])

    def test_apply_needs_one_line(self):
        with self.assertRaises(config.ConfigError):
            bump.apply(os.path.join(self.dir, "same.yaml"), "v1.0.0", "v1.1.0")

    def test_hook_does_not_change_build(self):
        pkg = config.load_one(os.path.join(self.dir, "app.yaml"))
        before = source.local_hash(pkg, self.dir)
        with open(os.path.join(self.dir, "app", "bump-check"), "w") as f:
            f.write("#!/bin/sh\n")
        self.assertEqual(source.local_hash(pkg, self.dir), before)

    def test_bad_keys(self):
        path = write_config(self.dir, "bad", "  url: https://github.com/o/tool\n  ref: v0.2.0\n  bump: auto\n")
        with self.assertRaises(config.ConfigError):
            config.load_one(path)


if __name__ == "__main__":
    unittest.main()
