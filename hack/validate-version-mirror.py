#!/usr/bin/env python3
"""Every artifact here carries the one upstream version, and a tag can only be that version.

    hack/validate-version-mirror.py [repo-root] [--tag X.Y.Z]

Both charts carry a LITERAL version equal to upstream's (the composition's served apiVersion is derived from it, so an
upstream bump stays a repo-only change; PUBLISHING.md "charts that version independently"). Nothing stamps it from the
tag, so the numbers can only agree if something checks them. This checks, against one value (the CRDs chart version):

  - both Chart.yaml version and appVersion;
  - the operator chart's dependency on upstream mariadb-operator, and the CRDs chart's krateo.io/upstream-version;
  - both CompositionDefinitions' spec.chart.version, and that each installs oci://ghcr.io/krateo-blueprints/charts/<chart>;
  - the krateo.io/upstream-version annotation on every vendored CRD;
  - every example Composition's apiVersion (composition.krateo.io/v<version with dashes>);
  - with --tag, the tag itself. hack/release-preflight repeats this at release time without PyYAML.

Fails when PyYAML is missing (2) and when any of these is absent: a check with nothing to compare passes nothing.
"""
import glob
import os
import sys

try:
    import yaml
except ImportError:
    print("FAILED MEASUREMENT: PyYAML unavailable, so no version was compared")
    sys.exit(2)

args = [a for a in sys.argv[1:] if not a.startswith("--tag")]
tag = None
for i, a in enumerate(sys.argv[1:]):
    if a == "--tag" and i + 2 < len(sys.argv):
        tag = sys.argv[i + 2]
    elif a.startswith("--tag="):
        tag = a.split("=", 1)[1]
if tag in args:
    args.remove(tag)
ROOT = os.path.abspath(args[0] if args else ".")
failures = []


def fail(m):
    failures.append(m)


def load(path):
    if not os.path.isfile(path):
        print("FAILED MEASUREMENT: %s is missing" % os.path.relpath(path, ROOT))
        sys.exit(2)
    return yaml.safe_load(open(path))


crds_chart = load(os.path.join(ROOT, "blueprints/mariadb-operator-crds/chart/Chart.yaml"))
op_chart = load(os.path.join(ROOT, "blueprints/mariadb-operator/chart/Chart.yaml"))
want = str(crds_chart.get("version") or "")
if not want:
    print("FAILED MEASUREMENT: blueprints/mariadb-operator-crds/chart/Chart.yaml has no version")
    sys.exit(2)

seen = {}
seen["blueprints/mariadb-operator-crds/chart appVersion"] = crds_chart.get("appVersion")
seen["blueprints/mariadb-operator-crds/chart krateo.io/upstream-version"] = (crds_chart.get("annotations") or {}).get(
    "krateo.io/upstream-version")
seen["blueprints/mariadb-operator/chart version"] = op_chart.get("version")
seen["blueprints/mariadb-operator/chart appVersion"] = op_chart.get("appVersion")
deps = [d for d in op_chart.get("dependencies") or [] if d.get("name") == "mariadb-operator"]
seen["blueprints/mariadb-operator/chart dependency on upstream mariadb-operator"] = deps[0].get("version") if deps else None

op_values = yaml.safe_load(open(os.path.join(ROOT, "blueprints/mariadb-operator/chart/values.yaml"))) or {}
upstream_values = op_values.get("mariadb-operator") or {}
seen["blueprints/mariadb-operator/chart operator image tag"] = (upstream_values.get("image") or {}).get("tag")
seen["blueprints/mariadb-operator/chart webhook image tag"] = ((upstream_values.get("webhook") or {}).get("image") or {}).get("tag")

cds = sorted(glob.glob(os.path.join(ROOT, "blueprints/*/compositiondefinition.yaml")))
if len(cds) != 2:
    fail("want 2 CompositionDefinitions as blueprints/*/compositiondefinition.yaml, found %d" % len(cds))
for p in cds:
    cd = yaml.safe_load(open(p))
    name = os.path.basename(os.path.dirname(p))
    chart = (cd.get("spec") or {}).get("chart") or {}
    seen["%s spec.chart.version" % os.path.relpath(p, ROOT)] = chart.get("version")
    if chart.get("url") != "oci://ghcr.io/krateo-blueprints/charts/%s" % name:
        fail("%s installs %s, not oci://ghcr.io/krateo-blueprints/charts/%s" % (os.path.relpath(p, ROOT),
                                                                               chart.get("url"), name))
    if not os.path.isfile(os.path.join(ROOT, "blueprints", name, "chart", "Chart.yaml")):
        fail("%s names chart %s, which has no blueprints/<name>/chart/" % (os.path.relpath(p, ROOT), name))

crd_docs = [d for d in yaml.safe_load_all(open(os.path.join(ROOT, "blueprints/mariadb-operator-crds/chart/templates/crds.yaml")))
            if d and d.get("kind") == "CustomResourceDefinition"]
if not crd_docs:
    fail("the vendored CRD file holds no CustomResourceDefinition")
for d in crd_docs:
    seen["CRD %s krateo.io/upstream-version" % d["metadata"]["name"]] = (d["metadata"].get("annotations") or {}).get(
        "krateo.io/upstream-version")

examples = sorted(glob.glob(os.path.join(ROOT, "examples/**/*.yaml"), recursive=True))
served = "composition.krateo.io/v" + want.replace(".", "-")
nex = 0
for p in examples:
    for d in yaml.safe_load_all(open(p)):
        if d and str(d.get("apiVersion", "")).startswith("composition.krateo.io/"):
            nex += 1
            if d["apiVersion"] != served:
                fail("%s uses %s, but the charts serve %s" % (os.path.relpath(p, ROOT), d["apiVersion"], served))
if not nex:
    fail("no example Composition found under examples/: nothing shows the served apiVersion")

for what, got in seen.items():
    if got is None or str(got) == "":
        fail("%s is missing" % what)
    elif str(got) != want:
        fail("%s is %s, not %s" % (what, got, want))
if tag is not None and tag != want:
    fail("the tag %s is not the version every artifact mirrors (%s): tag exactly %s" % (tag, want, want))

if failures:
    for f in failures:
        print("FAIL: " + f)
    sys.exit(1)
print("OK: %d version fields, %d CRDs and %d example Composition(s) all carry %s%s"
      % (len(seen) - len(crd_docs), len(crd_docs), nex, want, (", and so does the tag" if tag else "")))
