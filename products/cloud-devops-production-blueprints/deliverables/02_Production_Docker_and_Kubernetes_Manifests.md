# Module 2: 25+ Production-Grade Dockerfiles & Kubernetes Configurations

This module delivers battle-tested, security-hardened container specifications and Kubernetes deployment primitives designed for zero-trust, enterprise production clusters. Every artifact is engineered according to the CIS Docker Benchmark, CIS Kubernetes Benchmark, and the NSA/CISA Kubernetes Hardening Guidance.

---

## 1. Container Security Architecture Standards

Before deploying workloads, container images must adhere to four strict operational constraints:
1. **Rootless Execution**: Processes must never run as UID 0. Container engines must drop all default Linux capabilities except those strictly required for network binding or runtime execution.
2. **Ephemeral and Immutable Roots**: The root filesystem must be mounted read-only (`readOnlyRootFilesystem: true`). State must be isolated to explicitly mounted ephemeral `emptyDir` volumes or persistent claims.
3. **Deterministic Dependency Pinning**: Upstream base images and package dependencies must be pinned by SHA-256 digest or exact semantic versions.
4. **Minimal Attack Surface**: Build-time tools (compilers, package managers, test runners, shell binaries) are purged from the final runtime image via multi-stage builds.

| Dimension | Standard Applied | Verification Command |
| :--- | :--- | :--- |
| **Base Image** | Distroless or Alpine/Debian-Slim with pinned digest | `docker image inspect <image> --format '{{.RepoDigests}}'` |
| **User Identity** | Explicit non-root UID/GID (10001:10001) | `docker run --rm <image> id` |
| **Filesystem** | Read-Only root, tmpfs on `/tmp` | `docker run --rm --read-only --tmpfs /tmp <image>` |
| **Signals** | PID 1 init process handles `SIGTERM` and child reaping | `docker stop -t 10 <container_id>` exits 0 in <5s |

---

## 2. Hardened Multi-Stage Dockerfiles

### 2.1. Node.js 20 (TypeScript / Next.js / Express)

This blueprint handles production Next.js or standalone Express microservices. It isolates development dependencies, performs a production prune, implements `tini` as PID 1 to avoid orphan process leaks, and runs under an unprivileged user.

```dockerfile
# syntax=docker/dockerfile:1.4
# Stage 1: Dependency resolution and base environment
FROM node:20.12.2-bookworm-slim AS base
WORKDIR /usr/src/app
ENV NODE_ENV=production \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    NPM_CONFIG_AUDIT=false

# Stage 2: Build dependencies and compilation
FROM base AS builder
WORKDIR /usr/src/app

# Install native dependencies required for build steps (e.g., node-gyp)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3=3.11.2-1+b1 \
    make=4.3-4.1 \
    g++=4:12.2.0-3 \
    && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json ./
RUN npm ci --include=dev --ignore-scripts

COPY tsconfig.json ./
COPY src/ ./src/
RUN npm run build
RUN npm prune --omit=dev --ignore-scripts

# Stage 3: Minimal hardened runtime
FROM node:20.12.2-bookworm-slim AS runner
WORKDIR /usr/src/app

# Install tini for init signal handling
RUN apt-get update && apt-get install -y --no-install-recommends \
    tini=0.19.0-1 \
    && rm -rf /var/lib/apt/lists/*

# Security: Assign non-root UID/GID
RUN groupadd --gid 10001 nodejs && \
    useradd --uid 10001 --gid nodejs --shell /usr/sbin/nologin --home /usr/src/app nodeuser

COPY --from=builder --chown=10001:10001 /usr/src/app/node_modules ./node_modules
COPY --from=builder --chown=10001:10001 /usr/src/app/dist ./dist
COPY --from=builder --chown=10001:10001 /usr/src/app/package.json ./package.json

USER 10001:10001

EXPOSE 3000
ENV PORT=3000 \
    NODE_ENV=production

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["node", "dist/index.js"]
```

---

### 2.2. Python 3.11 (FastAPI / Poetry)

