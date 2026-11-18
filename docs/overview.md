---
type: Architecture
title: mariadb-operator-blueprint architecture
description: Why the CRDs are a separate, vendored and kept chart, how the operator chart wraps upstream for high availability, and how its preconditions refuse a render.
resource: mariadb-operator
tags:
  - krateo
  - architecture
  - mariadb
  - operator
timestamp: 2026-11-18T00:00:00+00:00
---
# Architecture

## Two charts, two Compositions

Upstream ships `mariadb-operator-crds` and `mariadb-operator` separately, so that removing the operator never removes
the CRDs. This blueprint keeps that split and makes each one a Composition.

## The CRDs chart: vendored, and kept

Upstream's `crds.yaml` (12 CRDs at 26.10.2) carries no `helm.sh/resource-policy`. Helm deletes the CRDs when that
release is uninstalled, and Kubernetes deletes every object of those kinds with them: every `MariaDB` and every
backup. Helm cannot annotate a dependency's templates, so this chart carries upstream's file itself, with two lines added
to each CRD's `metadata.annotations`:

- `helm.sh/resource-policy: keep`: an uninstall leaves the CRDs, and every object, in place;
- `krateo.io/upstream-version`: the version the operator chart compares against before it renders.

`hack/validate-crds-vendored.py` pulls upstream's chart at the pinned version and fails unless the vendored file, minus
exactly those two lines per CRD, is byte-equal to upstream's.

## The operator chart: upstream, made highly available

The chart depends on upstream's `mariadb-operator` chart at the same version and only sets values:

- `crds.enabled: false`: the CRDs belong to the CRDs chart. Upstream warns that a chart managing the CRDs deletes every
  MariaDB when it is uninstalled.
- The operator: 3 replicas with leader election, required pod anti-affinity by hostname, a PodDisruptionBudget with
  `maxUnavailable: 1`. With replication topologies the operator performs failover, so it must survive a node.
- The webhook: the same, because an unavailable webhook refuses every write to a mariadb-operator object. Its
  certificate is a cert-manager Certificate, so upstream's cert-controller is not rendered.
- The images, pinned explicitly to the chart's version, so they are resolved on every pull request.

## Preconditions

The operator chart refuses to render, with the message on the Composition's status, while:

- any of the 12 CRDs is not served, or lacks `krateo.io/upstream-version` (not installed by this blueprint's CRDs
  chart), or is older than the operator;
- cert-manager's `certificates.cert-manager.io` or `issuers.cert-manager.io` is not served.

Each check is a named GET of a CRD. Without core-provider's own CRD (`compositiondefinitions.core.krateo.io`) the render
is offline (`helm template`, CI) and nothing is checked. `preconditions.enabled: false` turns the check off, for
clusters that manage the CRDs themselves at this version.
