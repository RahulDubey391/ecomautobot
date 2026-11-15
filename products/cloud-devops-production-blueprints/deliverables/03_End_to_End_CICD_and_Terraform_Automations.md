# Module 3: Full-Stack CI/CD Pipelines & Modular Infrastructure-as-Code

This module contains production-tested CI/CD pipelines, keyless OIDC authentication patterns, and modular Infrastructure-as-Code (IaC) blueprints. Every pipeline includes automated vulnerability gating, software bill of materials (SBOM) generation, container signing, and progressive rollout validation.

---

## 1. Enterprise GitHub Actions Pipeline

This pipeline implements a secure software supply chain compliant with SLSA Level 3 principles: automated testing, static analysis, container image vulnerability scanning with Trivy, SBOM generation with Syft, keyless image signing via Cosign and Sigstore, and automated deployment with health checks.

Save this configuration as `.github/workflows/production-pipeline.yml`:

```yaml
name: Production CI/CD Pipeline

on:
  push:
    branches:
      - main
    tags:
      - 'v*.*.*'
  pull_request:
    branches:
      - main

permissions:
  id-token: write
  contents: read
  packages: write
  security-events: write

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}
  AWS_REGION: us-east-1
  AWS_ROLE_ARN: arn:aws:iam::123456789012:role/github-actions-production-deployer
  EKS_CLUSTER_NAME: production-core-eks

jobs:
  lint-and-test:
    name: Code Quality & Unit Tests
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Source Code
        uses: actions/checkout@v4

      - name: Set up Go Runtime
        uses: actions/setup-go@v5
        with:
          go-version: '1.22'
          cache: true

      - name: Run GolangCI-Lint
        uses: golangci/golangci-lint-action@v4
        with:
          version: v1.56.2
          args: --timeout=5m --issues-exit-code=1

      - name: Execute Unit Tests with Coverage
        run: |
          go test -v -race -coverprofile=coverage.out -covermode=atomic ./...

      - name: Verify Test Coverage Threshold
        run: |
          COVERAGE=$(go tool cover -func=coverage.out | grep total | awk '{print substr($3, 1, length($3)-1)}')
          echo "Current test coverage: ${COVERAGE}%"
          REQUIRED_COVERAGE=80.0
          if (( $(echo "$COVERAGE < $REQUIRED_COVERAGE" | bc -l) )); then
            echo "ERROR: Test coverage (${COVERAGE}%) is below the required threshold (${REQUIRED_COVERAGE}%)."
            exit 1
          fi

  security-scan:
    name: SAST & Dependency Auditing
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Source Code
        uses: actions/checkout@v4

      - name: Run Govulncheck (Go Vulnerability Database)
        run: |
          go install golang.org/x/vuln/cmd/govulncheck@latest
          govulncheck ./...

      - name: Run Gitleaks Secret Scanner
        uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

  build-and-sign:
    name: Multi-Arch Build, Trivy Gate & Cosign Sign
    needs: [lint-and-test, security-scan]
    runs-on: ubuntu-latest
    outputs:
      image_digest: ${{ steps.build-push.outputs.digest }}
      image_tag: ${{ steps.meta.outputs.version }}
    steps:
      - name: Checkout Source Code
        uses: actions/checkout@v4

      - name: Install Cosign
        uses: sigstore/cosign-installer@v3.4.0

      - name: Set up QEMU for Multi-Arch Builds
        uses: docker/setup-qemu-action@v3

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Extract Docker Metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=ref,event=branch
            type=semver,pattern={{version}}
            type=sha,format=long

      - name: Log in to GitHub Container Registry
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build Container Image Locally for Scanning
        uses: docker/build-push-action@v5
        with:
          context: .
          load: true
          tags: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:local-scan
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Run Trivy Security Vulnerability Scan
        uses: aquasecurity/trivy-action@0.18.0
        with:
          image-ref: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:local-scan
          format: 'sarif'
          output: 'trivy-results.sarif'
          severity: 'CRITICAL,HIGH'
          exit-code: '1'
          ignore-unfixed: true

      - name: Upload Trivy Scan Results to GitHub Security Tab
        if: always()
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: 'trivy-results.sarif'

      - name: Build and Push Multi-Architecture Image
        id: build-push
        uses: docker/build-push-action@v5
        with:
          context: .
          platforms: linux/amd64,linux/arm64
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Generate Software Bill of Materials (SBOM) using Syft
        uses: anchore/sbom-action@v0.15.8
        with:
          image: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}@${{ steps.build-push.outputs.digest }}
          format: spdx-json
          output-file: sbom.spdx.json

      - name: Sign Container Image and Attest SBOM with Cosign (Keyless)
        run: |
          cosign sign --yes "${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}@${{ steps.build-push.outputs.digest }}"
          cosign attest --yes --predicate sbom.spdx.json --type spdx "${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}@${{ steps.build-push.outputs.digest }}"

  deploy-production:
    name: Verify Rollout & Zero-Downtime Deployment
    needs: [build-and-sign]
    if: github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/tags/v')
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Source Code
        uses: actions/checkout@v4

      - name: Authenticate to AWS via OIDC
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ env.AWS_ROLE_ARN }}
          aws-region: ${{ env.AWS_REGION }}
          audience: sts.amazonaws.com

      - name: Configure Kubectl for Amazon EKS
        run: |
          aws eks update-kubeconfig --region ${{ env.AWS_REGION }} --name ${{ env.EKS_CLUSTER_NAME }}

      - name: Set up Helm 3
        uses: azure/setup-helm@v4
        with:
          version: v3.14.2

      - name: Deploy Production Release via Helm
        env:
          IMAGE_TAG: ${{ needs.build-and-sign.outputs.image_tag }}
          IMAGE_DIGEST: ${{ needs.build-and-sign.outputs.image_digest }}
        run: |
          helm upgrade --install production-app ./deploy/helm/production-app \
            --namespace production \
            --create-namespace \
            --set image.repository="${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}" \
            --set image.digest="${IMAGE_DIGEST}" \
            --values ./deploy/helm/production-app/values-production.yaml \
            --wait \
            --timeout 5m0s \
            --atomic

      - name: Run Post-Deployment Synthetic Integration Health Checks
        run: |
          ENDPOINT="https://api.production.internal/healthz"
          echo "Executing health checks against: ${ENDPOINT}"
          for i in {1..30}; do
            STATUS=$(curl --write-out "%{http_code}" --silent --output /dev/null --fail "${ENDPOINT}" || true)
            if [ "$STATUS" -eq 200 ]; then
              echo "Health verification passed successfully with HTTP 200."
              exit 0
            fi
            echo "Attempt $i: Received status $STATUS. Retrying in 5 seconds..."
            sleep 5
          done
          echo "ERROR: Health check timed out after 150 seconds."
          exit 1
```