Eliminates compilation toolchains from the final image, runs an isolated virtual environment, compiles `.pyc` files ahead-of-time for deterministic startup times, and uses `dumb-init` for POSIX signal propagation.

```dockerfile
# syntax=docker/dockerfile:1.4
# Stage 1: Base Python configuration
FROM python:3.11.9-slim-bookworm AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    POETRY_VERSION=1.8.2 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    PYSETUP_PATH="/opt/pysetup" \
    VENV_PATH="/opt/pysetup/.venv"

ENV PATH="$POETRY_HOME/bin:$VENV_PATH/bin:$PATH"

# Stage 2: Install dependencies
FROM base AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl=7.88.1-10+deb12u5 \
    build-essential=12.9 \
    libpq-dev=15.6-0+deb12u1 \
    && rm -rf /var/lib/apt/lists/*

# Install poetry via official installer
RUN curl -sSL https://install.python-poetry.org | python3 -

WORKDIR $PYSETUP_PATH
COPY poetry.lock pyproject.toml ./
RUN poetry install --only main --no-root

# Stage 3: Runtime
FROM python:3.11.9-slim-bookworm AS runner
ENV PATH="/opt/pysetup/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    dumb-init=1.2.5-2 \
    libpq5=15.6-0+deb12u1 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 appgroup && \
    useradd --uid 10001 --gid appgroup --shell /usr/sbin/nologin --no-create-home appuser

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/pysetup/.venv /opt/pysetup/.venv
COPY --chown=10001:10001 app/ /app/app/

# Compile Python bytecode for fast container boot
RUN python -m compileall -b /app

USER 10001:10001

EXPOSE 8000

ENTRYPOINT ["/usr/bin/dumb-init", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--no-access-log"]
```

---

### 2.3. Go 1.22 (Statically Compiled Distroless)

Compiles Go code into a zero-dependency, static ELF binary (`CGO_ENABLED=0`), removes debugging symbol tables and DWARF data to minimize size, and executes on top of Google's static distroless runtime with no shell or package manager present.

```dockerfile
# syntax=docker/dockerfile:1.4
# Stage 1: Build static Go binary
FROM golang:1.22.2-bookworm AS builder

WORKDIR /src

# Download dependencies using caching mounts
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download -x

COPY . .

# Compile statically with optimizations
# -w: Omit DWARF symbol table
# -s: Omit symbol table and debug information
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -trimpath -ldflags="-w -s -extldflags '-static'" -o /bin/server ./cmd/api

# Stage 2: Minimal Distroless execution image
FROM gcr.io/distroless/static-debian12:nonroot

WORKDIR /
COPY --from=builder /bin/server /bin/server

# Uses nonroot UID 65532 pre-baked into Google distroless
USER 65532:65532

EXPOSE 8080

ENTRYPOINT ["/bin/server"]
```

---

### 2.4. Rust 1.77 (Cargo Multi-Stage Distroless)

Utilizes compilation cache layers to prevent rebuilding dependencies on source updates, outputs a stripped production release binary, and runs inside a minimal C-runtime distroless base.

```dockerfile
# syntax=docker/dockerfile:1.4
# Stage 1: Dependency recipe and build
FROM rust:1.77.2-slim-bookworm AS builder

WORKDIR /usr/src/app

# Pre-compile dependencies using a dummy entrypoint for caching
COPY Cargo.toml Cargo.lock ./
RUN mkdir src && echo "fn main() { println!(\"placeholder\"); }" > src/main.rs
RUN cargo build --release && rm -rf src

# Copy real source code and build final binary
COPY src/ ./src/
RUN touch src/main.rs && cargo build --release

# Strip debug symbols to reduce image footprint
RUN strip target/release/api-server

# Stage 2: Distroless with glibc runtime
FROM gcr.io/distroless/cc-debian12:nonroot

WORKDIR /app
COPY --from=builder --chown=nonroot:nonroot /usr/src/app/target/release/api-server /app/api-server

USER nonroot:nonroot

EXPOSE 8080
ENV RUST_LOG=info \
    RUST_BACKTRACE=1

ENTRYPOINT ["/app/api-server"]
```

