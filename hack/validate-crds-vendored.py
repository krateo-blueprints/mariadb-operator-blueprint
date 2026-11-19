#!/usr/bin/env python3
"""The vendored CRDs are upstream's, byte for byte, plus exactly two annotations each.

    hack/validate-crds-vendored.py [repo-root]

Why vendored. Upstream's mariadb-operator-crds chart sets no helm.sh/resource-policy on any of its CRDs (read at
26.10.2), so uninstalling the CRDs release deletes every CRD, and with them every MariaDB, Backup and PhysicalBackup in
the cluster. Helm cannot add an annotation to a dependency's templates, so this chart carries upstream's crds.yaml
itself, with two lines added to each CRD's metadata.annotations:

    helm.sh/resource-policy: keep
    krateo.io/upstream-version: "<version>"     (what the operator chart compares against before it renders)

A vendored file drifts silently: a hand edit, a partial refresh, an annotation lost on one CRD. So this pulls upstream's
chart at the version Chart.yaml names (annotations krateo.io/upstream-chart and krateo.io/upstream-version) and asserts:

  1. the vendored file with exactly those two lines removed from each CRD equals upstream's templates/crds.yaml;
  2. every CRD carries both lines, once, in that order, right after `annotations:`;
  3. the CRD set equals what the operator chart requires before it renders (mdbop.requiredCRDs);
  4. the CRDs chart renders exactly those CRDs and nothing else;
  5. upstream's license ships with what is redistributed (hack/upstream-notices.yaml): for each chart, the file under
     blueprints/<chart>/chart/files/upstream/ has its recorded SHA-256 and is byte-equal to the file in the upstream
     repository at that chart's release tag (<upstream chart name>-<upstream version>, from its Chart.yaml
     annotations); NOTICE names the upstream's tree at that tag, its license and the file; LICENSE is the Apache License
     2.0 that covers this repository's own work.

Needs helm and network access to the upstream registry and to raw.githubusercontent.com. Fails (2) when either is missing, or upstream's chart has no
crds.yaml: a comparison with nothing on one side proves nothing.
"""
import os
import re
import shutil
import subprocess
import sys
import hashlib
import tarfile
import tempfile
import urllib.request

try:
    import yaml
except ImportError:
    print("FAILED MEASUREMENT: PyYAML unavailable, so nothing was compared")
    sys.exit(2)

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
CHART = os.path.join(ROOT, "blueprints", "mariadb-operator-crds", "chart")
VENDORED = os.path.join(CHART, "templates", "crds.yaml")
OPERATOR_TPL = os.path.join(ROOT, "blueprints", "mariadb-operator", "chart", "templates", "_preconditions.tpl")
failures = []


def measurement_failed(m):
    print("FAILED MEASUREMENT: " + m)
    sys.exit(2)


def fail(m):
    failures.append(m)


if shutil.which("helm") is None:
    measurement_failed("helm not on PATH")
for p in (CHART, VENDORED, OPERATOR_TPL):
    if not os.path.exists(p):
        measurement_failed("%s is missing" % os.path.relpath(p, ROOT))

meta = yaml.safe_load(open(os.path.join(CHART, "Chart.yaml")))
ann = meta.get("annotations") or {}
ref, version = ann.get("krateo.io/upstream-chart"), str(ann.get("krateo.io/upstream-version") or "")
if not ref or not version:
    measurement_failed("blueprints/mariadb-operator-crds/chart/Chart.yaml names no krateo.io/upstream-chart and upstream-version")
KEEP = "    helm.sh/resource-policy: keep"
VER = '    krateo.io/upstream-version: "%s"' % version

with tempfile.TemporaryDirectory() as tmp:
    r = subprocess.run(["helm", "pull", ref, "--version", version, "--destination", tmp], capture_output=True, text=True)
    if r.returncode != 0:
        measurement_failed("could not pull %s %s: %s" % (ref, version, r.stderr.strip()[:300]))
    tgz = [f for f in os.listdir(tmp) if f.endswith(".tgz")]
    if len(tgz) != 1:
        measurement_failed("pulling %s %s produced %s" % (ref, version, tgz))
    with tarfile.open(os.path.join(tmp, tgz[0])) as t:
        members = [m for m in t.getmembers() if m.name.endswith("/templates/crds.yaml")]
        if len(members) != 1:
            measurement_failed("upstream %s %s has no templates/crds.yaml" % (ref, version))
        upstream = t.extractfile(members[0]).read().decode()

vendored = open(VENDORED).read()
lines = vendored.split("\n")
stripped, docs_seen, bad_places = [], 0, []
i = 0
while i < len(lines):
    line = lines[i]
    stripped.append(line)
    if line == "kind: CustomResourceDefinition":
        docs_seen += 1
    if line == "  annotations:" and i >= 2 and lines[i - 2] == "kind: CustomResourceDefinition":
        if lines[i + 1:i + 3] == [KEEP, VER]:
            i += 3
            continue
        bad_places.append(i + 1)
    i += 1
stripped = "\n".join(stripped)

