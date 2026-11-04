"""Package list for the web site: configs joined with the last live manifests.

Output: index.html (one file, no external assets) and packages.json.
"""

import datetime
import functools
import html
import json
import os

from . import config, debver

KINDS = {"apt": "apt repository", "github": "GitHub release", "url": "download", "build": "built from source"}
# A missing build for one architecture is not an error (see cli._failed).
NOT_UPSTREAM = "no package matched"


def _source(pkg):
    if pkg["method"] == "build":
        return (pkg.get("upstream") or pkg.get("packaging") or {}).get("url")
    return (pkg.get("source") or {}).get("url")


def _main_package(pkg, files):
    """The package that names the version: the first install package with files."""
    have = {x["package"] for x in files}
    for name in pkg.get("install", []) + [pkg["name"]]:
        if name in have:
            return name
    return min(have) if have else None


def _describe(pkg, files, main, describe):
    for x in files:
        if x["package"] == main and x.get("description"):
            return x["description"], x.get("homepage")
    if describe and main:
        for x in files:
            if x["package"] == main:
                text = describe(x["release"], pkg.get("target", "main"), x["deb_arch"], main)
                if text:
                    return text, None
    return None, None


def collect(pkgs, manifests, describe=None):
    """Return the site data. manifests: {name: manifest}. describe(release, target, arch, package)."""
    releases, files, skipped = set(), {}, {}
    for doc in manifests.values():
        releases.update(doc.get("releases", []))
        for x in doc.get("files", []):
            if not x.get("carried"):       # old versions and removed configs
                files.setdefault(x["config"], []).append(x)
        for s in doc.get("skipped", []):
            skipped[(s["config"], s["release"], s["arch"])] = s["reason"]
    releases = sorted(releases) or list(config.DEFAULT_RELEASES)

    out = []
    for pkg in sorted(pkgs, key=lambda p: p["name"]):
        mine = files.get(pkg["name"], [])
        main = _main_package(pkg, mine)
        description, homepage = _describe(pkg, mine, main, describe)
        stable_ok = "stable" in pkg.get("repositories", config.REPOSITORIES)
        cells, wanted, ready = {}, 0, 0
        for rel, arch in config.expand(pkg, releases):
            here = [x for x in mine if x["release"] == rel and x["arch"] == arch]
            reason = skipped.get((pkg["name"], rel, arch))
            if here:
                # published: the stable repository has this version or a newer one.
                in_stable = stable_ok and any(x.get("stable") or x.get("published") for x in here)
                state = "stable" if in_stable else "beta"
                wanted += 1
                ready += 1
            elif reason == NOT_UPSTREAM:
                state = "none"
            else:
                state = "failed" if reason else "missing"
                wanted += 1
            versions = sorted({x["version"] for x in here if x["package"] == main},
                              key=functools.cmp_to_key(debver.compare))
            cells.setdefault(rel, {})[arch] = {
                "state": state,
                "version": versions[-1] if versions else None,
                "files": len(here),
                "reason": reason if state in ("failed", "none") else None,
            }
        if pkg.get("enabled", True) is False:
            status = "disabled"
        elif not mine:
            status = "missing"
        else:
            status = "ready" if ready == wanted else "partial"
        out.append({
            "name": pkg["name"],
            "method": pkg["method"],
            "kind": KINDS[pkg["method"]],
            "source": _source(pkg),
            "homepage": homepage,
            "description": description,
            "package": main,
            "binaries": sorted({x["package"] for x in mine}),
            "target": pkg.get("target", "main"),
            "repositories": pkg.get("repositories", list(config.REPOSITORIES)),
            "install": pkg.get("install", []),
            "status": status,
            "releases": cells,
        })
    return {
        "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "manifests": {n: d.get("generated") for n, d in sorted(manifests.items())},
        "releases": releases,
        "packages": out,
    }


