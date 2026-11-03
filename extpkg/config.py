"""Load and validate packages/<name>.yaml."""

import glob
import os

import yaml

from . import query

METHODS = ("apt", "github", "url")
TARGETS = ("main", "utils", "desktop")
ARCHES = ("amd64", "arm64", "armhf", "riscv64", "loong64", "i386")
# Used when the armbian/build checkout is not available.
DEFAULT_RELEASES = ["bookworm", "trixie", "forky", "jammy", "noble", "resolute"]


class ConfigError(ValueError):
    pass


def _list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _check(pkg, path):
    def need(cond, msg):
        if not cond:
            raise ConfigError(f"{path}: {msg}")

    need(isinstance(pkg, dict), "not a mapping")
    allowed = {"name", "method", "source", "filter", "with_deps", "releases", "architectures",
               "target", "install", "verify", "repack", "assets", "exclude", "filename",
               "enabled", "notes"}
    unknown = set(pkg) - allowed
    need(not unknown, f"unknown keys: {sorted(unknown)}")
    need(pkg.get("name") == os.path.basename(path)[:-5], "name must match the file name")
    need(pkg.get("method") in METHODS, f"method must be one of {METHODS}")
    need(pkg.get("target", "main") in TARGETS, f"target must be one of {TARGETS}")
    arches = _list(pkg.get("architectures"))
    need(arches and all(a in ARCHES for a in arches), f"architectures must be from {ARCHES}")
    rel = pkg.get("releases")
    need(rel == "all" or (isinstance(rel, list) and rel), "releases must be 'all' or a list")
    src = pkg.get("source") or {}
    need(isinstance(src, dict) and src.get("url"), "source.url is required")
    if pkg["method"] == "apt":
        need(src.get("suite"), "source.suite is required for apt")
        need(pkg.get("filter"), "filter is required for apt")
        try:
            query.compile_query(pkg["filter"])
        except query.QueryError as e:
            raise ConfigError(f"{path}: filter: {e}") from e
    if pkg["method"] == "github":
        need("github.com/" in src["url"], "source.url must be a github.com repository")
    rp = pkg.get("repack")
    if rp is not None:
        need(isinstance(rp, dict) and rp.get("packages"), "repack.packages is required")


def load_one(path):
    with open(path) as f:
        pkg = yaml.safe_load(f)
    _check(pkg, path)
    pkg.setdefault("target", "main")
    pkg.setdefault("enabled", True)
    pkg.setdefault("verify", {})
    pkg["verify"].setdefault("signature", True)   # apt: InRelease must verify
    pkg["verify"].setdefault("checksums", True)   # apt: deb SHA256 must match the index
    pkg["install"] = _list(pkg.get("install"))
    pkg["architectures"] = _list(pkg.get("architectures"))
    src = pkg["source"]
    src["components"] = _list(src.get("components"))
    return pkg


def load_all(directory, names=None):
    pkgs = []
    for path in sorted(glob.glob(os.path.join(directory, "*.yaml"))):
        name = os.path.basename(path)[:-5]
        if names and name not in names:
            continue
        pkgs.append(load_one(path))
    if names:
        missing = set(names) - {p["name"] for p in pkgs}
        if missing:
            raise ConfigError(f"unknown packages: {sorted(missing)}")
    return pkgs


def supported_releases(build_dir):
    """Releases whose config/distributions/<rel>/support is not 'eos'."""
    if not build_dir:
        return list(DEFAULT_RELEASES)
    out = []
    for support in sorted(glob.glob(os.path.join(build_dir, "config/distributions/*/support"))):
        with open(support) as f:
            if f.read().strip() != "eos":
                out.append(os.path.basename(os.path.dirname(support)))
    if not out:
        raise ConfigError(f"no supported releases found under {build_dir}")
    return out


def expand(pkg, releases_all):
    """Yield (release, arch) for one package."""
    releases = releases_all if pkg["releases"] == "all" else pkg["releases"]
    for arch in pkg["architectures"]:
        for rel in releases:
            yield rel, arch


def component_dir(pkg, release):
    """Output directory inside debs/ or debs-beta/. Matches incoming/external."""
    if pkg["target"] == "main":
        return ""
    return f"extra/{release}-{pkg['target']}"