# 1. byte equality after removing exactly the two added lines
if stripped != upstream:
    ul, sl = upstream.split("\n"), stripped.split("\n")
    first = next((n for n, (a, b) in enumerate(zip(ul, sl)) if a != b), min(len(ul), len(sl)))
    fail("1: the vendored CRDs, minus the two Krateo annotations, differ from upstream %s at line %d:\n"
         "      upstream: %r\n      vendored: %r" % (version, first + 1, ul[first] if first < len(ul) else "<end>",
                                                     sl[first] if first < len(sl) else "<end>"))
# 2. every CRD annotated once, in place
if docs_seen == 0:
    measurement_failed("the vendored file holds no CustomResourceDefinition")
if bad_places:
    fail("2: CRD annotations at line(s) %s lack the two Krateo lines right after `annotations:`" % bad_places)
for needle in (KEEP, VER):
    n = lines.count(needle)
    if n != docs_seen:
        fail("2: %r appears %d time(s) for %d CRDs" % (needle.strip(), n, docs_seen))
# 3. the set the operator chart requires
names = re.findall(r"^  name: (\S+)$", vendored, re.M)
req = re.search(r'define "mdbop.requiredCRDs" -\}\}\s*(.*?)\s*\{\{- end', open(OPERATOR_TPL).read(), re.S)
required = sorted(req.group(1).split()) if req else []
if sorted(names) != required:
    fail("3: the vendored CRDs %s are not the set the operator chart requires before rendering %s"
         % (sorted(set(names) ^ set(required)), "(mdbop.requiredCRDs)"))
# 4. what the chart renders
with tempfile.TemporaryDirectory() as tmp:
    w = os.path.join(tmp, "c")
    shutil.copytree(CHART, w)
    r = subprocess.run(["helm", "template", "crds", w, "--kube-version", "1.36.0"], capture_output=True, text=True)
    if r.returncode != 0:
        fail("4: the CRDs chart does not render: %s" % r.stderr.strip()[:200])
    else:
        kinds = [(d["kind"], d["metadata"]["name"]) for d in yaml.safe_load_all(r.stdout) if d]
        others = [k for k in kinds if k[0] != "CustomResourceDefinition"]
        if others or sorted(n for _, n in kinds) != sorted(names):
            fail("4: the CRDs chart renders %s besides or instead of its %d CRDs" % (others, len(names)))

# 5. upstream's license ships with what is redistributed
notices = (yaml.safe_load(open(os.path.join(ROOT, "hack", "upstream-notices.yaml"))) or {}).get("notices") or []
if not notices:
    measurement_failed("hack/upstream-notices.yaml lists no upstream license, so none was checked")
notice_path = os.path.join(ROOT, "NOTICE")
notice_text = open(notice_path, encoding="utf-8").read() if os.path.isfile(notice_path) else ""
lic_path = os.path.join(ROOT, "LICENSE")
lic_head = open(lic_path).read(2000) if os.path.isfile(lic_path) else ""
if "Apache License" not in lic_head or "Version 2.0" not in lic_head:
    fail("5: LICENSE is missing or is not the Apache License 2.0 that covers this repository's own work")
charts_with_notice = set()
for n in notices:
    cdir = os.path.join(ROOT, "blueprints", n["chart"], "chart")
    cann = (yaml.safe_load(open(os.path.join(cdir, "Chart.yaml"))) or {}).get("annotations") or {}
    cref, cver = cann.get("krateo.io/upstream-chart"), str(cann.get("krateo.io/upstream-version") or "")
    if not cref or not cver:
        fail("5: blueprints/%s/chart/Chart.yaml names no upstream chart and version to derive the tag from" % n["chart"])
        continue
    tag = "%s-%s" % (cref.rstrip("/").rsplit("/", 1)[-1], cver)
    fpath = os.path.join(cdir, "files", "upstream", n["file"])
    rel = os.path.relpath(fpath, ROOT)
    if not os.path.isfile(fpath):
        fail("5: %s is missing" % rel)
        continue
    data = open(fpath, "rb").read()
    if hashlib.sha256(data).hexdigest() != n["digest"]:
        fail("5: %s has SHA-256 %s, hack/upstream-notices.yaml records %s"
             % (rel, hashlib.sha256(data).hexdigest(), n["digest"]))
    url = "https://raw.githubusercontent.com/%s/%s/%s" % (n["repo"], tag, n["file"])
    try:
        served = urllib.request.urlopen(url, timeout=60).read()
    except Exception as ex:
        measurement_failed("could not read %s: %s" % (url, ex))
    if served != data:
        fail("5: %s differs from %s (SHA-256 %s)" % (rel, url, hashlib.sha256(served).hexdigest()))
    for want in ("github.com/%s/tree/%s" % (n["repo"], tag), n["license"], rel):
        if want not in notice_text:
            fail("5: NOTICE does not name %s" % want)
    charts_with_notice.add(n["chart"])
for c in ("mariadb-operator-crds", "mariadb-operator"):
    if c not in charts_with_notice:
        fail("5: %s redistributes upstream's work but hack/upstream-notices.yaml ships no license for it" % c)

if failures:
    for f in failures:
        print("FAIL: " + f)
    sys.exit(1)
print("OK: %d CRDs equal upstream %s %s byte for byte apart from keep and upstream-version, each annotated once; the "
      "operator chart requires exactly this set; the chart renders nothing else; %d upstream license file(s) match their "
      "digest and the repository at the tag, NOTICE names them, LICENSE is Apache-2.0"
      % (docs_seen, ref, version, len(charts_with_notice)))
