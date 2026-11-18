---
type: Component
title: mariadb-operator-blueprint
description: Krateo blueprint for mariadb-operator 26.10.2 as two Compositions, the CRDs kept on uninstall and the operator in high availability, published on the blueprints channel.
resource: mariadb-operator
tags:
  - krateo
  - blueprint
  - mariadb
  - operator
timestamp: 2026-11-18T00:00:00+00:00
---
# mariadb-operator-blueprint

| | |
|---|---|
| published | `oci://ghcr.io/krateo-blueprints/charts/mariadb-operator-crds`, `oci://ghcr.io/krateo-blueprints/charts/mariadb-operator` |
| channel | blueprints (each archive carries its CompositionDefinition) |
| chart versions | `26.10.2`, literals mirroring upstream |
| generated kinds | `MariadbOperatorCrds`, `MariadbOperator`, served at `composition.krateo.io/v26-10-2` |

## Where to go next

- [overview.md](overview.md): how the two charts, the vendored CRDs and the preconditions fit together
- [usage.md](usage.md): install, upgrade and uninstall
- [configuration.md](configuration.md): the value surface
- [api.md](api.md): the generated CRD contract
- [examples.md](examples.md): the runnable Compositions
- [release.md](release.md): the tag rule
- [log.md](log.md): what changed and why