---

## 2. GitLab CI Enterprise Pipeline with Review Apps & Auto-Rollback

This `.gitlab-ci.yml` pipeline provides:
- Automated merge request validation with ephemeral review apps deployed to dynamic namespaces.
- Native integration with GitLab container scanning and SAST.
- Atomic production rollouts with automated rollbacks if post-deployment checks fail.

Save this file as `.gitlab-ci.yml`:

```yaml
stages:
  - test
  - security
  - build
  - review
  - deploy
  - verify

variables:
  DOCKER_DRIVER: overlay2
  DOCKER_TLS_CERTDIR: ""
  CONTAINER_RELEASE_IMAGE: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
  CONTAINER_LATEST_IMAGE: $CI_REGISTRY_IMAGE:latest
  KUBE_NAMESPACE_BASE: "review"

default:
  image: alpine:3.19
  interruptible: true

lint:go:
  stage: test
  image: golangci/golangci-lint:v1.56.2
  script:
    - golangci-lint run --timeout 5m

test:unit:
  stage: test
  image: golang:1.22
  script:
    - go test -v -race -covermode=atomic ./...

security:container-scan:
  stage: security
  image:
    name: aquasec/trivy:0.49.1
    entrypoint: [""]
  variables:
    GIT_STRATEGY: none
  script:
    - trivy image --download-db-only
    - trivy image --exit-code 0 --severity HIGH,CRITICAL --format json --output gl-container-scanning-report.json $CONTAINER_RELEASE_IMAGE
    - trivy image --exit-code 1 --severity CRITICAL --ignore-unfixed $CONTAINER_RELEASE_IMAGE
  artifacts:
    reports:
      container_scanning: gl-container-scanning-report.json
    paths:
      - gl-container-scanning-report.json
    when: always
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
    - if: $CI_MERGE_REQUEST_IID

build:docker:
  stage: build
  image: docker:25.0.3
  services:
    - docker:25.0.3-dind
  before_script:
    - echo "$CI_REGISTRY_PASSWORD" | docker login -u "$CI_REGISTRY_USER" --password-stdin $CI_REGISTRY
  script:
    - docker build --pull -t $CONTAINER_RELEASE_IMAGE -t $CONTAINER_LATEST_IMAGE .
    - docker push $CONTAINER_RELEASE_IMAGE
    - docker push $CONTAINER_LATEST_IMAGE

deploy:review:
  stage: review
  image: dtzar/helm-kubectl:3.14.2
  variables:
    KUBE_NAMESPACE: "${KUBE_NAMESPACE_BASE}-${CI_MERGE_REQUEST_IID}"
    HELM_RELEASE_NAME: "review-${CI_MERGE_REQUEST_IID}"
  script:
    - kubectl create namespace $KUBE_NAMESPACE --dry-run=client -o yaml | kubectl apply -f -
    - >
      helm upgrade --install $HELM_RELEASE_NAME ./deploy/helm/app
      --namespace $KUBE_NAMESPACE
      --set image.tag=$CI_COMMIT_SHA
      --set ingress.host="mr-${CI_MERGE_REQUEST_IID}.preview.example.com"
      --wait --timeout 3m0s
  environment:
    name: review/$CI_BUILD_REF_NAME
    url: https://mr-${CI_MERGE_REQUEST_IID}.preview.example.com
    on_stop: stop:review
    auto_stop_in: 1 week
  rules:
    - if: '$CI_MERGE_REQUEST_IID'

stop:review:
  stage: review
  image: dtzar/helm-kubectl:3.14.2
  variables:
    GIT_STRATEGY: none
    KUBE_NAMESPACE: "${KUBE_NAMESPACE_BASE}-${CI_MERGE_REQUEST_IID}"
    HELM_RELEASE_NAME: "review-${CI_MERGE_REQUEST_IID}"
  script:
    - helm uninstall $HELM_RELEASE_NAME --namespace $KUBE_NAMESPACE || true
    - kubectl delete namespace $KUBE_NAMESPACE || true
  environment:
    name: review/$CI_BUILD_REF_NAME
    action: stop
  rules:
    - if: '$CI_MERGE_REQUEST_IID'
      when: manual

deploy:production:
  stage: deploy
  image: dtzar/helm-kubectl:3.14.2
  variables:
    KUBE_NAMESPACE: "production"
    HELM_RELEASE_NAME: "app-prod"
  script:
    - >
      helm upgrade --install $HELM_RELEASE_NAME ./deploy/helm/app
      --namespace $KUBE_NAMESPACE
      --set image.tag=$CI_COMMIT_SHA
      --values ./deploy/helm/app/values-production.yaml
      --atomic
      --timeout 5m0s
  environment:
    name: production
    url: https://production.example.com
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'

verify:production:
  stage: verify
  image: curlimages/curl:8.6.0
  variables:
    KUBE_NAMESPACE: "production"
    HELM_RELEASE_NAME: "app-prod"
  script:
    - echo "Validating live production HTTP endpoints..."
    - |
      for i in {1..20}; do
        HTTP_RESPONSE=$(curl -k -s -o /dev/null -w "%{http_code}" https://production.example.com/healthz || true)
        if [ "$HTTP_RESPONSE" -eq 200 ]; then
          echo "Health check validated: HTTP 200 received."
          exit 0
        fi
        echo "Attempt $i failed with status: $HTTP_RESPONSE. Waiting 5s..."
        sleep 5
      done
      echo "Health checks failed after 100 seconds. Triggering automated rollback!"
      exit 1
  after_script:
    - |
      if [ $CI_JOB_STATUS != 'success' ]; then
        echo "Executing automated Helm rollback to prior successful release..."
        helm rollback $HELM_RELEASE_NAME 0 --namespace $KUBE_NAMESPACE
      fi
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

---

## 3. Modular Infrastructure-as-Code Patterns

### Blueprint A: AWS EKS VPC & Cluster Module with IRSA & Bottlerocket

This configuration provisions an EKS cluster with managed Bottlerocket node groups, IMDSv2 enforcement, public endpoint protection, and IRSA support.

```hcl
# main.tf (AWS EKS Module)
terraform {
  required_version = ">= 1.7.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}

variable "environment" {
  type        = string
  description = "Target deployment environment (e.g., prod, staging)"
  default     = "prod"
}

variable "cluster_name" {
  type        = string
  description = "The unique identifier for the EKS Cluster"
  default     = "core-prod-eks"
}

variable "vpc_cidr" {
  type        = string
  description = "CIDR block for the dedicated VPC"
  default     = "10.0.0.0/16"
}

data "aws_availability_zones" "available" {
  state = "available"
}

# ---------------------------------------------------------
# Network Architecture
# ---------------------------------------------------------
resource "aws_vpc" "eks_vpc" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name                                        = "${var.cluster_name}-vpc"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }
}

