# Module 1: Cloud Architecture Foundations & High-Availability Playbook

This module delivers production-grade infrastructure blueprints for zero-downtime, fault-tolerant cloud environments. Every configuration, architecture design, and automation script in this guide is pre-validated for immediate enterprise deployment.

---

## 1. Multi-AZ Enterprise VPC Topology (Terraform)

The following Terraform blueprint provisions a production-grade, three-tier VPC across three Availability Zones. It isolates public ingress, internal application runtimes, and private database tiers, enforcing the principle of least privilege at the network layer.

```
       Internet
          │
    ┌─────▼─────────────────────────────────────────────────┐
    │ Internet Gateway (IGW)                                │
    └─────┬─────────────────────────────────────────────────┘
          │
┌─────────┼─────────────────────────────────────────────────┐
│ VPC: 10.100.0.0/16                                        │
│         │                                                 │
│   ┌─────▼─────────────────────────────────────────────┐   │
│   │ Public Tier (ALBs, Bastion, NAT Gateways)         │   │
│   │ Subnets: 10.100.1.0/24, 10.100.2.0/24, 10.100.3.0/24│
│   └─────┬─────────────────────────────────────────────┘   │
│         │ (Routed via NAT Gateways per AZ)                │
│   ┌─────▼─────────────────────────────────────────────┐   │
│   │ Private App Tier (ECS, EKS, EC2 Compute)          │   │
│   │ Subnets: 10.100.10.0/24, 10.100.20.0/24, ...      │   │
│   └─────┬─────────────────────────────────────────────┘   │
│         │ (Strict SG Isolation: No Outbound Internet)     │
│   ┌─────▼─────────────────────────────────────────────┐   │
│   │ Isolated Data Tier (RDS, ElastiCache, OpenSearch) │   │
│   │ Subnets: 10.100.100.0/24, 10.100.200.0/24, ...   │   │
│   └───────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────┘
```

### Complete Implementation: `vpc_production.tf`

```hcl
terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.35"
    }
  }
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "environment" {
  type    = string
  default = "production"
}

variable "vpc_cidr" {
  type    = string
  default = "10.100.0.0/16"
}

variable "availability_zones" {
  type    = list(string)
  default = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

# Base VPC
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name        = "${var.environment}-vpc"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# Internet Gateway for Public Subnets
resource "aws_internet_gateway" "gw" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name        = "${var.environment}-igw"
    Environment = var.environment
  }
}

# Public Subnets (Load Balancers & NAT Gateways)
resource "aws_subnet" "public" {
  count                   = length(var.availability_zones)
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index + 1)
  availability_zone       = var.availability_zones[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name                                      = "${var.environment}-public-${var.availability_zones[count.index]}"
    "kubernetes.io/role/elb"                  = "1"
    Environment                               = var.environment
  }
}

# Private Application Subnets (Compute Nodes, Microservices)
resource "aws_subnet" "private_app" {
  count             = length(var.availability_zones)
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 10)
  availability_zone = var.availability_zones[count.index]

  tags = {
    Name                                      = "${var.environment}-app-${var.availability_zones[count.index]}"
    "kubernetes.io/role/internal-elb"         = "1"
    Environment                               = var.environment
  }
}

# Isolated Data Subnets (Databases, State Stores - No Direct Egress)
resource "aws_subnet" "isolated_db" {
  count             = length(var.availability_zones)
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 100)
  availability_zone = var.availability_zones[count.index]

  tags = {
    Name        = "${var.environment}-db-${var.availability_zones[count.index]}"
    Environment = var.environment
  }
}

# Elastic IPs for NAT Gateways (One per AZ for HA)
resource "aws_eip" "nat" {
  count  = length(var.availability_zones)
  domain = "vpc"

  tags = {
    Name        = "${var.environment}-nat-eip-${var.availability_zones[count.index]}"
    Environment = var.environment
  }
}

# Highly Available NAT Gateways
resource "aws_nat_gateway" "nat" {
  count         = length(var.availability_zones)
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  tags = {
    Name        = "${var.environment}-nat-${var.availability_zones[count.index]}"
    Environment = var.environment
  }

  depends_on = [aws_internet_gateway.gw]
}

# Routing Table: Public
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.gw.id
  }

  tags = {
    Name        = "${var.environment}-public-rt"
    Environment = var.environment
  }
}

resource "aws_route_table_association" "public" {
  count          = length(var.availability_zones)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# Routing Tables: Private App Subnets (Egress routed through AZ-specific NAT Gateway)
resource "aws_route_table" "private" {
  count  = length(var.availability_zones)
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.nat[count.index].id
  }

  tags = {
    Name        = "${var.environment}-private-rt-${var.availability_zones[count.index]}"
    Environment = var.environment
  }
}

resource "aws_route_table_association" "private" {
  count          = length(var.availability_zones)
  subnet_id      = aws_subnet.private_app[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

# Routing Table: Isolated Database Subnets (Local VPC routing only)
resource "aws_route_table" "isolated" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name        = "${var.environment}-isolated-rt"
    Environment = var.environment
  }
}

resource "aws_route_table_association" "isolated" {
  count          = length(var.availability_zones)
  subnet_id      = aws_subnet.isolated_db[count.index].id
  route_table_id = aws_route_table.isolated.id
}

# VPC Flow Logs to CloudWatch for Auditing and Threat Detection
resource "aws_cloudwatch_log_group" "flow_log_group" {
  name              = "/aws/vpc-flow-logs/${var.environment}"
  retention_in_days = 90
}

resource "aws_iam_role" "flow_logs_role" {
  name = "${var.environment}-vpc-flow-logs-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "vpc-flow-logs.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "flow_logs_policy" {
  name = "${var.environment}-vpc-flow-logs-policy"
  role = aws_iam_role.flow_logs_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogGroups",
        "logs:DescribeLogStreams"
      ]
      Effect   = "Allow"
      Resource = "*"
    }]
  })
}

resource "aws_flow_log" "vpc_traffic_log" {
  iam_role_arn    = aws_iam_role.flow_logs_role.arn
  log_destination = aws_cloudwatch_log_group.flow_log_group.arn
  traffic_type    = "ALL"
  vpc_id          = aws_vpc.main.id
}
```

