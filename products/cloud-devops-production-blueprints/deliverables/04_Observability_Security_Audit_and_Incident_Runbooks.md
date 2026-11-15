# Module 4: Observability Stacks, Hardening Checklists & Incident Runbooks

## 1. Production Observability Stack Architecture

This observability architecture deploys an end-to-end OpenTelemetry (OTel) Collector DaemonSet that intercepts application traces, infrastructure metrics, and container stdout logs. It pipelines these telemetry streams directly to Prometheus, Grafana Tempo, and Grafana Loki.

```
+---------------------------------------------------------------------------------------+
|                                    Kubernetes Node                                    |
|                                                                                       |
|  +--------------------+   +--------------------+   +-------------------------------+  |
|  | Application Pod A  |   | Application Pod B  |   | /var/log/pods/*               |  |
|  | (OTel SDK Traces)  |   | (Prometheus /metrics)  | (Kubelet Log Sinks)           |  |
|  +---------+----------+   +---------+----------+   +---------------+---------------+  |
|            | OTLP/gRPC :4317        | HTTP :8080 Scraping          | Symlink Scraping |
|            +-------------------+    |    +-------------------------+                  |
|                                |    |    |                                            |
|                                v    v    v                                            |
|                  +-----------------------------+                                      |
|                  | OpenTelemetry Collector     |                                      |
|                  | (DaemonSet Instance)        |                                      |
|                  +--------------+--------------+                                      |
+---------------------------------|-----------------------------------------------------+
                                  |
            +---------------------+---------------------+
            | Remote Write OTLP   | Remote Write HTTP   | Push API / gRPC
            v                     v                     v
+---------------------+ +---------------------+ +---------------------+
| Grafana Tempo       | | Prometheus Server   | | Grafana Loki        |
| (Distributed Traces)| | (TSDB Metrics)      | | (Aggregated Logs)   |
+---------------------+ +---------------------+ +---------------------+
```

### 1.1 OpenTelemetry Collector DaemonSet Configuration

The following configuration deploys the OpenTelemetry Collector as a DaemonSet to ensure node-local data collection with minimal network overhead.

Save this manifest as `otel-collector-daemonset.yaml`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: otel-collector-config
  namespace: monitoring
  labels:
    app.kubernetes.io/name: otel-collector