resource "aws_subnet" "public" {
  count                   = 3
  vpc_id                  = aws_vpc.eks_vpc.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 4, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = false

  tags = {
    Name                                        = "${var.cluster_name}-public-subnet-${count.index}"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
    "kubernetes.io/role/elb"                    = "1"
  }
}

resource "aws_subnet" "private" {
  count             = 3
  vpc_id            = aws_vpc.eks_vpc.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 4, count.index + 4)
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = {
    Name                                        = "${var.cluster_name}-private-subnet-${count.index}"
    "kubernetes.io/cluster/${var.cluster_name}" = "owned"
    "kubernetes.io/role/internal-elb"           = "1"
    "karpenter.sh/discovery"                    = var.cluster_name
  }
}

resource "aws_internet_gateway" "gw" {
  vpc_id = aws_vpc.eks_vpc.id
  tags = {
    Name = "${var.cluster_name}-igw"
  }
}

resource "aws_eip" "nat" {
  domain = "vpc"
  tags = {
    Name = "${var.cluster_name}-nat-eip"
  }
}

resource "aws_nat_gateway" "nat" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id
  tags = {
    Name = "${var.cluster_name}-nat-gw"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.eks_vpc.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.gw.id
  }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.eks_vpc.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.nat.id
  }
}

resource "aws_route_table_association" "public" {
  count          = 3
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  count          = 3
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# ---------------------------------------------------------
# AWS EKS Cluster
# ---------------------------------------------------------
resource "aws_iam_role" "cluster_role" {
  name = "${var.cluster_name}-control-plane-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "eks.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "cluster_policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
  role       = aws_iam_role.cluster_role.name
}

resource "aws_eks_cluster" "primary" {
  name     = var.cluster_name
  version  = "1.29"
  role_arn = aws_iam_role.cluster_role.arn

  vpc_config {
    subnet_ids              = concat(aws_subnet.public[*].id, aws_subnet.private[*].id)
    endpoint_private_access = true
    endpoint_public_access  = false # Restricts access entirely to internal networks / VPN
  }

  enabled_cluster_log_types = ["api", "audit", "authenticator", "controllerManager", "scheduler"]

  depends_on = [aws_iam_role_policy_attachment.cluster_policy]
}

# ---------------------------------------------------------
# OIDC Provider Configuration for IRSA
# ---------------------------------------------------------
data "tls_certificate" "cluster" {
  url = aws_eks_cluster.primary.identity[0].oidc[0].issuer
}

resource "aws_iam_openid_connect_provider" "oidc" {
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.cluster.thumbprints[0]]
  url             = aws_eks_cluster.primary.identity[0].oidc[0].issuer
}

