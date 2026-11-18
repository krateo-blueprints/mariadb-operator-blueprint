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
- **The operator does the failover.** With replication topologies the operator promotes a replica when the primary is
  lost, so it runs 3 replicas with leader election, spread over nodes, with drainable PodDisruptionBudgets, and so does
  its webhook (an unavailable webhook blocks every write to a mariadb-operator object).
- **Preconditions refuse instead of failing later.** The operator chart refuses to render, with the reason on its
  status, until the CRDs (at this version or newer) and cert-manager are served.

Used by [krateo-openstack-blueprint](https://github.com/krateo-blueprints/krateo-openstack-blueprint) for HA MariaDB and
backups (#309, #310 there).

## Install

**Preconditions:**
- **cert-manager**, from any source. With Krateo, the installer's `features.ingress` brings it. Otherwise, for example:

  ```sh
  helm install cert-manager cert-manager --repo https://charts.jetstack.io \
    --namespace cert-manager --create-namespace --set crds.enabled=true
  ```

- Krateo core-provider, which turns each CompositionDefinition into a CRD.

**Register both CompositionDefinitions** (each archive carries its own; they are also in
[compositiondefinitions/](compositiondefinitions)), then create the two Compositions:

```sh
kubectl create namespace mariadb-operator
kubectl apply -f examples/basic/crds.yaml
kubectl apply -f examples/basic/operator.yaml
```

Applying both at once is safe: the operator refuses to render until the CRDs exist, and renders by itself on the next
reconcile. **Upgrade in the same order: CRDs first.** The operator refuses a version newer than its CRDs.

## Configure

The CRDs chart takes no configuration. The operator chart's root is closed:

| key | what it is |
|---|---|
| `preconditions.enabled` | default `true`; refuse to render without the CRDs or cert-manager |
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

Pull requests run [lint.yaml](.github/workflows/lint.yaml) (the gates in `hack/`) and
[preflight-refs.yaml](.github/workflows/preflight-refs.yaml). A release is a tag of **exactly `26.10.2`**, the version
both charts mirror from upstream, on a commit lint passed on: `hack/release-preflight` refuses anything else before
anything is published. See [docs/release.md](docs/release.md).
