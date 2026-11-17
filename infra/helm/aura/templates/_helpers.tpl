{{- define "aura.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "aura.databaseUrl" -}}
{{- if .Values.secrets.databaseUrl -}}
{{ .Values.secrets.databaseUrl }}
{{- else -}}
postgresql://{{ .Values.postgres.user }}:{{ .Values.postgres.password }}@{{ .Release.Name }}-postgres:5432/{{ .Values.postgres.database }}
{{- end -}}
{{- end -}}
