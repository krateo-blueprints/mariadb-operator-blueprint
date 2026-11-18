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

{{/*
Nodes (Krateo blueprint). The operator and its webhook run 3 replicas with REQUIRED pod anti-affinity by hostname, so
each needs 3 distinct schedulable nodes: on fewer, the rest stay Pending forever, and an operator that performs
failover is then one node loss away from performing none. The render is refused, naming the count, while fewer than
`replicas` nodes can take a pod: not cordoned, no NoSchedule/NoExecute taint the pods do not tolerate, and matching the
pods' nodeSelector. Counted per kubernetes.io/hostname, the anti-affinity's topology key.

Listing nodes needs a permission core-provider's render identity does not have, and a refused `lookup` is a template
error that aborts the whole render (helm returns empty only for NotFound). So the lookup is guarded: it runs only when
the ClusterRole and ClusterRoleBinding named by mdbop.nodeReaderName exist, the role covers nodes/list, and the binding
names this namespace's service accounts as a group (the asset blueprints/mariadb-operator/node-reader-rbac.yaml, which
an administrator applies; the openstack umbrella's osh.nodeReadGranted pattern). Without the grant, or offline, the
node check is NOT measured, and templates/preconditions.yaml records that in the ConfigMap <release>-preconditions
rather than passing silently.

mdbop.liveNodes returns JSON {"live": bool, "granted": bool, "nodes": [...]}; mdbop.requireNodes is a pure function of
it and the values, so hack/validate-operator-ha.py drives it with stand-in node lists.
*/}}

{{- define "mdbop.nodeReaderName" -}}
krateo-mariadb-operator-node-reader
{{- end -}}

{{- define "mdbop.nodeReadGranted" -}}
{{- $name := include "mdbop.nodeReaderName" . -}}
{{- $role := lookup "rbac.authorization.k8s.io/v1" "ClusterRole" "" $name -}}
{{- $binding := lookup "rbac.authorization.k8s.io/v1" "ClusterRoleBinding" "" $name -}}
{{- $canList := "" -}}
{{- range $r := (($role).rules | default list) -}}
{{- if and (or (has "" ($r.apiGroups | default list)) (has "*" ($r.apiGroups | default list))) (or (has "nodes" ($r.resources | default list)) (has "*" ($r.resources | default list))) (or (has "list" ($r.verbs | default list)) (has "*" ($r.verbs | default list))) -}}
{{- $canList = "true" -}}
{{- end -}}
{{- end -}}
{{- $bound := "" -}}
{{- if and $binding (eq (($binding.roleRef).name | toString) $name) (eq (($binding.roleRef).kind | toString) "ClusterRole") -}}
{{- range $s := ($binding.subjects | default list) -}}
{{- if and (eq ($s.kind | toString) "Group") (eq ($s.name | toString) (printf "system:serviceaccounts:%s" $.Release.Namespace)) -}}
{{- $bound = "true" -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- if and (eq $canList "true") (eq $bound "true") -}}true{{- end -}}
{{- end -}}

{{- define "mdbop.liveNodes" -}}
{{- $out := dict "live" false "granted" false "nodes" list -}}
{{- if lookup "apiextensions.k8s.io/v1" "CustomResourceDefinition" "" "compositiondefinitions.core.krateo.io" -}}
{{- $_ := set $out "live" true -}}
{{- if eq (include "mdbop.nodeReadGranted" .) "true" -}}
{{- $_ := set $out "granted" true -}}
{{- $nodes := list -}}
{{- range $n := ((lookup "v1" "Node" "" "").items | default list) -}}
{{- $nodes = append $nodes (dict "name" $n.metadata.name "labels" ($n.metadata.labels | default dict) "unschedulable" (($n.spec).unschedulable | default false) "taints" (($n.spec).taints | default list)) -}}
{{- end -}}
{{- $_ := set $out "nodes" $nodes -}}
{{- end -}}
{{- end -}}
{{- $out | toJson -}}
{{- end -}}

