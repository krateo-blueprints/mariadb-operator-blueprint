---
type: Log
title: mariadb-operator-blueprint changelog
description: Notable changes to the mariadb-operator blueprint, with the measurements that settled each decision.
resource: mariadb-operator
tags:
  - krateo
  - changelog
  - log
  - mariadb
timestamp: 2026-11-18T00:00:00+00:00
---
# Log

## 2026-11

- **Initial blueprint, mariadb-operator 26.10.2.**
  - Two charts and Compositions: the CRDs, vendored from upstream with `helm.sh/resource-policy: keep` (upstream sets
    none on any of its 12 CRDs, read at 26.10.2), and the operator in high availability with its webhook certificate
    from cert-manager.
  - The operator chart refuses to render without the CRDs at its version or newer, or without cert-manager.
  - Released through the organisation's publisher 1.1.0 with the release preflight first.
  - Gates: `validate-version-mirror.py`, `validate-crds-vendored.py`, `validate-operator-ha.py`,
    `validate-release-wiring.py`, `validate-yaml-block-style.py`.
