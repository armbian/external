"""Load and validate package configs.

mirror/<name>.yaml   built packages to download (apt, github, url)
build/<name>.yaml    packages to build from source (method build), with
                     optional build/<name>/patches and build/<name>/debian
"""

import glob
import os

import yaml

from . import query

MIRROR_METHODS = ("apt", "github", "url")
BUILD_METHODS = ("build",)
METHODS = MIRROR_METHODS + BUILD_METHODS
# Native GitHub-hosted runners only: no emulation.
BUILD_ARCHES = ("amd64", "arm64")
TARGETS = ("main", "utils", "desktop")
# Old configs: REPOSITORY=B (beta), S (stable), BS (both).
REPOSITORIES = ("stable", "beta")
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
               "enabled", "notes", "keep", "include_debug", "skip", "depcheck",
               "packaging", "upstream", "revision", "build_depends", "repositories"}
    unknown = set(pkg) - allowed
    need(not unknown, f"unknown keys: {sorted(unknown)}")
    need(pkg.get("name") == os.path.basename(path)[:-5], "name must match the file name")
    need(pkg.get("method") in METHODS, f"method must be one of {METHODS}")
    need(pkg.get("target", "main") in TARGETS, f"target must be one of {TARGETS}")
    arches = _list(pkg.get("architectures"))
    need(arches and all(a in ARCHES for a in arches), f"architectures must be from {ARCHES}")
    rel = pkg.get("releases")
    need(rel == "all" or (isinstance(rel, list) and rel), "releases must be 'all' or a list")
    need(isinstance(pkg.get("keep", 1), int) and pkg.get("keep", 1) >= 1, "keep must be a number >= 1")
    skip = pkg.get("skip", [])
    need(isinstance(skip, list) and all(isinstance(x, str) and x.count("/") == 1 for x in skip),
         "skip must be a list of release/arch")
    need(isinstance(pkg.get("depcheck", True), bool), "depcheck must be true or false")
    repos = pkg.get("repositories", list(REPOSITORIES))
    need(isinstance(repos, list) and repos and set(repos) <= set(REPOSITORIES),
         f"repositories must be a list from {REPOSITORIES}")
    if pkg["method"] == "build":
        _check_build(pkg, path, need)
        return
    need(not {"packaging", "upstream", "revision", "build_depends"} & set(pkg),
         "packaging, upstream, revision and build_depends are for method build")
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


def _check_build(pkg, path, need):
    """method build: packaging and/or upstream; build/<name>/debian without packaging."""
    need("source" not in pkg, "method build uses packaging and upstream, not source")
    need(set(_list(pkg["architectures"])) <= set(BUILD_ARCHES),
         f"method build: architectures must be from {BUILD_ARCHES}")
    pk, up = pkg.get("packaging"), pkg.get("upstream")
    need(pk or up, "method build needs packaging, upstream or both")
    if pk:
        need(isinstance(pk, dict) and pk.get("url") and pk.get("suite") and pk.get("package"),
             "packaging needs url, suite and package")
    else:
        need(os.path.isfile(os.path.join(os.path.dirname(path), pkg["name"], "debian", "control")),
             f"without packaging, {pkg['name']}/debian/control is required")
    if up:
        need(isinstance(up, dict) and up.get("url"), "upstream.url is required")
        rb = up.get("rebase")
        need(rb is None or (isinstance(rb, dict) and rb.get("url") and rb.get("ref")),
             "upstream.rebase needs url and ref")
        need(isinstance(up.get("submodules", False), bool), "upstream.submodules must be true or false")
    rev = pkg.get("revision", 1)
    need(isinstance(rev, int) and rev >= 1, "revision must be a number >= 1")
    deps = pkg.get("build_depends", [])
    need(isinstance(deps, list) and all(isinstance(d, str) for d in deps), "build_depends must be a list of configs")
    for key in ("filter", "with_deps", "assets", "exclude", "filename", "repack"):
        need(key not in pkg, f"{key} is not for method build")


DEBUG_PATTERNS = ("*-dbg", "*-dbgsym")


def is_debug(package):
    """Debug symbol packages: not mirrored unless a config asks for them."""
    import fnmatch
    return any(fnmatch.fnmatchcase(package, p) for p in DEBUG_PATTERNS)


def load_one(path):
    with open(path) as f:
        pkg = yaml.safe_load(f)
    _check(pkg, path)
    pkg.setdefault("target", "main")
    pkg.setdefault("enabled", True)
    pkg.setdefault("include_debug", False)
    pkg.setdefault("repositories", list(REPOSITORIES))
    pkg.setdefault("verify", {})
    pkg["verify"].setdefault("signature", True)   # apt: InRelease must verify
    pkg["verify"].setdefault("checksums", True)   # apt: deb SHA256 must match the index
    pkg["install"] = _list(pkg.get("install"))
    pkg["architectures"] = _list(pkg.get("architectures"))
    for key in ("source", "packaging"):
        if key in pkg:
            pkg[key]["components"] = _list(pkg[key].get("components"))
    return pkg


def load_all(directory, names=None):
    """Configs of one directory. mirror/ takes apt, github, url; build/ takes build."""
    kind = os.path.basename(os.path.normpath(directory))
    allowed = {"mirror": MIRROR_METHODS, "build": BUILD_METHODS}.get(kind, METHODS)
    pkgs = []
    for path in sorted(glob.glob(os.path.join(directory, "*.yaml"))):
        name = os.path.basename(path)[:-5]
        if names and name not in names:
            continue
        pkg = load_one(path)
        if pkg["method"] not in allowed:
            raise ConfigError(f"{path}: method {pkg['method']} does not belong in {kind}/")
        pkgs.append(pkg)
    _check_build_depends(directory, pkgs)
    if names:
        missing = set(names) - {p["name"] for p in pkgs}
        if missing:
            raise ConfigError(f"unknown packages: {sorted(missing)}")
    return pkgs


def _check_build_depends(directory, pkgs):
    """build_depends: other build configs, one level deep (the Build workflow has two stages)."""
    for pkg in pkgs:
        for dep in pkg.get("build_depends", []):
            path = os.path.join(directory, f"{dep}.yaml")
            if not os.path.exists(path):
                raise ConfigError(f"{pkg['name']}: build_depends: no config {dep}")
            d = load_one(path)
            if d["method"] != "build" or d.get("build_depends"):
                raise ConfigError(f"{pkg['name']}: build_depends: {dep} must be a build config without build_depends")


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
    skip = set(pkg.get("skip", []))
    for arch in pkg["architectures"]:
        for rel in releases:
            if f"{rel}/{arch}" not in skip:
                yield rel, arch


def component_dir(pkg, release):
    """Output directory inside debs/ or debs-beta/. Matches incoming/external."""
    if pkg["target"] == "main":
        return ""
    return f"extra/{release}-{pkg['target']}"
