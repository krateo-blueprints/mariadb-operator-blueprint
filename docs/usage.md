---
type: Usage
title: Using the mariadb-operator blueprint
description: Installing the CRDs and the operator as Compositions, the upgrade order, and what an uninstall leaves behind.
resource: mariadb-operator
tags:
  - krateo
  - usage
  - mariadb
  - operator
timestamp: 2026-11-18T00:00:00+00:00
---
# Usage

## Preconditions

- **3 schedulable nodes** for the operator's and the webhook's required anti-affinity. To let the render check this,
  apply the node-read grant once per cluster, as an administrator (edit its subject if your namespace differs):

  ```sh
  kubectl apply -f https://raw.githubusercontent.com/krateo-blueprints/mariadb-operator-blueprint/26.10.2/blueprints/mariadb-operator/node-reader-rbac.yaml
  ```

- **cert-manager**, from any source. With Krateo, the installer's `features.ingress` brings it. A generic install:

  ```sh
  helm install cert-manager cert-manager --repo https://charts.jetstack.io \
    --namespace cert-manager --create-namespace --set crds.enabled=true
  ```

- Krateo core-provider. Register both CompositionDefinitions: each published archive carries its own, and the same
  files are at `blueprints/<chart>/compositiondefinition.yaml`. Both live in `mariadb-operator-system`, the
  `<name>-system` convention for cluster-prerequisite blueprints, and the examples put the Compositions there too.

## Install

```sh
kubectl create namespace mariadb-operator-system
kubectl apply -f examples/basic/crds.yaml
kubectl apply -f examples/basic/operator.yaml
```

The operator Composition reports the refusal on its status until the CRDs and cert-manager are served (and, when the
grant is applied, 3 schedulable nodes exist), then renders on the next reconcile. Nothing has to be re-applied.
`kubectl -n mariadb-operator-system get configmap mariadb-operator-preconditions -o yaml` says which checks were
measured.

## Upgrade

CRDs first, then the operator. The operator refuses a version newer than the installed CRDs, naming both versions.

## Uninstall

Deleting the operator Composition removes the operator; MariaDB instances keep running without reconciliation.
Deleting the CRDs Composition leaves the CRDs, and every object, in place (`helm.sh/resource-policy: keep`). Removing
them is a deliberate `kubectl delete crd`, which deletes every object of those kinds.