# ---------------------------------------------------------
# Bottlerocket Managed Node Group
# ---------------------------------------------------------
resource "aws_iam_role" "node_role" {
  name = "${var.cluster_name}-node-group-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "worker_node" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
  role       = aws_iam_role.node_role.name
}

resource "aws_iam_role_policy_attachment" "cni" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
  role       = aws_iam_role.node_role.name
}

resource "aws_iam_role_policy_attachment" "registry" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
  role       = aws_iam_role.node_role.name
}

resource "aws_eks_node_group" "system_nodes" {
  cluster_name    = aws_eks_cluster.primary.name
  node_group_name = "system-bottlerocket-workers"
  node_role_arn   = aws_iam_role.node_role.arn
  subnet_ids      = aws_subnet.private[*].id
  ami_type        = "BOTTLEROCKET_x86_64"
  instance_types  = ["m6i.xlarge"]

  scaling_config {
    desired_size = 3
    max_size     = 10
    min_size     = 3
  }

  update_config {
    max_unavailable = 1
  }

  labels = {
    role = "system"
  }

  depends_on = [
    aws_iam_role_policy_attachment.worker_node,
    aws_iam_role_policy_attachment.cni,
    aws_iam_role_policy_attachment.registry,
  ]
}

output "eks_cluster_name" {
  value = aws_eks_cluster.primary.name
}