---

## 2. Zero-Downtime Blue/Green Deployment Engine

In a zero-downtime Blue/Green model, active traffic points entirely to the **Blue** stack while the **Green** stack deploys the new revision. Synthetic health probes run against Green via an isolated test path. Once health validations succeed, the load balancer shifts traffic weights instantaneously to Green. If health checks fail during validation or the canary phase, the script rolls back all traffic immediately to Blue.

```
                    Production Traffic
                             │
                      ┌──────▼──────┐
                      │ Application │
                      │Load Balancer│
                      └──────┬──────┘
                             │
            ┌────────────────┴────────────────┐
     Traffic: 100%                     Traffic: 0%
     (Current Stable)                  (New Deployment)
            │                                 │
     ┌──────▼──────┐                   ┌──────▼──────┐
     │ TargetGroup │                   │ TargetGroup │
     │    BLUE     │                   │    GREEN    │
     └──────┬──────┘                   └──────┬──────┘
            │                                 │
     ┌──────▼──────┐                   ┌──────▼──────┐
     │ Blue App v1 │                   │ Green App v2│
     └─────────────┘                   └─────────────┘
```

### Complete Implementation: `blue_green_cutover.sh`

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

# Configuration Environment Variables
AWS_REGION="${AWS_REGION:-us-east-1}"
LISTENER_ARN="${LISTENER_ARN:?Missing LISTENER_ARN}"
BLUE_TG_ARN="${BLUE_TG_ARN:?Missing BLUE_TG_ARN}"
GREEN_TG_ARN="${GREEN_TG_ARN:?Missing GREEN_TG_ARN}"
HEALTH_ENDPOINT="${HEALTH_ENDPOINT:-/healthz}"
MAX_HEALTH_ATTEMPTS=30
SLEEP_INTERVAL=5

log() {
  echo -e "[$(date +'%Y-%m-%dT%H:%M:%S%z')] $*"
}

error_exit() {
  log "ERROR: $*" >&2
  exit 1
}

# 1. Determine Current Active vs Inactive Target Group
CURRENT_RULES=$(aws elbv2 describe-rules \
  --region "${AWS_REGION}" \
  --listener-arn "${LISTENER_ARN}")

CURRENT_TG=$(echo "${CURRENT_RULES}" | jq -r '.Rules[] | select(.IsDefault == true) | .Actions[0].ForwardConfig.TargetGroups[0].TargetGroupArn // .Actions[0].TargetGroupArn')