---

## 3. Production Kubernetes Manifest Suite

The manifests below deploy a resilient, highly available service:
* **Microservice Topology**: `payment-api` running in namespace `production`.
* **Zero-Downtime Resilience**: 3 replicas, spread evenly across failure zones, managed by strict disruption budgets.
* **Security Enforcement**: Full Linux namespace isolation, read-only root filesystems, dropped capabilities.

```
                              [ Ingress Controller ]
                                        │ (TLS Termination)
                                        ▼
                             [ Service: payment-api ]
                                        │
           ┌────────────────────────────┼────────────────────────────┐
           ▼                            ▼                            ▼
[ Pod: payment-api-1 ]        [ Pod: payment-api-2 ]        [ Pod: payment-api-3 ]
 (Zone: us-east-1a)            (Zone: us-east-1b)            (Zone: us-east-1c)
 (Read-Only Root FS)           (Read-Only Root FS)           (Read-Only Root FS)
```

---

### 3.1. Deployment & PodDisruptionBudget

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: payment-api-pdb
  namespace: production
  labels:
    app.kubernetes.io/name: payment-api
    app.kubernetes.io/part-of: billing-platform
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: payment-api
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payment-api
  namespace: production
  labels:
    app.kubernetes.io/name: payment-api
    app.kubernetes.io/instance: payment-api-prod
    app.kubernetes.io/version: "1.4.2"
    app.kubernetes.io/component: backend
    app.kubernetes.io/part-of: billing-platform
    app.kubernetes.io/managed-by: gitops
spec:
  replicas: 3
  revisionHistoryLimit: 5
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 25%
      maxUnavailable: 0
  selector:
    matchLabels:
      app.kubernetes.io/name: payment-api
  template:
    metadata:
      labels:
        app.kubernetes.io/name: payment-api
        app.kubernetes.io/instance: payment-api-prod
        app.kubernetes.io/version: "1.4.2"
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/path: "/metrics"
        prometheus.io/port: "8080"
    spec:
      terminationGracePeriodSeconds: 60
      # Anti-affinity & Zone Topology Distribution
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              app.kubernetes.io/name: payment-api
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels:
              app.kubernetes.io/name: payment-api
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        runAsGroup: 10001
        fsGroup: 10001
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: payment-api
          image: registry.internal.net/billing/payment-api:v1.4.2@sha256:7f3b4822002167d499ec1fb45a27072c476722d5771abf81b190f84ae7ddfa98
          imagePullPolicy: IfNotPresent
          command: ["/bin/server"]
          ports:
            - name: http
              containerPort: 8080
              protocol: TCP
            - name: metrics
              containerPort: 9090
              protocol: TCP
          env:
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            - name: POD_NAMESPACE
              valueFrom:
                fieldRef:
                  fieldPath: metadata.namespace
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: payment-api-secrets
                  key: database-url
          resources:
            requests:
              cpu: "250m"
              memory: "512Mi"
            limits:
              cpu: "1000m"
              memory: "1Gi"
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            privileged: false
            capabilities:
              drop:
                - ALL
          volumeMounts:
            - name: ephemeral-tmp
              mountPath: /tmp
            - name: app-cache
              mountPath: /app/cache
          startupProbe:
            httpGet:
              path: /healthz/startup
              port: 8080
            failureThreshold: 30
            periodSeconds: 2
            timeoutSeconds: 2
          livenessProbe:
            httpGet:
              path: /healthz/liveness
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
            timeoutSeconds: 3
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /healthz/ready
              port: 8080
            initialDelaySeconds: 2
            periodSeconds: 5
            timeoutSeconds: 2
            successThreshold: 1
            failureThreshold: 2
          lifecycle:
            preStop:
              exec:
                command: ["/bin/sh", "-c", "sleep 15"]
      volumes:
        - name: ephemeral-tmp
          emptyDir:
            medium: Memory
            sizeLimit: 64Mi
        - name: app-cache
          emptyDir:
            medium: Memory
            sizeLimit: 128Mi