{{/* (list $taint $tolerations): "true" when one of the tolerations tolerates the taint (Kubernetes' matching rules). */}}
{{- define "mdbop.tolerated" -}}
{{- $t := index . 0 -}}{{- $ok := "" -}}
{{- range $tol := (index . 1 | default list) -}}
{{- $effect := ($tol.effect | default "") | toString -}}
{{- if or (eq $effect "") (eq $effect ($t.effect | toString)) -}}
{{- if eq ($tol.operator | default "Equal" | toString) "Exists" -}}
{{- if or (not $tol.key) (eq ($tol.key | toString) ($t.key | toString)) -}}{{- $ok = "true" -}}{{- end -}}
{{- else if and (eq ($tol.key | default "" | toString) ($t.key | toString)) (eq ($tol.value | default "" | toString) ($t.value | default "" | toString)) -}}
{{- $ok = "true" -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- $ok -}}
{{- end -}}

{{/* (list $ $nodes $replicas $nodeSelector $tolerations): the number of distinct hostnames that can take one of the pods. */}}
{{- define "mdbop.schedulableHosts" -}}
{{- $nodes := index . 1 -}}{{- $selector := index . 3 | default dict -}}{{- $tols := index . 4 | default list -}}
{{- $hosts := dict -}}
{{- range $n := $nodes -}}
{{- $fits := not $n.unschedulable -}}
{{- range $k, $v := $selector -}}
{{- if ne (index ($n.labels | default dict) $k | default "" | toString) ($v | toString) -}}{{- $fits = false -}}{{- end -}}
{{- end -}}
{{- range $t := ($n.taints | default list) -}}
{{- if and (has ($t.effect | toString) (list "NoSchedule" "NoExecute")) (ne (include "mdbop.tolerated" (list $t $tols)) "true") -}}{{- $fits = false -}}{{- end -}}
{{- end -}}
{{- if $fits -}}{{- $_ := set $hosts (index ($n.labels | default dict) "kubernetes.io/hostname" | default $n.name | toString) true -}}{{- end -}}
{{- end -}}
{{- len $hosts -}}
{{- end -}}

{{- define "mdbop.requireNodes" -}}
{{- $top := index . 0 -}}{{- $state := index . 1 -}}
{{- $v := index $top.Values "mariadb-operator" | default dict -}}
{{- if and $state.live $state.granted (gt (len ($state.nodes | default list)) 0) -}}
{{- $workloads := list (dict "name" "the operator" "ha" (($v.ha | default dict).enabled) "replicas" (($v.ha | default dict).replicas | default 1) "selector" $v.nodeSelector "tolerations" $v.tolerations) -}}
{{- $wh := $v.webhook | default dict -}}
{{- $workloads = append $workloads (dict "name" "the webhook" "ha" (($wh.ha | default dict).enabled) "replicas" (($wh.ha | default dict).replicas | default 1) "selector" $wh.nodeSelector "tolerations" $wh.tolerations) -}}
{{- range $w := $workloads -}}
{{- if $w.ha -}}
{{- $want := int $w.replicas -}}
{{- $have := include "mdbop.schedulableHosts" (list $top $state.nodes $want $w.selector $w.tolerations) | int -}}
{{- if lt $have $want -}}
{{- fail (printf "\n\n%s runs %d replicas with required anti-affinity by kubernetes.io/hostname, but only %d of the %d node(s) this release can see can take one: not cordoned, no NoSchedule/NoExecute taint its pods do not tolerate, matching its nodeSelector %v.\n\nThe rest would stay Pending, and the operator performs MariaDB failover, so it must survive a node. Add schedulable nodes, uncordon or untaint them, add tolerations under mariadb-operator.tolerations / mariadb-operator.webhook.tolerations, or lower ha.replicas (not below 2).\n" $w.name $want $have (len $state.nodes) ($w.selector | default dict)) -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- end -}}
