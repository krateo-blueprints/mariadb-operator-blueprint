#!/usr/bin/env python3
"""The operator renders highly available, takes its webhook certificate from cert-manager, owns no CRD, and refuses
to render without its preconditions.

    hack/validate-operator-ha.py [repo-root]

With mariadb-operator's replication topology the operator performs the failover, so a single operator replica on a
lost node means no failover until it is rescheduled. And an unavailable webhook blocks every write to a mariadb-operator
object. So, rendered at the chart's defaults, as the kubelet and the scheduler receive it:

  1. HA. The operator and webhook Deployments run 3 replicas; each has a REQUIRED pod anti-affinity by
     kubernetes.io/hostname whose selector matches its own pod labels (one that matched nothing would not spread); each
     has exactly one PodDisruptionBudget selecting its pods that lets a drain evict one (1 <= maxUnavailable < 3, no
     minAvailable). The operator runs with leader election.
  2. cert-manager. The webhook's certificate is a cert-manager Certificate, and upstream's cert-controller is not
     rendered.
  3. No CRD. The operator chart renders no CustomResourceDefinition: upstream's chart can (crds.enabled), and a chart
     that owns the CRDs deletes every MariaDB when uninstalled. The CRDs belong to the mariadb-operator-crds chart.
  4. Refusals. mdbop.preconditions, a pure function of a cluster state, is driven with stand-in clusters: offline and
     complete clusters render; a missing operator CRD, a CRD without krateo.io/upstream-version, a CRD older than the
     chart, and a missing cert-manager CRD are each refused with a message naming the cause; a newer CRD renders.
     templates/preconditions.yaml must feed it the live state, gated on preconditions.enabled (default true).

Needs helm, PyYAML and network access for the upstream dependency. Fails (2) when one is missing or nothing renders.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

try:
    import yaml
except ImportError:
    print("FAILED MEASUREMENT: PyYAML unavailable, so nothing was rendered")
    sys.exit(2)

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
CHART = os.path.join(ROOT, "helm", "mariadb-operator")
failures = []


def measurement_failed(m):
    print("FAILED MEASUREMENT: " + m)
    sys.exit(2)


def fail(m):
    failures.append(m)


if shutil.which("helm") is None:
    measurement_failed("helm not on PATH")
if not os.path.isdir(CHART):
    measurement_failed("no chart at helm/mariadb-operator")


def render(w, values=None, extra=None):
    args = ["helm", "template", "mariadb-operator", w, "--namespace", "mariadb-operator", "--kube-version", "1.36.0"]
    f = None
    if values is not None:
        f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
        yaml.safe_dump(values, f)
        f.close()
        args += ["-f", f.name]
    try:
        return subprocess.run(args + (extra or []), capture_output=True, text=True)
    finally:
        if f:
            os.unlink(f.name)


def matches(selector, labels):
    return bool(selector) and all((labels or {}).get(k) == v for k, v in selector.items())


def check_ha(docs):
    deps = {d["metadata"]["name"]: d for d in docs if d.get("kind") == "Deployment"}
    pdbs = [d for d in docs if d.get("kind") == "PodDisruptionBudget"]
    want = {"mariadb-operator": "operator", "mariadb-operator-webhook": "webhook"}
    if sorted(deps) != sorted(want):
        fail("1: Deployments rendered: %s; want exactly %s" % (sorted(deps), sorted(want)))
    for name, d in deps.items():
        spec = d["spec"]
        pod = spec["template"]
        labels = pod["metadata"].get("labels") or {}
        if spec.get("replicas") != 3:
            fail("1: %s runs %s replica(s), want 3" % (name, spec.get("replicas")))
        req = (((pod["spec"].get("affinity") or {}).get("podAntiAffinity") or {})
               .get("requiredDuringSchedulingIgnoredDuringExecution") or [])
        spread = [t for t in req if t.get("topologyKey") == "kubernetes.io/hostname"
                  and matches((t.get("labelSelector") or {}).get("matchLabels"), labels)]
        if not spread:
            fail("1: %s has no required anti-affinity by hostname whose selector matches its own pods (%s)"
                 % (name, labels))
        mine = [p for p in pdbs if matches((p["spec"].get("selector") or {}).get("matchLabels"), labels)]
        if len(mine) != 1:
            fail("1: %s is selected by %d PodDisruptionBudget(s), want exactly 1" % (name, len(mine)))
        else:
            ps = mine[0]["spec"]
            mu = ps.get("maxUnavailable")
            if "minAvailable" in ps or not isinstance(mu, int) or not 1 <= mu < 3:
                fail("1: %s's PodDisruptionBudget is %s; a drain must be able to evict one replica and no more"
                     % (name, ps))
        if name == "mariadb-operator":
            args = " ".join(sum((c.get("args") or [] for c in pod["spec"]["containers"]), []))
            if "--leader-elect" not in args:
                fail("1: the operator runs without --leader-elect, so 3 replicas would all reconcile")
    certs = [d for d in docs if d.get("kind") == "Certificate" and str(d.get("apiVersion", "")).startswith(
        "cert-manager.io/")]
    if len(certs) != 1:
        fail("2: %d cert-manager Certificate(s) rendered, want the webhook's one" % len(certs))
    if any("cert-controller" in d["metadata"]["name"] for d in docs if d.get("kind") == "Deployment"):
        fail("2: upstream's cert-controller is rendered beside cert-manager")
    crds = [d["metadata"]["name"] for d in docs if d.get("kind") == "CustomResourceDefinition"]
    if crds:
        fail("3: the operator chart renders %d CRD(s) (%s...). They belong to mariadb-operator-crds: a chart that owns "
             "them deletes every MariaDB when uninstalled. Keep mariadb-operator.crds.enabled false." % (len(crds),
                                                                                                     crds[0]))
    return len(deps)


def stand_in(state):
    return {"live": True, "crds": state}


def part4(w):
    tpl = open(os.path.join(CHART, "templates", "preconditions.yaml")).read()
    if "preconditions.enabled" not in tpl or 'include "mdbop.liveCRDs"' not in tpl or "mdbop.preconditions" not in tpl:
        fail("4: templates/preconditions.yaml does not feed mdbop.preconditions the live state under "
             "preconditions.enabled")
    vals = yaml.safe_load(open(os.path.join(CHART, "values.yaml")))
    if (vals.get("preconditions") or {}).get("enabled") is not True:
        fail("4: preconditions.enabled is not true by default")
    src = open(os.path.join(CHART, "templates", "_preconditions.tpl")).read()
    req = src.split('define "mdbop.requiredCRDs" -}}')[1].split("{{- end")[0].split()
    cm = src.split('define "mdbop.certManagerCRDs" -}}')[1].split("{{- end")[0].split()
    if not req or not cm:
        measurement_failed("_preconditions.tpl lists no required CRD")
    chart_version = str(yaml.safe_load(open(os.path.join(CHART, "Chart.yaml")))["version"])

    def full(ver=chart_version, drop=(), noann=(), with_cm=True):
        out = {}
        for n in req:
            if n in drop:
                continue
            out[n] = {"annotations": {} if n in noann else {"krateo.io/upstream-version": ver}}
        if with_cm:
            for n in cm:
                out[n] = {"annotations": {}}
        return out

    major, minor, patch = (int(x) for x in chart_version.split("."))
    older = "%d.%d.%d" % (major, minor, patch - 1) if patch else "%d.%d.0" % (major, minor - 1)
    newer = "%d.%d.%d" % (major, minor, patch + 1)
    cases = [
        ("offline", {"live": False, "crds": {}}, None),
        ("a complete cluster", stand_in(full()), None),
        ("CRDs newer than the chart", stand_in(full(newer)), None),
        ("mariadbs CRD missing", stand_in(full(drop=("mariadbs.k8s.mariadb.com",))), "mariadbs.k8s.mariadb.com"),
        ("a CRD without krateo.io/upstream-version", stand_in(full(noann=("users.k8s.mariadb.com",))),
         "users.k8s.mariadb.com were not installed by the mariadb-operator-crds chart"),
        ("CRDs older than the chart", stand_in(full(older)), "older than this operator"),
        ("cert-manager missing", stand_in(full(with_cm=False)), "certificates.cert-manager.io"),
    ]
    probe = os.path.join(w, "templates", "zz-gate-preconditions.yaml")
    for label, state, needle in cases:
        open(probe, "w").write('{{- include "mdbop.preconditions" (list $ (%s | fromJson)) }}\n'
                               % json.dumps(json.dumps(state)))
        r = render(w, {"preconditions": {"enabled": False}})
        if needle is None and r.returncode != 0:
            fail("4: %s is refused: %s" % (label, r.stderr.strip()[:200]))
        if needle is not None:
            if r.returncode == 0:
                fail("4: %s renders; it must be refused" % label)
            elif needle not in r.stderr:
                fail("4: %s is refused without naming %r: %s" % (label, needle, r.stderr.strip()[:200]))
    os.unlink(probe)
    return len(cases)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        w = os.path.join(tmp, "mariadb-operator")
        shutil.copytree(CHART, w, ignore=shutil.ignore_patterns("charts", "Chart.lock"))
        r = subprocess.run(["helm", "dependency", "update", w], capture_output=True, text=True)
        if r.returncode != 0:
            measurement_failed("helm dependency update failed: %s" % r.stderr.strip()[:300])
        r = render(w)
        if r.returncode != 0:
            measurement_failed("the chart does not render at its defaults: %s" % r.stderr.strip()[:300])
        docs = [d for d in yaml.safe_load_all(r.stdout) if d]
        if not docs:
            measurement_failed("the chart rendered no object")
        n = check_ha(docs)
        cases = part4(w)
    if failures:
        for f in failures:
            print("FAIL: " + f)
        sys.exit(1)
    print("OK: %d Deployments with 3 replicas, required hostname anti-affinity on their own pods and a drainable PDB; "
          "leader election; the webhook certificate from cert-manager, no cert-controller; no CRD; %d precondition "
          "cases" % (n, cases))


main()
