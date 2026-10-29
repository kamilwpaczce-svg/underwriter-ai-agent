{{/*
Nazwa bazowa wydania - prefiks wszystkich zasobow (np. "underwriter-api").
Krotsza niz standardowy scaffold "helm create" (bez nazwy Chart.Name osobno) -
w tym chartcie Release.Name wystarcza (jedna instalacja = jedna aplikacja).
*/}}
{{- define "underwriter.fullname" -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Wspolne etykiety nakladane na kazdy zasob (standard Helm/K8s).
*/}}
{{- define "underwriter.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{/*
Etykiety selektora danego komponentu - argument to slownik {root: ., component: "api"}.
Uzywane zarowno w spec.selector (Deployment/StatefulSet/Service), jak i w
podSelector NetworkPolicy - musza byc identyczne w obu miejscach.
*/}}
{{- define "underwriter.selectorLabels" -}}
app.kubernetes.io/name: {{ .root.Chart.Name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/*
securityContext kontenerow z obrazu API (api, initContainer, Job migracji).
runAsUser MUSI byc liczba: Dockerfile ma "USER uzytkownik" (nazwa), a przy samym
runAsNonRoot kubelet odmawia startu ("image has non-numeric user, cannot verify user
is non-root" - sprawdzone na kind 14.10). uid 1000 = useradd --uid 1000 w Dockerfile.
*/}}
{{- define "underwriter.securityContextApi" -}}
runAsNonRoot: true
runAsUser: 1000
runAsGroup: 1000
allowPrivilegeEscalation: false
capabilities:
  drop: ["ALL"]
seccompProfile:
  type: RuntimeDefault
readOnlyRootFilesystem: true
{{- end -}}