```

---

### 3.2. Service & Horizontal Pod Autoscaler (HPA v2)

This configuration drives scaling based on dual metrics: CPU consumption and sustained HTTP request load per replica.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: payment-api
  namespace: production
  labels:
    app.kubernetes.io/name: payment-api
spec:
  type: ClusterIP
  ports:
    - name: http
      port: 80
      targetPort: http
      protocol: TCP
    - name: metrics
      port: 9090
      targetPort: metrics
      protocol: TCP
  selector:
    app.kubernetes.io/name: payment-api
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: payment-api-hpa
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: payment-api
  minReplicas: 3
  maxReplicas: 15
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
    - type: Pods
      pods:
        metric:
          name: http_requests_per_second
        target:
          type: AverageValue
          averageValue: "850m"
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Percent
          value: 100
          periodSeconds: 15
        - type: Pods
          value: 4
          periodSeconds: 15
      selectPolicy: Max
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 10
          periodSeconds: 60
      selectPolicy: Min
```

---

### 3.3. Ingress Route (Ingress-NGINX + cert-manager)

Secured via automated TLS generation, proxy buffering, tight rate-limiting, and strict HSTS headers.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: payment-api-ingress
  namespace: production
  annotations:
    kubernetes.io/ingress.class: "nginx"
    cert-manager.io/cluster-issuer: "letsencrypt-production"
    nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
    nginx.ingress.kubernetes.io/proxy-body-size: "2m"
    nginx.ingress.kubernetes.io/proxy-connect-timeout: "5"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "30"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "30"
    nginx.ingress.kubernetes.io/proxy-next-upstream: "error timeout http_502 http_503"
    nginx.ingress.kubernetes.io/proxy-next-upstream-tries: "3"
    nginx.ingress.kubernetes.io/limit-rps: "100"
    nginx.ingress.kubernetes.io/limit-burst-multiplier: "5"
    nginx.ingress.kubernetes.io/configuration-snippet: |
      more_set_headers "X-Frame-Options: DENY";
      more_set_headers "X-Content-Type-Options: nosniff";
      more_set_headers "X-XSS-Protection: 1; mode=block";
      more_set_headers "Strict-Transport-Security: max-age=63072000; includeSubDomains; preload";
spec:
  tls:
    - hosts:
        - payment-api.platform.internal
      secretName: payment-api-tls-cert
  rules:
    - host: payment-api.platform.internal
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: payment-api
                port:
                  number: 80
