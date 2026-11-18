---
type: ExampleIndex
title: mariadb-operator-blueprint examples
description: Index of runnable examples, starting with the two Compositions that install the CRDs and the operator.
resource: mariadb-operator
tags:
  - krateo
  - examples
  - mariadb
timestamp: 2026-11-18T00:00:00+00:00
---
# Examples

## basic

[examples/basic](../examples/basic): the CRDs Composition and the operator Composition, both with an empty spec (the
defaults are the high-availability ones). Applying both at once converges: the operator refuses to render until the
CRDs are served.