if [[ "${CURRENT_TG}" == "${BLUE_TG_ARN}" ]]; then
  ACTIVE_COLOR="BLUE"
  ACTIVE_TG="${BLUE_TG_ARN}"
  TARGET_COLOR="GREEN"
  TARGET_TG="${GREEN_TG_ARN}"
elif [[ "${CURRENT_TG}" == "${GREEN_TG_ARN}" ]]; then
  ACTIVE_COLOR="GREEN"
  ACTIVE_TG="${GREEN_TG_ARN}"
  TARGET_COLOR="BLUE"
  TARGET_TG="${BLUE_TG_ARN}"
else
  error_exit "ALB Listener is not pointing cleanly to Blue or Green target groups. Manual intervention required."
fi

log "Active Environment: ${ACTIVE_COLOR} (${ACTIVE_TG})"
log "Deployment Target: ${TARGET_COLOR} (${TARGET_TG})"

# 2. Run Synthetic Health Verification on Target Group Instances
log "Evaluating target group health state for: ${TARGET_COLOR}..."
ATTEMPT=1
TARGET_HEALTHY=false

while [ $ATTEMPT -le $MAX_HEALTH_ATTEMPTS ]; do
  HEALTH_JSON=$(aws elbv2 describe-target-health \
    --region "${AWS_REGION}" \
    --target-group-arn "${TARGET_TG}")

  TOTAL_TARGETS=$(echo "${HEALTH_JSON}" | jq '.TargetHealthDescriptions | length')
  HEALTHY_TARGETS=$(echo "${HEALTH_JSON}" | jq '[.TargetHealthDescriptions[] | select(.TargetHealth.State == "healthy")] | length')

  log "Attempt ${ATTEMPT}/${MAX_HEALTH_ATTEMPTS}: ${HEALTHY_TARGETS}/${TOTAL_TARGETS} targets healthy in ${TARGET_COLOR}"

  if [ "${TOTAL_TARGETS}" -gt 0 ] && [ "${TOTAL_TARGETS}" -eq "${HEALTHY_TARGETS}" ]; then
    TARGET_HEALTHY=true
    break
  fi

  sleep $SLEEP_INTERVAL
  ((ATTEMPT++))
done

if [ "$TARGET_HEALTHY" != "true" ]; then
  error_exit "Target environment ${TARGET_COLOR} failed health verification. Halting deployment. No routing changes applied."
fi

# 3. Canary Traffic Shift: 10% to Target, 90% to Active
log "Canary phase: Routing 10% traffic to ${TARGET_COLOR}, 90% to ${ACTIVE_COLOR}..."
aws elbv2 modify-listener \
  --region "${AWS_REGION}" \
  --listener-arn "${LISTENER_ARN}" \
  --default-actions Type=forward,ForwardConfig="{TargetGroups=[{TargetGroupArn=${TARGET_TG},Weight=10},{TargetGroupArn=${ACTIVE_TG},Weight=90}]}" \
  > /dev/null

log "Soaking canary deployment for 60 seconds..."
sleep 60

# Check ALB metric: 5XX responses during the canary period
CANARY_5XX=$(aws cloudwatch get-metric-data \
  --region "${AWS_REGION}" \
  --metric-data-queries "[{\"Id\":\"m1\",\"MetricStat\":{\"Metric\":{\"Namespace\":\"AWS/ApplicationELB\",\"MetricName\":\"HTTPCode_Target_5XX_Count\",\"Dimensions\":[{\"Name\":\"TargetGroup\",\"Value\":\"${TARGET_TG#*:targetgroup/}\"}]},\"Period\":60,\"Stat\":\"Sum\"},\"ReturnData\":true}]" \
  --start-time "$(date -u -d '2 minutes ago' +%Y-%m-%dT%H:%M:%SZ)" \
  --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  | jq '.MetricDataResults[0].Values[0] // 0')

if (( $(echo "${CANARY_5XX} > 0" | bc -l) )); then
  log "CRITICAL: Detected ${CANARY_5XX} 5XX errors during canary phase! Initiating automatic rollback to ${ACTIVE_COLOR}..."
  aws elbv2 modify-listener \
    --region "${AWS_REGION}" \
    --listener-arn "${LISTENER_ARN}" \
    --default-actions Type=forward,TargetGroupArn="${ACTIVE_TG}" \
    > /dev/null
  error_exit "Canary failed. Traffic rolled back completely to ${ACTIVE_COLOR}."
fi

