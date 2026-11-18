{{/*
Preconditions of the operator (Krateo blueprint). The render is REFUSED, with the reason on the Composition's status,
while the cluster does not serve what the operator needs:

  - every mariadb-operator CRD, from the mariadb-operator-crds chart at this version or newer. Each vendored CRD carries
    krateo.io/upstream-version; a CRD without it was not installed by that chart, and one older than this chart would
    make the operator act on objects its CRDs cannot validate. CRDs first, then the operator, on install and upgrade;
  - cert-manager's Certificate and Issuer CRDs, from any source: the webhook's certificate is a cert-manager
    Certificate (Krateo's installer brings cert-manager with features.ingress; any cert-manager install will do).

Without core-provider's own CRD the render is offline (helm template, CI): nothing can be checked there and nothing is
refused. A live cluster running this chart through Krateo always serves it. The same witness the openstack umbrella's
ESO refusal uses.

mdbop.liveCRDs reads the cluster (named GETs only) and returns JSON: {"live": bool, "crds": {name: {annotations}}}.
mdbop.preconditions is a pure function of that JSON and the chart, so hack/validate-operator-ha.py drives it with
stand-in clusters.
*/}}

{{- define "mdbop.requiredCRDs" -}}
backups.k8s.mariadb.com connections.k8s.mariadb.com databases.k8s.mariadb.com externalmariadbs.k8s.mariadb.com grants.k8s.mariadb.com mariadbs.k8s.mariadb.com maxscales.k8s.mariadb.com physicalbackups.k8s.mariadb.com pointintimerecoveries.k8s.mariadb.com restores.k8s.mariadb.com sqljobs.k8s.mariadb.com users.k8s.mariadb.com
{{- end -}}

{{- define "mdbop.certManagerCRDs" -}}
certificates.cert-manager.io issuers.cert-manager.io
{{- end -}}

{{- define "mdbop.liveCRDs" -}}
{{- $out := dict "live" false "crds" dict -}}
{{- if lookup "apiextensions.k8s.io/v1" "CustomResourceDefinition" "" "compositiondefinitions.core.krateo.io" -}}
{{- $_ := set $out "live" true -}}
{{- range $n := concat (splitList " " (include "mdbop.requiredCRDs" .)) (splitList " " (include "mdbop.certManagerCRDs" .)) -}}
{{- with lookup "apiextensions.k8s.io/v1" "CustomResourceDefinition" "" $n -}}
{{- $_ := set $out.crds $n (dict "annotations" (.metadata.annotations | default dict)) -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- $out | toJson -}}
{{- end -}}

{{- define "mdbop.preconditions" -}}
{{- $top := index . 0 -}}{{- $state := index . 1 -}}
{{- if $state.live -}}
{{- $crds := $state.crds | default dict -}}
{{- $want := $top.Chart.Version -}}
{{- $absent := list -}}{{- $foreign := list -}}{{- $older := list -}}
{{- range $n := splitList " " (include "mdbop.requiredCRDs" $top) -}}
{{- if not (hasKey $crds $n) -}}{{- $absent = append $absent $n -}}
{{- else -}}
{{- $v := index ((index $crds $n).annotations | default dict) "krateo.io/upstream-version" | default "" | toString -}}
{{- if not $v -}}{{- $foreign = append $foreign $n -}}
{{- else if semverCompare (printf "< %s" $want) $v -}}{{- $older = append $older (printf "%s (%s)" $n $v) -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- if $absent -}}
{{- fail (printf "\n\nThe mariadb-operator CRDs are not installed: this cluster does not serve %s.\n\nInstall the mariadb-operator-crds Composition (chart oci://ghcr.io/krateo-blueprints/charts/mariadb-operator-crds, version %s) first; this one renders by itself on the next reconcile.\n" (join ", " $absent) $want) -}}
{{- end -}}
{{- if $foreign -}}
{{- fail (printf "\n\nThe mariadb-operator CRDs %s were not installed by the mariadb-operator-crds chart (no krateo.io/upstream-version annotation), so their version cannot be checked against this operator (%s), and they may not be kept on uninstall.\n\nInstall the mariadb-operator-crds Composition at version %s, which adopts them, or set preconditions.enabled: false if you manage the CRDs yourself at this version.\n" (join ", " $foreign) $want $want) -}}
{{- end -}}
{{- if $older -}}
{{- fail (printf "\n\nThe installed mariadb-operator CRDs are older than this operator (%s): %s.\n\nUpgrade the mariadb-operator-crds Composition to %s first. CRDs first, then the operator: an operator newer than its CRDs acts on fields the API server prunes.\n" $want (join ", " $older) $want) -}}
{{- end -}}
{{- $cm := list -}}
{{- range $n := splitList " " (include "mdbop.certManagerCRDs" $top) -}}
{{- if not (hasKey $crds $n) -}}{{- $cm = append $cm $n -}}{{- end -}}
{{- end -}}
{{- if $cm -}}
{{- fail (printf "\n\ncert-manager is required: this cluster does not serve %s.\n\nThe operator's webhook certificate is a cert-manager Certificate. Install cert-manager from any source; with Krateo, the installer's features.ingress brings it. A generic install:\n\n    helm install cert-manager cert-manager --repo https://charts.jetstack.io --namespace cert-manager --create-namespace --set crds.enabled=true\n\nThis renders by itself on the next reconcile.\n" (join ", " $cm)) -}}
{{- end -}}
{{- end -}}
{{- end -}}
