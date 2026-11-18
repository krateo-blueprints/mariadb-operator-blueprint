#!/usr/bin/env python3
"""A release runs the preflight first and the publisher last, both pinned to one charts release, and the preflight
refuses every tag but the version the charts mirror.

    hack/validate-release-wiring.py [repo-root]

  1. WIRING (.github/workflows/release-tag.yaml): it triggers only on a plain X.Y.Z tag; a `preflight` job calls
     krateo-blueprints/charts release-preflight.yaml with `version: ${{ github.ref_name }}`; package-and-push `needs`
     preflight and publish-index `needs` package-and-push, so a refusal publishes nothing; release-preflight.yaml and
     publish-chart.yaml are pinned to the SAME full 40-character SHA with an `# X.Y.Z` comment (PUBLISHING.md rule 9);
     publish-index publishes the blueprints channel from the artifact package-and-push uploads.
  2. THE HOOK (hack/release-preflight) is an executable regular file, and it is RUN: the mirrored version passes; a
     different X.Y.Z, a `v` prefix, a pre-release suffix and an empty version are refused. Then it is run against a
     copy of the repository whose operator chart version was changed, and must refuse the mirrored version there: a
     hook that checked only the shape would pass the rest.

Fails (2) when PyYAML is missing or a file it needs is absent.
"""
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

try:
    import yaml
except ImportError:
    print("FAILED MEASUREMENT: PyYAML unavailable, so the workflow was not read")
    sys.exit(2)

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
WF = os.path.join(ROOT, ".github", "workflows", "release-tag.yaml")
HOOK = os.path.join(ROOT, "hack", "release-preflight")
failures = []


def fail(m):
    failures.append(m)


for p in (WF, HOOK):
    if not os.path.exists(p):
        print("FAILED MEASUREMENT: %s is missing" % os.path.relpath(p, ROOT))
        sys.exit(2)

text = open(WF).read()
wf = yaml.safe_load(text)
on = wf.get(True) or wf.get("on") or {}
tags = ((on.get("push") or {}).get("tags")) or []
if tags != ["[0-9]+.[0-9]+.[0-9]+"]:
    fail("1: release-tag.yaml triggers on tags %s, want only the plain X.Y.Z glob" % tags)
jobs = wf.get("jobs") or {}
pre, pkg, pub = jobs.get("preflight") or {}, jobs.get("package-and-push") or {}, jobs.get("publish-index") or {}
PIN = re.compile(r"^krateo-blueprints/charts/\.github/workflows/(release-preflight|publish-chart)\.yaml@([0-9a-f]{40})$")
shas = {}
for name, job in (("preflight", pre), ("publish-index", pub)):
    m = PIN.match(str(job.get("uses", "")))
    if not m:
        fail("1: job %s does not call krateo-blueprints/charts %s pinned by full SHA (uses: %r)"
             % (name, "release-preflight.yaml" if name == "preflight" else "publish-chart.yaml", job.get("uses")))
        continue
    shas[name] = m.group(2)
    line = next((l for l in text.split("\n") if m.group(0) in l), "")
    if not re.search(r"#\s*\d+\.\d+\.\d+\s*$", line):
        fail("1: %s's pin carries no `# X.Y.Z` comment: %r" % (name, line.strip()))
if len(set(shas.values())) > 1:
    fail("1: the preflight and the publisher are pinned to different charts commits: %s" % shas)
if (pre.get("with") or {}).get("version") != "${{ github.ref_name }}":
    fail("1: the preflight is not given the tag as its version: %r" % (pre.get("with") or {}).get("version"))
needs = lambda j: j.get("needs") if isinstance(j.get("needs"), list) else [j.get("needs")]
if "preflight" not in needs(pkg):
    fail("1: package-and-push does not need preflight, so a refused tag would still be packaged and pushed")
if "package-and-push" not in needs(pub):
    fail("1: publish-index does not need package-and-push")
pw = pub.get("with") or {}
if pw.get("channel") != "blueprints" or pw.get("artifact") != "charts-blueprints":
    fail("1: publish-index publishes channel %r from artifact %r, want blueprints / charts-blueprints"
         % (pw.get("channel"), pw.get("artifact")))
if "name: charts-blueprints" not in text:
    fail("1: package-and-push uploads no charts-blueprints artifact for publish-index")

st = os.lstat(HOOK)
if not stat.S_ISREG(st.st_mode) or not st.st_mode & stat.S_IXUSR:
    fail("2: hack/release-preflight is not an executable regular file; the reusable preflight would refuse the release")


def run(root, version):
    return subprocess.run(["bash", os.path.join(root, "hack", "release-preflight"), version],
                          capture_output=True, text=True, cwd=root)


want = str(yaml.safe_load(open(os.path.join(ROOT, "helm/mariadb-operator-crds/Chart.yaml")))["version"])
r = run(ROOT, want)
if r.returncode != 0:
    fail("2: the hook refuses the mirrored version %s: %s" % (want, (r.stdout + r.stderr).strip()[-300:]))
major, minor, patch = want.split(".")
for bad in ("%s.%s.%d" % (major, minor, int(patch) + 1), "v" + want, want + "-main.gabc1234", ""):
    r = run(ROOT, bad)
    if r.returncode == 0:
        fail("2: the hook accepts %r; it must refuse every tag but %s" % (bad, want))
with tempfile.TemporaryDirectory() as tmp:
    copy = os.path.join(tmp, "repo")
    shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", "charts"))
    cy = os.path.join(copy, "helm", "mariadb-operator", "Chart.yaml")
    txt = open(cy).read()
    open(cy, "w").write(txt.replace('version: "%s"' % want, 'version: "0.0.1"', 1))
    r = run(copy, want)
    if r.returncode == 0:
        fail("2: with the operator chart at another version, the hook still accepts %s: it checks only the tag's shape"
             % want)

if failures:
    for f in failures:
        print("FAIL: " + f)
    sys.exit(1)
print("OK: preflight then package then publish, both reusables pinned to %s; the hook passes %s and refuses 4 other "
      "tags and a drifted chart" % (next(iter(shas.values()))[:7], want))
