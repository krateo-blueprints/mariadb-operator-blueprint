---
type: Configuration
title: mariadb-operator configuration
description: The value surface of both charts, the high-availability defaults the operator chart sets on upstream, and why the upstream key is open.
resource: mariadb-operator
tags:
  - krateo
  - configuration
  - values
  - mariadb
timestamp: 2026-11-18T00:00:00+00:00
---
# Configuration

## mariadb-operator-crds

No configuration. The root accepts only `global`.

## mariadb-operator

The root is closed:

| key | default | what it is |
|---|---|---|
| `preconditions.enabled` | `true` | refuse to render without the 12 CRDs at this version or newer, or cert-manager's Certificate and Issuer CRDs |
| `mariadb-operator` | see below | passthrough to the upstream chart |
| `global` | | injected by the installer, propagated to the subchart |

`mariadb-operator` is open because helm validates this schema against coalesced values that always carry the
subchart's full defaults, so a typed node would refuse the chart's own defaults. Upstream's
[values.yaml](https://github.com/mariadb-operator/mariadb-operator/blob/26.10.2/deploy/charts/mariadb-operator/values.yaml)
documents every key. This blueprint sets:

| value | why |
|---|---|
| `crds.enabled: false` | the CRDs belong to the CRDs chart, which keeps them |
| `image.tag`, `webhook.image.tag`: `26.10.2` | pinned explicitly, so preflight-refs resolves them |
| `ha.enabled: true`, `ha.replicas: 3` | the operator performs failover; leader election picks one active replica |
| `affinity`: required anti-affinity by hostname | the replicas land on different nodes |
| `pdb.enabled: true`, `maxUnavailable: 1` | a drain evicts one replica at a time |
| `webhook.ha`, `webhook.affinity`, `webhook.pdb`: the same | an unavailable webhook refuses every write |
| `webhook.cert.certManager.enabled: true` | the certificate comes from cert-manager; the cert-controller is not rendered |

Required anti-affinity needs 3 schedulable nodes. Nothing defaults to a cloud provider, a StorageClass or a node pool.
