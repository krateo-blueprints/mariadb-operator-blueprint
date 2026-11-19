# mariadb-operator-blueprint

## What is this

A Krateo blueprint for [mariadb-operator](https://github.com/mariadb-operator/mariadb-operator) **26.10.2**, as two
Compositions:

| chart | kind | what it installs |
|---|---|---|
| `mariadb-operator-crds` | `MariadbOperatorCrds` | the operator's 12 CRDs, vendored from upstream with `helm.sh/resource-policy: keep` |
| `mariadb-operator` | `MariadbOperator` | the operator in high availability, its webhook certificate from cert-manager |

Both are published to `oci://ghcr.io/krateo-blueprints/charts/<chart>` on the **blueprints** channel, each with its
CompositionDefinition inside the archive, and serve `composition.krateo.io/v26-10-2`.

Why a blueprint, and not upstream's charts as they are:
- **Upstream's CRDs are deleted on uninstall.** Its CRD chart sets no `helm.sh/resource-policy` on any CRD, so
  removing that release deletes every `MariaDB`, `Backup` and `PhysicalBackup` in the cluster. These CRDs are kept.
- **The operator is failover-critical.** Many operators only reconcile: if one is down for a while, nothing that is
  running breaks and it catches up when it returns, so one replica is enough. mariadb-operator is different. With
  replication topologies it is the component that promotes a replica when the primary is lost (`autoFailover`) and
  repoints the primary Service. While no operator replica runs, a lost primary is not replaced at all. So the operator
  runs 3 replicas with leader election, required anti-affinity by hostname (one per node) and a PodDisruptionBudget
  that lets a drain evict one at a time. Its webhook does the same, because an unavailable webhook refuses every write to
  a mariadb-operator object.
- **Preconditions refuse instead of failing later.** The operator chart refuses to render, with the reason on its
  status, until the CRDs (at this version or newer) and cert-manager are served, and, when it can read the nodes, until
  3 schedulable nodes can take its replicas.

Used by [krateo-openstack-blueprint](https://github.com/krateo-blueprints/krateo-openstack-blueprint) for HA MariaDB and
backups (#309, #310 there).

## Install

**Preconditions:**
- **3 schedulable nodes** for the required anti-affinity. The render checks this when an administrator has applied the
  node-read grant, once per cluster:

  ```sh
  kubectl apply -f https://raw.githubusercontent.com/krateo-blueprints/mariadb-operator-blueprint/26.10.2/blueprints/mariadb-operator/node-reader-rbac.yaml
  ```

  Without it the check is skipped, and the ConfigMap `<release>-preconditions` says `nodes: unmeasured`.
- **cert-manager**, from any source. With Krateo, the installer's `features.ingress` brings it. Otherwise, for example:

  ```sh
  helm install cert-manager cert-manager --repo https://charts.jetstack.io \
    --namespace cert-manager --create-namespace --set crds.enabled=true
  ```

- Krateo core-provider, which turns each CompositionDefinition into a CRD.

**Register both CompositionDefinitions** (each archive carries its own; they are also at
`blueprints/<chart>/compositiondefinition.yaml`). They live in **`mariadb-operator-system`**: cluster-prerequisite
blueprints use `<name>-system` for their CompositionDefinitions and Compositions, as krateo-openstack-blueprint uses
`openstack-system`. The operator's own pods run in the Composition's namespace, so the examples use the same one. Then
create the two Compositions:

```sh
kubectl create namespace mariadb-operator-system
kubectl apply -f examples/basic/crds.yaml
kubectl apply -f examples/basic/operator.yaml
```

Applying both at once is safe: the operator refuses to render until the CRDs exist, and renders by itself on the next
reconcile. **Upgrade in the same order: CRDs first.** The operator refuses a version newer than its CRDs.

## Configure

The CRDs chart takes no configuration. The operator chart's root is closed:

| key | what it is |
|---|---|
| `preconditions.enabled` | default `true`; refuse to render without the CRDs, cert-manager or (when measurable) 3 schedulable nodes |
| `mariadb-operator` | passthrough to the upstream chart, with this blueprint's HA defaults |
| `global` | injected by the installer, propagated to the upstream subchart |

Nothing defaults to a cloud provider, a StorageClass or a node pool. See [docs/configuration.md](docs/configuration.md).

## Examples

[examples/basic](examples/basic): the two Compositions. See [docs/examples.md](docs/examples.md).

## Docs

- [docs/overview.md](docs/overview.md): the two charts, why the CRDs are vendored, the preconditions
- [docs/usage.md](docs/usage.md): installing, upgrading, uninstalling
- [docs/configuration.md](docs/configuration.md): the value surface and the HA defaults
- [docs/api.md](docs/api.md): the generated kinds and the served version
- [docs/release.md](docs/release.md): the tag rule and what a release refuses
- [docs/log.md](docs/log.md): what changed and why

## Develop & release

**Layout:** `blueprints/<chart>/chart/` holds each chart and `blueprints/<chart>/compositiondefinition.yaml` its
CompositionDefinition, as in krateo-openstack-blueprint. The release copies each CompositionDefinition into its chart's
archive and checks its URL and version.

**The version and tag rule.** Both charts carry upstream's version as a **literal**, not a `CHART_VERSION` placeholder
stamped from the tag. The served apiVersion (`composition.krateo.io/v26-10-2`) is derived from it, so it always names
the upstream release it installs, and an upstream bump is a repo-only change. Consequently:
- **A release is a tag of exactly that version**: today `26.10.2`, on a commit lint passed on.
- The chart versions, the upstream dependency, the CompositionDefinitions, the image tags, the CRD annotations and the
  examples all carry the same version (`hack/validate-version-mirror.py`).
- `hack/release-preflight` refuses any other tag before anything is published.
- A blueprint-only fix to an already-released upstream version cannot reuse its tag: it ships with the next upstream
  bump.

**Pins:**
- The upstream dependency is locked by the committed `Chart.lock` (the release runs `helm dependency build`, which never
  re-resolves).
- Each upstream chart is pinned by its OCI manifest digest (`krateo.io/upstream-digest`).
- Every `uses:` in every workflow is pinned to a full commit SHA.

Pull requests run [lint.yaml](.github/workflows/lint.yaml) (the gates in `hack/`) and
[preflight-refs.yaml](.github/workflows/preflight-refs.yaml). See [docs/release.md](docs/release.md).

## License

This repository's own work is licensed under the [Apache License 2.0](LICENSE). mariadb-operator, whose CRDs the CRDs
chart vendors and whose chart the operator chart packages, keeps its own MIT license and ships with it: see
[NOTICE](NOTICE).