```

---

### 3.4. Production StatefulSet with NVMe StorageClass (PostgreSQL 16)

This manifest demonstrates stateful workload orchestration. It provisions high-throughput, non-volatile block storage, sets deterministic initialization, isolates volume claims per replica, and configures an internal headless discovery service.

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: fast-nvme-sc
provisioner: pd.csi.storage.gke.io
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
parameters:
  type: pd-ssd
  replication-type: none
---
apiVersion: v1
kind: Service
metadata:
  name: postgres-cluster-headless
  namespace: production
  labels:
    app.kubernetes.io/name: postgres-cluster
spec:
  clusterIP: None
  ports:
    - port: 5432
      name: postgresql
  selector:
    app.kubernetes.io/name: postgres-cluster
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres-cluster
  namespace: production
  labels:
    app.kubernetes.io/name: postgres-cluster
spec:
  serviceName: "postgres-cluster-headless"
  replicas: 3
  podManagementPolicy: OrderedReady
  updateStrategy:
    type: RollingUpdate
  selector:
    matchLabels:
      app.kubernetes.io/name: postgres-cluster
  template:
    metadata:
      labels:
        app.kubernetes.io/name: postgres-cluster
    spec:
      terminationGracePeriodSeconds: 120
      securityContext:
        runAsNonRoot: true
        runAsUser: 999
        runAsGroup: 999
        fsGroup: 999
      containers:
        - name: postgresql
          image: postgres:16.2-bookworm
          imagePullPolicy: IfNotPresent
          env:
            - name: POSTGRES_DB
              value: "core_datastore"
            - name: POSTGRES_USER_FILE
              value: "/etc/postgres-secrets/username"
            - name: POSTGRES_PASSWORD_FILE
              value: "/etc/postgres-secrets/password"
            - name: PGDATA
              value: "/var/lib/postgresql/data/pgdata"
          ports:
            - containerPort: 5432
              name: postgresql
          resources:
            requests:
              cpu: "1"
              memory: "4Gi"
            limits:
              cpu: "4"
              memory: "16Gi"
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: false
            capabilities:
              drop:
                - ALL
          volumeMounts:
            - name: postgres-storage
              mountPath: /var/lib/postgresql/data
            - name: secrets
              mountPath: /etc/postgres-secrets
              readOnly: true
            - name: shm
              mountPath: /dev/shm
          readinessProbe:
            exec:
              command: ["psql", "-w", "-U", "postgres", "-c", "SELECT 1"]
            initialDelaySeconds: 10
            timeoutSeconds: 5
            periodSeconds: 10
          livenessProbe:
            exec:
              command: ["psql", "-w", "-U", "postgres", "-c", "SELECT 1"]
            initialDelaySeconds: 30
            timeoutSeconds: 5
            periodSeconds: 20
      volumes:
        - name: secrets
          secret:
            secretName: postgres-credentials
            defaultMode: 0400
        - name: shm
          emptyDir:
            medium: Memory
            sizeLimit: 1Gi
  volumeClaimTemplates:
    - metadata:
        name: postgres-storage
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: fast-nvme-sc
        resources:
          requests:
            storage: 250Gi
```

---

## 4. Production Verification & Validation Procedures

To verify that these manifests and Docker containers meet all hardened operational requirements, execute the following audit checklist against your artifacts:

### 4.1. Container Audit
```bash
# 1. Verify unprivileged execution identity
docker run --rm --entrypoint id payment-api:latest
# Expected output: uid=10001(nodeuser) gid=10001(nodejs) groups=10001(nodejs)

# 2. Verify write protections by testing explicit writes to the root filesystem
docker run --rm --read-only --entrypoint touch payment-api:latest /test-file
# Expected output: touch: cannot touch '/test-file': Read-only file system

# 3. Verify zero root escalations
docker run --rm --entrypoint whoami payment-api:latest
# Output must not be 'root'
```

### 4.2. Kubernetes Manifest Deployment Audit
```bash
# 1. Validate that manifest adheres to the Kubernetes Restricted Pod Security Standard
kubectl-slice -f payment-api.yaml -o ./manifests
kubeconform -strict -kubernetes-version 1.29.0 -summary ./manifests/*.yaml

# 2. Check for missing resource ceilings and non-standard permissions using kube-linter
kube-linter lint ./manifests/*.yaml
```

---

## 5. Security & Sizing Reference Matrix

| Workload Type | Base Image Pattern | Required Mounts | Initial Sizing (Req/Lim) | Probe Protocol |
| :--- | :--- | :--- | :--- | :--- |
| **API Services (Go/Rust)** | `gcr.io/distroless/static` | `emptyDir` on `/tmp` (Memory) | CPU: `100m`/`1000m`<br>RAM: `128Mi`/`512Mi` | HTTP `/healthz` (Port 8080) |
| **Dynamic Apps (Node/Python)** | `debian-slim` (User: non-root) | `emptyDir` on `/tmp`, `/app/cache` | CPU: `250m`/`2000m`<br>RAM: `512Mi`/`1.5Gi` | HTTP `/healthz` via dumb-init |
| **Datastores (Stateful)** | Official Distro (Debian-based) | Block volume, memory tmpfs `/dev/shm` | CPU: `2000m`/`8000m`<br>RAM: `8Gi`/`32Gi` | Exec CLI (`SELECT 1`) |
| **Queue Workers** | Distroless or Slim | `emptyDir` on `/tmp` | CPU: `500m`/`2000m`<br>RAM: `512Mi`/`2Gi` | Exec or Internal Metrics Poll |
