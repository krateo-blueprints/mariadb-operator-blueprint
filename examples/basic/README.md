---
type: Example
title: Basic mariadb-operator example
description: The two Compositions that install the mariadb-operator CRDs and the operator with its high-availability defaults.
resource: mariadb-operator
tags:
  - krateo
  - example
  - mariadb
timestamp: 2026-11-18T00:00:00+00:00
---
# Basic example

- [crds.yaml](crds.yaml): the CRDs, kept on uninstall.
- [operator.yaml](operator.yaml): the operator, 3 replicas, its webhook certificate from cert-manager.

```sh
kubectl create namespace mariadb-operator
kubectl apply -f crds.yaml -f operator.yaml
```

The operator refuses to render until the CRDs and cert-manager are served, then renders on the next reconcile.