output "eks_oidc_provider_arn" {
  value = aws_iam_openid_connect_provider.oidc.arn
}
```

---

### Blueprint B: Hetzner Cloud (hcloud) Lightweight K3s Architecture

This setup provisions an economical, production-grade K3s cluster on Hetzner Cloud. It uses internal private networks, strict host firewalls, cloud-init automated provisioning, and automated token registration.

```hcl
# main.tf (Hetzner Cloud K3s Module)
terraform {
  required_version = ">= 1.7.0"
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.45"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

variable "hcloud_token" {
  type        = string
  sensitive   = true
  description = "Hetzner Cloud API Token"
}

variable "location" {
  type        = string
  default     = "fsn1" # Falkenstein, Germany
}

variable "server_type" {
  type        = string
  default     = "cpx31" # 4 vCPU, 8GB RAM, Dedicated AMD
}

provider "hcloud" {
  token = var.hcloud_token
}

resource "random_password" "k3s_cluster_token" {
  length  = 48
  special = false
}

# ---------------------------------------------------------
# Private Network Structure
# ---------------------------------------------------------
resource "hcloud_network" "k3s_network" {
  name     = "k3s-internal-net"
  ip_range = "10.10.0.0/16"
}

resource "hcloud_network_subnet" "k3s_subnet" {
  network_id   = hcloud_network.k3s_network.id
  type         = "cloud"
  network_zone = "eu-central"
  ip_range     = "10.10.1.0/24"
}

# ---------------------------------------------------------
# Stateful Firewall Architecture
# ---------------------------------------------------------
resource "hcloud_firewall" "k3s_firewall" {
  name = "k3s-node-firewall"

  # SSH Restricted Access
  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "22"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }

  # Kubernetes API Endpoint
  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "6443"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }

  # WireGuard flannel backend / Intra-node communication
  rule {
    direction = "in"
    protocol  = "udp"
    port      = "51820"
    source_ips = [
      "10.10.0.0/16"
    ]
  }

  # Node-to-node flannel VXLAN
  rule {
    direction = "in"
    protocol  = "udp"
    port      = "8472"
    source_ips = [
      "10.10.0.0/16"
    ]
  }

  # Kubelet internal metrics
  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "10250"
    source_ips = [
      "10.10.0.0/16"
    ]
  }
}

# ---------------------------------------------------------
# Control Plane Node
# ---------------------------------------------------------
resource "hcloud_server" "k3s_master" {
  name        = "k3s-control-plane-01"
  image       = "ubuntu-22.04"
  server_type = var.server_type
  location