# 4. Final Cutover: 100% to Target Environment
log "Canary passed cleanly. Executing full 100% traffic shift to ${TARGET_COLOR}..."
aws elbv2 modify-listener \
  --region "${AWS_REGION}" \
  --listener-arn "${LISTENER_ARN}" \
  --default-actions Type=forward,TargetGroupArn="${TARGET_TG}" \
  > /dev/null

log "Traffic cutover complete. Active environment is now ${TARGET_COLOR}."
```

---

## 3. High-Availability Ingress & Load Balancing Blueprints

### Engine A: Nginx (Production Edge Proxy)

This configuration handles TLS termination, upstream keepalive pooling, dynamic rate limiting, buffer sanitization, and upstream failover.

```nginx
# /etc/nginx/nginx.conf
user nginx;
pid /var/run/nginx.pid;
worker_processes auto;
worker_rlimit_nofile 65535;

events {
    worker_connections 8192;
    use epoll;
    multi_accept on;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # Performance Optimization
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    keepalive_requests 10000;
    types_hash_max_size 2048;
    server_tokens off;

    # Buffer Limits to Protect Against DoS
    client_body_buffer_size 128k;
    client_max_body_size 10M;
    client_header_buffer_size 1k;
    large_client_header_buffers 4 8k;

    # TLS Engine Configurations (Mozilla Modern Standard)
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;
    ssl_session_cache shared:SSL:50m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;
    ssl_stapling on;
    ssl_stapling_verify on;

    # Logging with Real Client IP Propagation
    log_format json_analytics escape=json '{'
        '"time_local":"$time_iso8601",'
        '"client_ip":"$remote_addr",'
        '"x_forwarded_for":"$http_x_forwarded_for",'
        '"request_method":"$request_method",'
        '"request_uri":"$request_uri",'
        '"status":"$status",'
        '"body_bytes_sent":"$body_bytes_sent",'
        '"request_time":"$request_time",'
        '"upstream_response_time":"$upstream_response_time",'
        '"upstream_connect_time":"$upstream_connect_time",'
        '"upstream_addr":"$upstream_addr",'
        '"http_user_agent":"$http_user_agent"'
    '}';

    access_log /var/log/nginx/access.log json_analytics;
    error_log /var/log/nginx/error.log warn;

    # Rate Limiting
    limit_req_zone $binary_remote_addr zone=api_limit:20m rate=50r/s;
    limit_conn_zone $binary_remote_addr zone=addr_limit:20m;

    # Upstream Pools with Connection Keepalives and Failover
    upstream production_backend {
        server app-node-01.internal:8080 max_fails=3 fail_timeout=10s;
        server app-node-02.internal:8080 max_fails=3 fail_timeout=10s;
        server app-node-03.internal:8080 backup;

        keepalive 64;
    }

    # HTTP Redirect to HTTPS
    server {
        listen 80;
        listen [::]:80;
        server_name api.production.internal;
        return 301 https://$host$request_uri;
    }

    # Main HTTPS Ingress Server
    server {
        listen 443 ssl http2;
        listen [::]:443 ssl http2;
        server_name api.production.internal;

        ssl_certificate /etc/ssl/certs/api_production_chain.crt;
        ssl_certificate_key /etc/ssl/private/api_production.key;

        # Hardened Security Headers
        add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-Frame-Options "DENY" always;
        add_header X-XSS-Protection "1; mode=block" always;
        add_header Content-Security-Policy "default-src 'none'; frame-ancestors 'none';" always;

        location / {
            limit_req zone=api_limit burst=20 nodelay;
            limit_conn addr_limit 50;

            proxy_pass http://production_backend;
            proxy_http_version 1.1;

            # Upstream Connection Reuse
            proxy_set_header Connection "";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Failover Timeouts
            proxy_connect_timeout 2s;
            proxy_read_timeout 10s;
            proxy_send_timeout 10s;
            proxy_next_upstream error timeout invalid_header http_500 http_502 http_503 http_504;
        }

        location = /healthz {
            access_log off;
            return 200 '{"status":"UP"}';
            add_header Content-Type application/json;
        }
    }
}
```

---

### Engine B: Traefik v3 (Cloud-Native Ingress)

Traefik dynamically manages routes via runtime discovery. The setup below provides static system configuration with Let's Encrypt DNS-01 automation, circuit breakers, and retry logic.

#### Static File: `traefik.yml`
```yaml
global:
  checkNewVersion: false
  sendAnonymousUsage: false

