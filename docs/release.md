---
type: Runbook
title: Releasing the mariadb-operator blueprint
description: The tag rule for charts that mirror upstream's version, what release-tag.yaml and hack/release-preflight refuse, and how to bump upstream.
resource: mariadb-operator
tags:
  - krateo
  - release
  - runbook
  - oci
  - mariadb
timestamp: 2026-11-18T00:00:00+00:00
---
# Release

## The tag rule

**Tag exactly `26.10.2`.** Both charts carry that literal version, not a `CHART_VERSION` placeholder the tag would
stamp, so the tag has to equal it.

## What a release does

1. **Preflight** (`krateo-blueprints/charts` `release-preflight.yaml`, pinned with the publisher to one release):
   runs `hack/release-preflight <tag>`. It refuses a version that is not plain X.Y.Z, or that differs from either
   chart's version or appVersion, the upstream dependency, either CompositionDefinition, or the
   `krateo.io/upstream-version` of any vendored CRD. Nothing is published after a refusal.
2. **Package and push:** the commit must have passed lint and `CHARTS_PUBLISH_TOKEN` must be present.
   `hack/validate-chart-lock.py --live` then refuses a `Chart.lock` out of sync with `Chart.yaml` or a registry no longer
   serving the pinned upstream digest. Each chart's dependencies come from its lock (`helm dependency build`, which
   never re-resolves). Each chart is packaged once, with `blueprints/<chart>/compositiondefinition.yaml` copied inside,
   and pushed to `oci://ghcr.io/krateo-blueprints/charts`.
3. **Index:** the organisation's publisher publishes the same bytes on the **blueprints** channel.

There is no pre-release channel here. This repository's charts are upstream's chart and CRDs at a pinned version with
values set and two annotations added, and lint renders and checks them on every pull request. Clusters that consume
them are verified through the blueprints that use them.

## Bumping upstream

1. Change every `26.10.2` together: both `Chart.yaml` files (version, appVersion, the dependency, the
   `krateo.io/upstream-version` annotation), both CompositionDefinitions, the image tags in
   `blueprints/mariadb-operator/chart/values.yaml`, and the example Compositions' apiVersion.
2. Re-pin: `helm dependency update blueprints/mariadb-operator/chart` and commit the new `Chart.lock`; set each
   `krateo.io/upstream-digest` to the manifest digest `helm pull` prints for the new version.
3. Re-vendor the CRDs: upstream's `templates/crds.yaml` from the new `mariadb-operator-crds` chart, with the two
   annotation lines added to each CRD. Update `mdbop.requiredCRDs` if the set changed.
   Re-fetch upstream's `LICENSE` at each chart's new release tag (`mariadb-operator-crds-<version>`,
   `mariadb-operator-<version>`) into its `files/upstream/`, unchanged, and record its `digest` in
   `hack/upstream-notices.yaml`. If the license changed, update `license` there and in `NOTICE`.
4. Run the gates in `hack/`; `validate-version-mirror.py` and `validate-crds-vendored.py` say exactly what is out of
   step.
5. Merge, then tag the new version.
