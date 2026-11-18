---
type: API
title: mariadb-operator-blueprint API
description: The MariadbOperatorCrds and MariadbOperator CRDs generated from the charts' values.schema.json, and why the served apiVersion makes the charts mirror upstream's version.
resource: mariadb-operator
tags:
  - krateo
  - api
  - crd
  - schema
  - mariadb
timestamp: 2026-11-18T00:00:00+00:00
---
# API

core-provider generates one CRD per CompositionDefinition from the chart's `values.schema.json`:

| chart | kind | served apiVersion |
|---|---|---|
| `mariadb-operator-crds` | `MariadbOperatorCrds` | `composition.krateo.io/v26-10-2` |
| `mariadb-operator` | `MariadbOperator` | `composition.krateo.io/v26-10-2` |

The served version is derived from the chart version, so both charts carry upstream's version as a literal. An
upstream bump is then a repo-only change: no served-version move of its own making, and the version always names the
upstream release it installs. The spec of each kind is the chart's values: see [configuration.md](configuration.md).

The operator itself defines its own API (`k8s.mariadb.com/v1alpha1`: `MariaDB`, `User`, `Grant`, `Database`,
`PhysicalBackup`, `PointInTimeRecovery` and others), documented
[upstream](https://github.com/mariadb-operator/mariadb-operator/blob/26.10.2/docs/api_reference.md).
