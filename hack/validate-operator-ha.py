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

  5. Nodes. mdbop.requireNodes, driven with stand-in node lists: 3 schedulable nodes render; 2 schedulable plus one
     cordoned, one carrying an untolerated NoSchedule taint, or only 2 matching the nodeSelector are refused, naming
     the count; a taint the pods tolerate renders; an empty list (not measured) renders; ha off renders on one node.
     The node lookup must sit inside the mdbop.nodeReadGranted guard (a refused lookup aborts the render), and the
     grant asset blueprints/mariadb-operator/node-reader-rbac.yaml must carry the guard's names, a rule covering
     nodes/list and a group subject for the CompositionDefinition's namespace.

Needs helm, PyYAML and network access for the upstream dependency. Fails (2) when one is missing or nothing renders.
"""
import json
import os
import re
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
CHART = os.path.join(ROOT, "blueprints", "mariadb-operator", "chart")
failures = []


def measurement_failed(m):
    print("FAILED MEASUREMENT: " + m)
    sys.exit(2)


def fail(m):
    failures.append(m)


if shutil.which("helm") is None:
    measurement_failed("helm not on PATH")
if not os.path.isdir(CHART):
    measurement_failed("no chart at blueprints/mariadb-operator/chart")


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


def node(name, unschedulable=False, taints=None, labels=None):
    lab = {"kubernetes.io/hostname": name}
    lab.update(labels or {})
    return {"name": name, "labels": lab, "unschedulable": unschedulable, "taints": taints or []}


def part5(w):
    src = open(os.path.join(CHART, "templates", "_preconditions.tpl")).read()
    body = src.split('define "mdbop.liveNodes"')[1].split("{{- end -}}\n\n")[0] if 'define "mdbop.liveNodes"' in src \
        else ""
    guard = body.find('include "mdbop.nodeReadGranted"')
    look = body.find('lookup "v1" "Node"')
    if guard < 0 or look < 0 or look < guard:
        fail("5: the node lookup is not inside the mdbop.nodeReadGranted guard: a Forbidden would abort every render")
    if src.count('lookup "v1" "Node"') != 1:
        fail("5: nodes are looked up %d times; once, guarded" % src.count('lookup "v1" "Node"'))
    name = re.search(r'define "mdbop.nodeReaderName" -\}\}\s*(\S+)', src)
    asset = os.path.join(ROOT, "blueprints", "mariadb-operator", "node-reader-rbac.yaml")
    cd = yaml.safe_load(open(os.path.join(ROOT, "blueprints", "mariadb-operator", "compositiondefinition.yaml")))
    if not os.path.isfile(asset) or not name:
        fail("5: no node-read grant asset, or no mdbop.nodeReaderName")
    else:
        docs = {d["kind"]: d for d in yaml.safe_load_all(open(asset)) if d}
        role, binding = docs.get("ClusterRole") or {}, docs.get("ClusterRoleBinding") or {}
        nm = name.group(1)
        if role.get("metadata", {}).get("name") != nm or binding.get("metadata", {}).get("name") != nm \
                or (binding.get("roleRef") or {}).get("name") != nm:
            fail("5: the grant asset's names are not %s, so the guard would never find it" % nm)
        if not any("nodes" in r.get("resources", []) and "list" in r.get("verbs", []) and "" in r.get("apiGroups", [])
                   for r in role.get("rules") or []):
            fail("5: the grant asset's ClusterRole does not cover nodes/list")
        want = "system:serviceaccounts:%s" % cd["metadata"]["namespace"]
        if not any(sub.get("kind") == "Group" and sub.get("name") == want for sub in binding.get("subjects") or []):
            fail("5: the grant asset's binding has no Group %s subject" % want)
    three = [node("n1"), node("n2"), node("n3")]
    taint = {"key": "dedicated", "value": "db", "effect": "NoSchedule"}
    cases = [
        ("not measured", {"live": True, "granted": False, "nodes": []}, None, None),
        ("3 schedulable nodes", {"live": True, "granted": True, "nodes": three}, None, None),
        ("2 schedulable and 1 cordoned", {"live": True, "granted": True,
                                           "nodes": [node("n1"), node("n2"), node("n3", unschedulable=True)]},
         None, "only 2 of the 3 node(s)"),
        ("an untolerated NoSchedule taint", {"live": True, "granted": True,
                                             "nodes": [node("n1"), node("n2"), node("n3", taints=[taint])]},
         None, "only 2 of the 3 node(s)"),
        ("a tolerated NoSchedule taint", {"live": True, "granted": True,
                                          "nodes": [node("n1"), node("n2"), node("n3", taints=[taint])]},
         {"tolerations": [{"key": "dedicated", "operator": "Equal", "value": "db", "effect": "NoSchedule"}],
          "webhook": {"tolerations": [{"key": "dedicated", "operator": "Exists"}]}}, None),
        ("only 2 nodes match the nodeSelector", {"live": True, "granted": True,
                                                 "nodes": [node("n1", labels={"pool": "db"}),
                                                           node("n2", labels={"pool": "db"}), node("n3")]},
         {"nodeSelector": {"pool": "db"}}, "only 2 of the 3 node(s)"),
        ("ha off on one node", {"live": True, "granted": True, "nodes": [node("n1")]},
         {"ha": {"enabled": False}, "webhook": {"ha": {"enabled": False}}}, None),
    ]
    probe = os.path.join(w, "templates", "zz-gate-nodes.yaml")
    for label, state, upstream, needle in cases:
        open(probe, "w").write('{{- include "mdbop.requireNodes" (list $ (%s | fromJson)) }}\n'
                               % json.dumps(json.dumps(state)))
        vals = {"preconditions": {"enabled": False}}
        if upstream:
            vals["mariadb-operator"] = upstream
        r = render(w, vals)
        if needle is None and r.returncode != 0:
            fail("5: %s is refused: %s" % (label, r.stderr.strip()[:200]))
        if needle is not None:
            if r.returncode == 0:
                fail("5: %s renders; it must be refused" % label)
            elif needle not in r.stderr:
                fail("5: %s is refused without naming the count: %s" % (label, r.stderr.strip()[:200]))
    os.unlink(probe)
    return len(cases)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        w = os.path.join(tmp, "mariadb-operator")
        shutil.copytree(CHART, w, ignore=shutil.ignore_patterns("charts"))
        r = subprocess.run(["helm", "dependency", "build", w], capture_output=True, text=True)
        if r.returncode != 0:
            measurement_failed("helm dependency build failed (the lock is checked by validate-chart-lock.py): %s"
                               % r.stderr.strip()[:300])
        r = render(w)
        if r.returncode != 0:
            measurement_failed("the chart does not render at its defaults: %s" % r.stderr.strip()[:300])
        docs = [d for d in yaml.safe_load_all(r.stdout) if d]
        if not docs:
            measurement_failed("the chart rendered no object")
        n = check_ha(docs)
        cases = part4(w)
        ncases = part5(w)
    if failures:
        for f in failures:
            print("FAIL: " + f)
        sys.exit(1)
    print("OK: %d Deployments with 3 replicas, required hostname anti-affinity on their own pods and a drainable PDB; "
          "leader election; the webhook certificate from cert-manager, no cert-controller; no CRD; %d precondition "
          "cases; %d node cases, the lookup guarded and the grant asset in agreement" % (n, cases, ncases))


main()