def write(data, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "packages.json"), "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    # No < in the script element: </script> or <!-- cannot end or hide it.
    blob = json.dumps(data, sort_keys=True).replace("<", "\\u003c")
    with open(os.path.join(out_dir, "index.html"), "w") as f:
        f.write(PAGE.replace("@GENERATED@", html.escape(data["generated"])).replace("@DATA@", blob))
    with open(os.path.join(out_dir, ".nojekyll"), "w"):
        pass


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Armbian external packages</title>
<meta name="description" content="Third-party packages in the Armbian apt repository: versions per release and architecture.">
<style>
:root {
  --bg: #f7f7f5; --panel: #ffffff; --text: #1c1d1f; --muted: #686b70; --line: #e3e3df;
  --accent: #d9480f; --accent-soft: #fff0e8;
  --stable: #1f8a4c; --stable-soft: #e3f4ea; --beta: #a86400; --beta-soft: #fdf1dc;
  --bad: #c92a2a; --bad-soft: #fde8e8; --none: #9a9ca1; --none-soft: #efefec;
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #131416; --panel: #1b1c1f; --text: #e8e8e6; --muted: #9b9ea4; --line: #2d2f33;
    --accent: #ff8a4c; --accent-soft: #3a2116;
    --stable: #5cc98a; --stable-soft: #17301f; --beta: #f0b052; --beta-soft: #35280f;
    --bad: #ff7b7b; --bad-soft: #3a1717; --none: #75787e; --none-soft: #26272a;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.wrap { max-width: 1180px; margin: 0 auto; padding: 0 16px; }
header { padding: 40px 0 20px; }
h1 { margin: 0 0 6px; font-size: 28px; letter-spacing: -0.01em; }
.lead { margin: 0; color: var(--muted); max-width: 760px; }
.stats { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 10px; margin: 22px 0 0; max-width: 680px; }
.stat { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 10px 16px; }
.stat b { display: block; font-size: 22px; font-variant-numeric: tabular-nums; }
.stat span { color: var(--muted); font-size: 13px; }
.bar { position: sticky; top: 0; z-index: 2; background: var(--bg); padding: 12px 0; border-bottom: 1px solid var(--line);
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.bar input, .bar select { font: inherit; color: var(--text); background: var(--panel); border: 1px solid var(--line);
  border-radius: 8px; padding: 7px 10px; }
.bar input { flex: 1 1 220px; min-width: 0; }
.bar .count { color: var(--muted); font-size: 13px; margin-left: auto; }
.legend { display: flex; flex-wrap: wrap; gap: 14px; color: var(--muted); font-size: 13px; padding: 12px 0 4px; }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 6px; vertical-align: -1px; background: currentColor; }
.legend span { color: var(--muted); }
.list { display: grid; gap: 10px; padding: 12px 0 40px; }
.pkg { min-width: 0; background: var(--panel); border: 1px solid var(--line); border-radius: 12px; }
.pkg > summary { list-style: none; cursor: pointer; padding: 14px 16px; display: grid;
  grid-template-columns: minmax(0, 1fr) auto; gap: 6px 16px; }
.pkg > summary::-webkit-details-marker { display: none; }
.pkg[open] > summary { border-bottom: 1px solid var(--line); }
.name { font-weight: 600; font-size: 16px; }
.desc { color: var(--muted); font-size: 14px; grid-column: 1; }
.meta { display: flex; flex-wrap: wrap; gap: 6px; grid-column: 1 / -1; align-items: center; }
.tag { font-size: 12px; border: 1px solid var(--line); border-radius: 999px; padding: 1px 9px; color: var(--muted); white-space: nowrap; }
.status { grid-row: 1; grid-column: 2; font-size: 12px; font-weight: 600; border-radius: 999px; padding: 2px 10px; align-self: start; }
.s-ready { color: var(--stable); background: var(--stable-soft); }
.s-partial { color: var(--beta); background: var(--beta-soft); }
.s-missing { color: var(--bad); background: var(--bad-soft); }
.s-disabled { color: var(--none); background: var(--none-soft); }
.rels { display: flex; flex-wrap: wrap; gap: 4px; min-width: 0; }
.rel { font: 12px/1.6 var(--mono); border-radius: 6px; padding: 0 7px; }
.c-stable { color: var(--stable); background: var(--stable-soft); }
.c-beta { color: var(--beta); background: var(--beta-soft); }
.c-failed, .c-missing { color: var(--bad); background: var(--bad-soft); }
.c-none { color: var(--none); background: var(--none-soft); }
.body { padding: 14px 16px 16px; overflow-x: auto; }
.facts { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 4px 14px; margin: 0 0 14px; font-size: 14px; }
.facts dt { color: var(--muted); }
.facts dd { margin: 0; overflow-wrap: anywhere; }
code, .mono { font-family: var(--mono); font-size: 13px; }
pre { margin: 0; background: var(--bg); border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; overflow-x: auto; }
table { border-collapse: collapse; font-size: 13px; min-width: 100%; }
th, td { text-align: left; padding: 6px 10px; border-top: 1px solid var(--line); white-space: nowrap; }
th { color: var(--muted); font-weight: 500; border-top: 0; }
td.cell { font-family: var(--mono); font-size: 12px; }
td.cell span { border-radius: 6px; padding: 1px 6px; }
.empty { color: var(--muted); padding: 30px 0; text-align: center; }
footer { color: var(--muted); font-size: 13px; padding: 0 0 40px; }
@media (max-width: 600px) {
  .pkg > summary { grid-template-columns: minmax(0, 1fr); }
  .status { grid-row: auto; grid-column: 1; justify-self: start; }
  .bar .count { margin-left: 0; }
}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Armbian external packages</h1>
  <p class="lead">Third-party packages that the Armbian apt repository takes from upstream or builds from source.
  Versions per release and architecture, from the last live runs.</p>
  <div class="stats" id="stats"></div>
</header>
<div class="bar">
  <input id="q" type="search" placeholder="Search name, package, description" aria-label="Search">
  <select id="release" aria-label="Release"><option value="">All releases</option></select>
  <select id="method" aria-label="Source"><option value="">All sources</option></select>
  <select id="status" aria-label="Status"><option value="">All states</option>
    <option value="ready">Ready</option><option value="partial">Partial</option>
    <option value="missing">Missing</option><option value="disabled">Disabled</option></select>
  <span class="count" id="count"></span>
</div>
<div class="legend">
  <span><i style="color: var(--stable)"></i>stable and beta</span>
  <span><i style="color: var(--beta)"></i>beta only</span>
  <span><i style="color: var(--bad)"></i>failed or missing</span>
  <span><i style="color: var(--none)"></i>no upstream build</span>
</div>
<div class="list" id="list"></div>
<footer id="foot"></footer>
</div>
<script type="application/json" id="data">@DATA@</script>
<script>
(function () {
  var D = JSON.parse(document.getElementById("data").textContent);
  var $ = function (id) { return document.getElementById(id); };
  var esc = function (s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]; }); };
  var link = function (u) { return /^https?:\/\//.test(u || "") ? '<a href="' + esc(u) + '" rel="noopener">' + esc(u) + "</a>" : esc(u); };
  var LABEL = {ready: "Ready", partial: "Partial", missing: "Missing", disabled: "Disabled"};
  var RANK = {failed: 4, missing: 3, beta: 2, stable: 1, none: 0};

  function relState(cells) {
    var worst = null, ver = null;
    Object.keys(cells).forEach(function (a) {
      var c = cells[a];
      if (worst === null || RANK[c.state] > RANK[worst]) worst = c.state;
      if (c.version) ver = c.version;
    });
    return {state: worst, version: ver};
  }

  var methods = {};
  D.packages.forEach(function (p) { methods[p.method] = p.kind; });
  Object.keys(methods).sort().forEach(function (m) { $("method").add(new Option(methods[m], m)); });
  D.releases.forEach(function (r) { $("release").add(new Option(r, r)); });

  var n = {ready: 0, partial: 0, missing: 0}, built = 0;
  D.packages.forEach(function (p) { if (n[p.status] != null) n[p.status]++; if (p.method === "build") built++; });
  $("stats").innerHTML = [[D.packages.length, "packages"], [n.ready, "ready"], [n.partial, "partial"],
    [n.missing, "missing"], [built, "built from source"]].map(function (s) {
    return '<div class="stat"><b>' + s[0] + "</b><span>" + s[1] + "</span></div>"; }).join("");

  function card(p) {
    var rels = Object.keys(p.releases).sort().map(function (r) {
      var s = relState(p.releases[r]);
      return '<span class="rel c-' + s.state + '" title="' + esc(r + ": " + (s.version || s.state)) + '">' + esc(r) + "</span>";
    }).join("");
    var arches = {};
    Object.keys(p.releases).forEach(function (r) { Object.keys(p.releases[r]).forEach(function (a) { arches[a] = 1; }); });
    arches = Object.keys(arches).sort();
    var rows = Object.keys(p.releases).sort().map(function (r) {
      return "<tr><th>" + esc(r) + "</th>" + arches.map(function (a) {
        var c = p.releases[r][a];
        if (!c) return "<td></td>";
        var txt = c.version || c.state;
        var tip = c.reason ? ' title="' + esc(c.reason) + '"' : (c.files ? ' title="' + c.files + ' files"' : "");
        return '<td class="cell"><span class="c-' + c.state + '"' + tip + ">" + esc(txt) + "</span></td>";
      }).join("") + "</tr>";
    }).join("");
    var install = p.install.length ? "<pre>apt install " + esc(p.install.join(" ")) + "</pre>" : "";
    return '<details class="pkg" id="' + esc(p.name) + '"><summary>' +
      '<div><span class="name">' + esc(p.name) + "</span></div>" +
      '<span class="status s-' + p.status + '">' + LABEL[p.status] + "</span>" +
      '<div class="desc">' + esc(p.description || "") + "</div>" +
      '<div class="meta"><span class="tag">' + esc(p.kind) + '</span><span class="tag">' + esc(p.target) + "</span>" +
      (p.repositories.indexOf("stable") < 0 ? '<span class="tag">beta repository only</span>' : "") +
      '<span class="rels">' + rels + "</span></div></summary>" +
      '<div class="body"><dl class="facts">' +
      "<dt>Source</dt><dd>" + link(p.source) + "</dd>" +
      (p.homepage ? "<dt>Homepage</dt><dd>" + link(p.homepage) + "</dd>" : "") +
      "<dt>Component</dt><dd><code>" + esc(p.target === "main" ? "main" : "<release>-" + p.target) + "</code></dd>" +
      "<dt>Repositories</dt><dd>" + esc(p.repositories.join(", ")) + "</dd>" +
      (p.package ? "<dt>Versions of</dt><dd><code>" + esc(p.package) + "</code></dd>" : "") +
      (install ? "<dt>Install</dt><dd>" + install + "</dd>" : "") +
      "</dl><table><tr><th></th>" + arches.map(function (a) { return "<th>" + esc(a) + "</th>"; }).join("") +
      "</tr>" + rows + "</table></div></details>";
  }

  function render() {
    var q = $("q").value.trim().toLowerCase(), rel = $("release").value, m = $("method").value, st = $("status").value;
    var shown = D.packages.filter(function (p) {
      if (m && p.method !== m) return false;
      if (st && p.status !== st) return false;
      if (rel && !p.releases[rel]) return false;
      if (q && [p.name, p.package, p.description, p.source].concat(p.install).join(" ").toLowerCase().indexOf(q) < 0) return false;
      return true;
    });
    $("list").innerHTML = shown.length ? shown.map(card).join("") : '<div class="empty">No package matches.</div>';
    $("count").textContent = shown.length + " of " + D.packages.length;
  }
  ["q", "release", "method", "status"].forEach(function (id) { $(id).addEventListener("input", render); });
  render();
  if (location.hash) { var el = document.getElementById(decodeURIComponent(location.hash.slice(1))); if (el) { el.open = true; el.scrollIntoView(); } }

  $("foot").innerHTML = "Generated @GENERATED@ from " + Object.keys(D.manifests).map(function (k) {
    return esc(k) + " (" + esc(D.manifests[k] || "?") + ")"; }).join(", ") +
    '. Machine-readable: <a href="packages.json">packages.json</a>.';
})();
</script>
</body>
</html>
"""