data:
  otel-collector-config.yaml: |
    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: 0.0.0.0:4317
          http:
            endpoint: 0.0.0.0:4318
      prometheus:
        config:
          scrape_configs:
            - job_name: 'kubernetes-pods'
              kubernetes_sd_configs:
                - role: pod
              relabel_configs:
                - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
                  action: keep
                  regex: true
                - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
                  action: replace
                  target_label: __metrics_path__
                  regex: (.+)
                - source_labels: [__address__, __meta_kubernetes_pod_annotation_prometheus_io_port]
                  action: replace
                  regex: ([^:]+)(?::\d+)?;(\d+)
                  replacement: $1:$2
                  target_label: __address__
                - action: labelmap
                  regex: __meta_kubernetes_pod_label_(.+)
                - source_labels: [__meta_kubernetes_namespace]
                  action: replace
                  target_label: namespace
                - source_labels: [__meta_kubernetes_pod_name]
                  action: replace
                  target_label: pod
      filelog:
        include:
          - /var/log/pods/*/*/*.log
        exclude:
          - /var/log/pods/monitoring_*/*/*.log
        start_at: end
        include_file_path: true
        include_file_name: false
        operators:
          - type: container
            id: container-parser

    processors:
      memory_limiter:
        check_interval: 1s
        limit_percentage: 75
        spike_limit_percentage: 20
      batch:
        send_batch_size: 8192
        timeout: 200ms
        send_batch_max_size: 10240
      resourcedetection:
        detectors: [env, system]
        timeout: 2s
        override: false
      k8sattributes:
        auth_type: "serviceAccount"
        passthrough: false
        extract:
          metadata:
            - k8s.pod.name
            - k8s.pod.uid
            - k8s.deployment.name
            - k8s.namespace.name
            - k8s.node.name
            - star.status.phase

    exporters:
      prometheus:
        endpoint: "0.0.0.0:8889"
        namespace: "production"
        send_timestamps: true
      otlp/tempo:
        endpoint: "tempo-distributor.monitoring.svc.cluster.local:4317"
        tls:
          insecure: true
      otlphttp/loki:
        endpoint: "http://loki-gateway.monitoring.svc.cluster.local/otlp"
        tls:
          insecure: true

    extensions:
      health_check:
        endpoint: 0.0.0.0:13133
      zpages:
        endpoint: 0.0.0.0:55679

    service:
      extensions: [health_check, zpages]
      pipelines:
        traces:
          receivers: [otlp]
          processors: [memory_limiter, k8sattributes, batch]
          exporters: [otlp/tempo]
        metrics:
          receivers: [otlp, prometheus]
          processors: [memory_limiter, k8sattributes, batch]
          exporters: [prometheus]
        logs:
          receivers: [filelog]
          processors: [memory_limiter, k8sattributes, batch]
          exporters: [otlphttp/loki]
---
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: otel-collector
  namespace: monitoring
  labels:
    app.kubernetes.io/name: otel-collector
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: otel-collector
  template:
    metadata:
      labels:
        app.kubernetes.io/name: otel-collector
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8889"
        prometheus.io/path: "/metrics"
    spec:
      serviceAccountName: otel-collector
      terminationGracePeriodSeconds: 30
      hostNetwork: false
      dnsPolicy: ClusterFirst
      containers:
        - name: collector
          image: otel/opentelemetry-collector-contrib:0.96.0
          imagePullPolicy: IfNotPresent
          command:
            - "/otelcol-contrib"
            - "--config=/conf/otel-collector-config.yaml"
          resources:
            limits:
              cpu: 1000m
              memory: 1Gi
            requests:
              cpu: 250m
              memory: 512Mi
          ports:
            - name: otlp-grpc
              containerPort: 4317
              hostPort: 4317
              protocol: TCP
            - name: otlp-http
              containerPort: 4318
              hostPort: 4318
              protocol: TCP
            - name: metrics
              containerPort: 8889
              protocol: TCP
            - name: healthz
              containerPort: 13133
              protocol: TCP
          livenessProbe:
            httpGet:
              path: /
              port: healthz
            initialDelaySeconds: 15
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /
              port: healthz
            initialDelaySeconds: 5
            periodSeconds: 10
          volumeMounts:
            - name: config
              mountPath: /conf
            - name: varlogpods
              mountPath: /var/log/pods
              readOnly: true
            - name: varlibdockercontainers
              mountPath: /var/lib/docker/containers
              readOnly: true
          securityContext:
            readOnlyRootFilesystem: true
            runAsNonRoot: false
            runAsUser: 0
            capabilities:
              drop:
                - ALL
      volumes:
        - name: config
          configMap:
            name: otel-collector-config
        - name: varlogpods
          hostPath:
            path: /var/log/pods
        - name: varlibdockercontainers
          hostPath:
            path: /var/lib/docker/containers
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: otel-collector
  namespace: monitoring
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: otel-collector
rules:
  - apiGroups: [""]
    resources:
      - nodes
      - nodes/proxy
      - services
      - endpoints
      - pods
    verbs: ["get", "list", "watch"]
  - apiGroups: ["apps"]
    resources:
      - daemonsets
      - statefulsets
      - deployments
      - replicasets
    verbs: ["get", "list", "watch"]
  - apiGroups: ["extensions"]
    resources: ["*"]
    verbs: ["get", "list", "watch"]
  - nonResourceURLs: ["/metrics"]
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: otel-collector
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: otel-collector
subjects:
  - kind: ServiceAccount
    name: otel-collector
    namespace: monitoring
```

### 1.2 Enterprise Prometheus Alerting Rules

Save these production alert rules as `prometheus-alerts-production.yaml`. They detect resource exhaustion, control-plane anomalies, service instability, and ingress latency regressions.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: enterprise-platform-alerts
  namespace: monitoring
  labels:
    role: alert-rules
    prometheus: k8s
spec:
  groups:
    - name: node.rules
      rules:
        - alert: HostMemoryUnderSeverePressure
          expr: (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100 < 10
          for: 3m
          labels:
            severity: critical
            tier: infrastructure
          annotations:
            summary: "Host memory critically low on {{ $labels.instance }}"
            description: "Node {{ $labels.instance }} has less than 10% available memory (Current: {{ $value | printf \"%.2f\" }}%). OOM kills imminent."
            runbook_url: "https://wiki.internal.net/ops/runbooks/host-memory-exhaustion"

        - alert: HostDiskWillFillIn6Hours
          expr: (predict_linear(node_filesystem_free_bytes{fstype!~"tmpfs|overlay"}[1h], 6 * 3600) < 0) and (node_filesystem_free_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes{fstype!~"tmpfs|overlay"} < 0.15)
          for: 15m
          labels:
            severity: warning
            tier: infrastructure
          annotations:
            summary: "Filesystem on {{ $labels.instance }} projected to fill within 6 hours"
            description: "Mountpoint {{ $labels.mountpoint }} on {{ $labels.instance }} is filling rapidly and has < 15% free space remaining."
            runbook_url: "https://wiki.internal.net/ops/runbooks/disk-filling"

    - name: workload.rules
      rules:
        - alert: KubernetesPodCrashLooping
          expr: rate(kube_pod_container_status_restarts_total[5m]) * 60 > 2
          for: 2m
          labels:
            severity: critical
            tier: applications
          annotations:
            summary: "Pod {{ $labels.pod }} is crash looping"
            description: "Pod {{ $labels.pod }} in namespace {{ $labels.namespace }} (container: {{ $labels.container }}) has restarted > 2 times in the last 5 minutes."
            runbook_url: "https://wiki.internal.net/ops/runbooks/pod-crashloop"

        - alert: ContainerOOMKilled
          expr: (kube_pod_container_status_terminated_reason{reason="OOMKilled"} == 1) or (increase(node_vmstat_oom_kill[5m]) > 0)
          for: 0m
          labels:
            severity: critical
            tier: applications
          annotations:
            summary: "Container or Host hit Out-Of-Memory condition"
            description: "Namespace: {{ $labels.namespace }}, Pod: {{ $labels.pod }} was killed due to Out-Of-Memory limits."
            runbook_url: "https://wiki.internal.net/ops/runbooks/container-oomkilled"

    - name: api-ingress.rules
      rules:
        - alert: IngressHigh5xxErrorRate
          expr: (sum(rate(nginx_ingress_controller_requests{status=~"5.*"}[5m])) / sum(rate(nginx_ingress_controller_requests[5m]))) * 100 > 5
          for: 2m
          labels:
            severity: critical
            tier: networking
          annotations:
            summary: "High HTTP 5xx error rate on Ingress"
            description: "Ingress 5XX failure rate exceeds 5% across the last 5 minutes. Current rate: {{ $value | printf \"%.2f\" }}%."
            runbook_url: "https://wiki.internal.net/ops/runbooks/ingress-5xx-spike"

        - alert: ApiP99LatencyBreach
          expr: histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{route!~"/healthz|/ready|/metrics"}[5m])) by (le, route)) > 1.2
          for: 3m
          labels:
            severity: warning
            tier: applications
          annotations:
            summary: "API route p99 latency exceeds 1.2 seconds"
            description: "Route {{ $labels.route }} p99 response duration is {{ $value | printf \"%.3f\" }}s for more than 3 minutes."
            runbook_url: "https://wiki.internal.net/ops/runbooks/latency-degradation"
```

### 1.3 Declarative Grafana Provisioning (RED Metrics)

Configure automated datasource creation and dashboard provisioning to avoid manual UI manipulation.

Save this manifest as `grafana-datasources-provisioning.yaml`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-datasources
  namespace: monitoring
  labels:
    grafana_datasource: "1"
data:
  datasources.yaml: |
    apiVersion: 1
    datasources:
      - name: Prometheus
        type: prometheus
        access: proxy
        url: http://prometheus-k8s.monitoring.svc.cluster.local:9090
        isDefault: true
        editable: false
        jsonData:
          timeInterval: "15s"
          httpMethod: "POST"
      - name: Tempo
        type: tempo
        access: proxy
        url: http://tempo-query-frontend.monitoring.svc.cluster.local:3100
        isDefault: false
        editable: false
        jsonData:
          tracesToLogs:
            datasourceUid: 'loki'
            tags: ['job', 'instance', 'pod', 'namespace']
      - name: Loki
        type: loki
        access: proxy
        url: http://loki-gateway.monitoring.svc.cluster.local:80
        isDefault: false
        editable: false
        jsonData:
          maxLines: 5000
          derivedFields:
            - matcherRegex: "traceID=(\\w+)"
              name: TraceID
              url: '$${__trace.id}'
              datasourceUid: 'Tempo'
```

Save this RED (Rate, Errors, Duration) metrics dashboard definition as `grafana-dashboard-red.json`:

```json
{
  "annotations": { "list": [] },
  "editable": false,
  "fiscalYearStartMonth": 0,
  "graphTooltip": 1,
  "id": null,
  "links": [],
  "liveNow": false,
  "panels": [
    {
      "collapsed": false,
      "gridPos": { "h": 8, "w": 8, "x": 0, "y": 0 },
      "id": 1,
      "title": "Rate: Requests Per Second",
      "type": "timeseries",
      "datasource": { "type": "prometheus", "uid": "Prometheus" },
      "targets": [
        {
          "datasource": { "type": "prometheus", "uid": "Prometheus" },
          "expr": "sum(rate(http_requests_total{namespace=~\"$namespace\"}[$__rate_interval])) by (service)",
          "legendFormat": "{{service}} (RPS)"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "custom": { "drawStyle": "line", "lineInterpolation": "smooth" },
          "unit": "reqps"
        }
      }
    },
    {
      "collapsed": false,
      "gridPos": { "h": 8, "w": 8, "x": 8, "y": 0 },
      "id": 2,
      "title": "Errors: 5xx Return Rate",
      "type": "timeseries",
      "datasource": { "type": "prometheus", "uid": "Prometheus" },
      "targets": [
        {
          "datasource": { "type": "prometheus", "uid": "Prometheus" },
          "expr": "sum(rate(http_requests_total{status=~\"5.*\", namespace=~\"$namespace\"}[$__rate_interval])) by (service) / sum(rate(http_requests_total{namespace=~\"$namespace\"}[$__rate_interval])) by (service) * 100",
          "legendFormat": "{{service}} Error %"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "custom": { "drawStyle": "line", "lineInterpolation": "smooth" },
          "unit": "percent",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "green", "value": null },
              { "color": "yellow", "value": 1 },
              { "color": "red", "value": 5 }
            ]
          }
        }
      }
    },
    {
      "collapsed": false,
      "gridPos": { "h": 8, "w": 8, "x": 16, "y": 0 },
      "id": 3,
      "title": "Duration: p99 Transaction Latency",
      "type": "timeseries",
      "datasource": { "type": "prometheus", "uid": "Prometheus" },
      "targets": [
        {
          "datasource": { "type": "prometheus", "uid": "Prometheus" },
          "expr": "histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{namespace=~\"$namespace\"}[$__rate_interval])) by (le, service))",
          "legendFormat": "{{service}} p99"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "custom": { "drawStyle": "line", "lineInterpolation": "smooth" },
          "unit": "s"
        }
      }
    }
  ],
  "refresh": "10s",
  "schemaVersion": 38,
  "style": "dark",
  "tags": ["production", "red-metrics"],
  "time": { "from": "now-1h", "to": "now" },
  "timepicker": { "refresh_intervals": ["5s", "10s", "30s", "1m"] },
  "timezone": "utc",
  "title": "Production Service Golden Signals (RED)",
  "uid": "golden-signals-red",
  "variables": {
    "list": [
      {
        "current": { "text": "production", "value": "production" },
        "datasource": { "type": "prometheus", "uid": "Prometheus" },
        "definition": "label_values(http_requests_total, namespace)",
        "hide": 0,
        "includeAll": false,
        "name": "namespace",
        "query": "label_values(http_requests_total, namespace)",
        "refresh": 1,
        "type": "query"
      }
    ]
  }
}
```

---

## 2. Kubernetes CIS Benchmark & Security Hardening Audit Rubric

The following rubric provides explicit verification mechanics, commands, and actionable remediations mapped to the CIS Kubernetes Benchmark.

### 2.1 Audit Rubric Matrix

| Control ID | Benchmark Item | Automated Audit Command | Expected Compliant Output | Immediate Remediation Execution |
| :--- | :--- | :--- | :--- | :--- |
| **CIS-1.2.1** | Ensure Anonymous Requests to Kube-API are Disabled | `kubectl get nodes -v=0 &>/dev/null && curl -sk https://<APISERVER_IP>:6443/api | jq .` | Return HTTP `401 Unauthorized` or empty anonymous access block. | Append `--anonymous-auth=false` to `/etc/kubernetes/manifests/kube-apiserver.yaml`. |
| **CIS-1.2.20** | Ensure Node-Restriction is Enabled | `grep -E '--enable-admission-plugins=.*NodeRestriction' /etc/kubernetes/manifests/kube-apiserver.yaml` | Output matches `--enable-admission-plugins=...,NodeRestriction,...` | Add `NodeRestriction` to the comma-separated `--enable-admission-plugins` list. |
| **CIS-4.2.6** | Protect Containers from Running with `root` Execution UID | `kubectl get pods --all-namespaces -o json \| jq -r '.items[] \| select(.spec.securityContext.runAsNonRoot != true and (.spec.containers[].securityContext.runAsNonRoot != true)) \| .metadata.namespace + "/" + .metadata.name'` | Empty response (no pods returned). | Inject `securityContext.runAsNonRoot: true` and `runAsUser: 10001` in Pod templates. |
| **CIS-4.2.1** | Restrict HostPath Volume Mounts | `kubectl get pods --all-namespaces -o json \| jq -r '.items[] \| select(.spec.volumes[]?.hostPath != null) \| .metadata.namespace + "/" + .metadata.name'` | Empty response (except for system DaemonSets e.g., CNI). | Remove `hostPath` declarations; replace with `PersistentVolumeClaim` or `emptyDir`. |
| **CIS-5.1.3** | Minimize Wildcard Permissions in ClusterRoles | `kubectl get clusterroles -o json \| jq -r '.items[] \| select(.rules[]? \| select((.verbs[]? == "*") or (.resources[]? == "*"))) \| .metadata.name'` | Only default system roles (`cluster-admin`, `admin`). | Rewrite ClusterRole RBAC rules explicitly; strip `*` verbs and targets. |
| **CIS-5.7.1** | Default Deny Network Policies on Namespaces | `for ns in $(kubectl get ns -o jsonpath='{.items[*].metadata.name}'); do count=$(kubectl get netpol -n $ns --no-headers 2>/dev/null | wc -l); if [ $count -eq 0 ]; then echo "Missing NetPol: $ns"; fi; done` | All production/tenant namespaces have active NetworkPolicies. | Apply default-deny `NetworkPolicy` to isolated namespaces. |

### 2.2 Namespace Hardening: Pod Security Admission (PSA)

Enforce the Kubernetes Pod Security Standard `restricted` profile on all production namespaces by applying declarative metadata labels.

Save this manifest as `namespace-security-hardening.yaml`:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: production
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/audit-version: latest
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/warn-version: latest
---
apiVersion: v1
kind: Pod
metadata:
  name: security-compliance-test-pod
  namespace: production
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 10001
    runAsGroup: 10001
    fsGroup: 10001
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: hardened-test
      image: cgr.dev/chainguard/static:latest
      command: ["/bin/sleep", "3600"]
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop:
            - ALL
      resources:
        limits:
          cpu: 100m
          memory: 128Mi
        requests:
          cpu: 50m
          memory: 64Mi
```

### 2.3 Zero-Trust Default-Deny NetworkPolicy

Apply this policy to isolate target pods. It drops all egress and ingress traffic unless explicitly allowed.

Save this manifest as `zero-trust-default-deny.yaml`:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: production
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-system-dns-and-internal-ingress
  namespace: production
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/part-of: core-services
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ingress-nginx
      ports:
        - protocol: TCP
          port: 8080
  egress:
    # Allow DNS Resolution
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
    # Allow DB egress within secure-data namespace
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: databases
      ports:
        - protocol: TCP
          port: 5432
```

---

## 3. Automated Zero-Downtime TLS/SSL Management

This section establishes automated certificate lifecycle management using `cert-manager` with Let's Encrypt, securing ingresses via Cloudflare DNS-01 and HTTP-01 automated fallback hooks.

### 3.1 Cert-Manager Production Setup and ClusterIssuer

Apply the Cloudflare API Token as a secure Kubernetes secret.

```bash
kubectl create secret generic cloudflare-api-token-secret \
  --namespace cert-manager \
  --from-literal=api-token="v-X91b8A_dE9EXAMPLETOKENqL283jXl_d89234"
```

Save this ClusterIssuer configuration as `letsencrypt-production-issuer.yaml`:

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-production
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: security-operations@internal.net
    privateKeySecretRef:
      name: letsencrypt-production-account-key
    solvers:
      # Primary Solver: DNS-01 for Wildcards and Apex Domains
      - selector:
          dnsZones:
            - "internal.net"
            - "production-domain.com"
        dns01:
          cloudflare:
            apiTokenSecretRef:
              name: cloudflare-api-token-secret
              key: api-token
      # Fallback Solver: HTTP-01 for public HTTP routing endpoints
      - selector:
          matchLabels:
            use-http01-solver: "true"
        http01:
          ingress:
            class: nginx