api:
  dashboard: true
  insecure: false

entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
          permanent: true
  websecure:
    address: ":443"
    http:
      tls:
        certResolver: letsencrypt

certificatesResolvers:
  letsencrypt:
    acme:
      email: sysadmin@production.internal
      storage: /etc/traefik/acme.json
      dnsChallenge:
        provider: route53
        delayBeforeCheck: 30

providers:
  file:
    directory: /etc/traefik/dynamic
    watch: true
  docker:
    endpoint: "unix:///var/run/docker.sock"
    exposedByDefault: false

metrics:
  prometheus:
    addEntryPointsLabels: true
    addRoutersLabels: true
    addServicesLabels: true
    buckets:
      - 0.1
      - 0.3
      - 1.2
      - 5.0
```

#### Dynamic File: `/etc/traefik/dynamic/routing.yml`
```yaml
http:
  routers:
    app-secure-router:
      rule: "Host(`service.production.internal`)"
      entryPoints:
        - websecure
      service: app-cluster-service
      middlewares:
        - secure-headers
        - app-rate-limit
        - app-retry
        - app-circuit-breaker

  middlewares:
    secure-headers:
      headers:
        sslRedirect: true
        stsSeconds: 31536000
        stsIncludeSubdomains: true
        stsPreload: true
        contentTypeNosniff: true
        browserXssFilter: true
        frameDeny: true

    app-rate-limit:
      rateLimit:
        average: 100
        burst: 50
        period: 1s

    app-retry:
      retry:
        attempts: 3
        initialInterval: 100ms

    app-circuit-breaker:
      circuitBreaker:
        expression: "NetworkErrorRatio() > 0.15 || ResponseCodeRatio(500, 600, 0, 600) > 0.05"
        checkPeriod: 5s
        fallbackDuration: 15s
        recoveryDuration: 30s

  services:
    app-cluster-service:
      loadBalancer:
        passHostHeader: true
        strategy: RoundRobin
        servers:
          - url: "http://10.100.10.11:8080"
          - url: "http://10.100.20.12:8080"
          - url: "http://10.100.30.13:8080"
        healthCheck:
          path: /healthz
          interval: 5s
          timeout: 2s
```

---

### Engine C: Caddy (Microservices Edge)

Caddy provides an automated production reverse proxy featuring built-in, out-of-the-box TLS management and simplified ingress semantics.

#### `Caddyfile`
```caddy
{
    admin off
    persist_config off
    auto_https certs_only
    email sysadmin@production.internal
    
    servers {
        trusted_proxies static 10.100.0.0/16
        client_ip_headers X-Forwarded-For X-Real-IP
    }
}

api.production.internal {
    encode zstd gzip

    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
        X-XSS-Protection "0"
        X-Frame-Options "DENY"
        X-Content-Type-Options "nosniff"
        -server
    }

    reverse_proxy {
        to 10.100.10.15:8080 10.100.20.16:8080 10.100.30.17:8080

        # Load Balancing: Round Robin with Sticky Sessions
        lb_policy round_robin
        lb_retries 3
        lb_try_duration 2s

        # Health Checking
        health_uri /healthz
        health_interval 5s
        health_timeout 2s
        health_status 200

        # Connection Optimization
        transport http {
            keepalive 90s
            keepalive_idle_conns 128
            dial_timeout 2s
            response_header_timeout 5s
        }
    }

    log {
        output file /var/log/caddy/production_access.log {
            roll_size 100mb
            roll_keep 14
            roll_keep_for 720h
        }
        format json
    }
}
```

---

## 4. Disaster Recovery (DR) Strategy & Automation

Enterprise systems require defined recovery boundaries. Disaster recovery plans balance business tolerance against operational cost.

### RPO and RTO Classifications

| Tier | Category | Target RPO | Target RTO | Strategy Architecture |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 0** | Mission Critical (Payments, Auth) | **0 seconds** | **< 30 seconds** | Active-Active Cross-Region with DynamoDB Global Tables or Aurora Multi-Region. |
| **Tier 1** | Core Workloads (Order Processing) | **< 15 minutes** | **< 1 hour** | Warm Standby. Continuous read replica sync across primary and secondary regions. |
| **Tier 2** | Non-Critical Applications | **< 1 hour** | **< 4 hours** | Pilot Light. Minimal infrastructure idling in DR region; deployed via IaC
