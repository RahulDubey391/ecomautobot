# Module 4: Master Pen-Test Checklist, CI/CD Security Scanners & Incident Playbook

---

## 1. 65-Point Pre-Launch API Security Audit Rubric

Every production API endpoint must be audited against this 65-point verification matrix prior to deployment. Violations of Category A or B block deployment unconditionally.

### Category A: Authentication & Identity Assurance (Items 1–15)

| ID | Security Verification Check | Attack Vector / Exploit Scenario | Verification Method / CLI Command | Pass Criteria |
|---|---|---|---|---|
| **01** | JWT `alg: none` Rejection | Attacker changes header to `{"alg":"none"}` and strips signature to forge admin claims. | `jwt_tool.py <TOKEN> -X a` | API responds with `401 Unauthorized`; token rejected. |
| **02** | Asymmetric-to-Symmetric Key Confusion (RS256 to HS256) | Public key used as HMAC secret when token header altered to `{"alg":"HS256"}`. | `jwt_tool.py <TOKEN> -S hs256 -k public.pem` | Verification fails; server refuses HS256 signatures when configured for RS256/ES256. |
| **03** | Missing JWT Expiration (`exp`) Validation | Replay of intercepted access tokens indefinitely. | `curl -H "Authorization: Bearer <EXPIRED_TOKEN>" https://api.domain.com/v1/user` | API returns `401 Unauthorized` with error code `TOKEN_EXPIRED`. |
| **04** | Critical Claim Enforcement (`iss`, `aud`, `nbf`) | Token issued for third-party client accepted by core internal API. | Forge token with modified `aud: "client-b"` against endpoint expecting `aud: "client-a"`. | API rejects token with `401 Unauthorized` on audience or issuer mismatch. |
| **05** | Refresh Token Single-Use & Family Invalidation | Intercepted refresh token used concurrently by victim and attacker. | Issue refresh request twice simultaneously: `curl -X POST /auth/refresh -d '{"refresh_token":"rt_123"}'` | Second request triggers revocation of the entire token family; both tokens invalidated. |
| **06** | PKCE Enforcement on Public Clients | Auth code interception via custom URI schemes on mobile/SPA. | Send auth code exchange without `code_verifier` or with invalid hash. | Token endpoint returns `400 Bad Request` with `invalid_grant`. |
| **07** | Strict Redirect URI Matching | Open redirect exploitation via parameter poisoning (`?redirect_uri=https://attacker.com`). | Submit OAuth request with `https://api.domain.com/oauth/callback/../../attacker`. | Server rejects request; requires exact byte-for-byte URI whitelist match. |
| **08** | Client Secret Storage in Native/SPA Apps | Extraction of hardcoded `client_secret` via binary disassembly. | Run `strings <binary>` or inspect client-side JS bundles. | Zero hardcoded client secrets; native clients use PKCE without client secrets. |
| **09** | Mutual TLS (mTLS) for B2B API Channels | Man-in-the-Middle (MitM) credential theft on server-to-server traffic. | `curl -k https://b2b.domain.com/v1/transfers` (without client cert). | Connection rejected at TLS handshake (`496 No Cert` / TLS Alert 42). |
| **10** | Session Revocation on Password Reset | Active sessions persist after credential compromise recovery. | Issue password reset; submit previously valid access/refresh token to protected route. | Previously issued tokens rejected; session store purge verified in Redis/DB. |
| **11** | Weak Ephemeral Key Entropy | Predictable state or challenge parameters vulnerable to collision. | Collect 10,000 auth states; run Shannon entropy test (`ent` utility). | Entropy score >= 7.999 bits per byte; values generated via cryptographically secure PRNG. |
| **12** | API Key Leakage via Query Strings | API keys harvested from access logs, browser history, and proxy servers. | Send `GET /v1/data?api_key=secret123`; inspect reverse proxy logs. | Server rejects query string auth (`401`); accepts exclusively `Authorization` or `X-API-Key` headers. |
| **13** | Brute-Force Defense on Token Endpoints | Distributed credential stuffing targeting `/oauth/token`. | Execute Hydra: `hydra -l user@domain.com -P passlist.txt api.domain.com http-post-form` | IP and account locked after 5 failed attempts within 60 seconds; returns `429 Too Many Requests`. |
| **14** | Clock Skew Allowance Limit | Token accepted hours after official expiration due to excessive skew config. | Craft token with `exp` = (Current Time - 120 seconds). | Token rejected; skew tolerance must not exceed 60 seconds. |
| **15** | Token Binding Verification (DPoP / mTLS) | Stolen access tokens replayed from unauthenticated network addresses. | Extract token; replay from a secondary machine without DPoP private key. | API fails verification with `401 Unauthorized` (`invalid_dpop_proof`). |

### Category B: Authorization & Access Control (BOLA/BFLA) (Items 16–30)

| ID | Security Verification Check | Attack Vector / Exploit Scenario | Verification Method / CLI Command | Pass Criteria |
|---|---|---|---|---|
| **16** | BOLA / IDOR on Resource Identifiers | Tenant A modifies or reads Tenant B data by swapping UUIDs. | `curl -H "Authorization: Bearer <TOKEN_USER_A>" https://api.domain.com/v1/orders/<UUID_TENANT_B>` | Server returns `404 Not Found` or `403 Forbidden`; no data leakage. |
| **17** | Function-Level Access (BFLA) on Administrative Routes | Regular user invokes admin endpoints by guessing URL paths. | `curl -H "Authorization: Bearer <TOKEN_REGULAR_USER>" -X DELETE https://api.domain.com/v1/users/<ID>` | Returns `403 Forbidden`; RBAC engine checks claims before route handler execution. |
| **18** | Multi-Tenant Data Separation at Database Layer | ORM injection or missing tenant filter leaking shared table records. | Query API with search terms matching another tenant’s explicit entities. | Response contains only records explicitly tied to the requester’s `tenant_id`. |
| **19** | Step-Up Auth on Sensitive Operations | Attacker with read-level session executes financial wire transfer. | Submit `POST /v1/transfers` using session token lacking MFA verification step. | Server yields `403 Forbidden` with header `WWW-Authenticate: StepUp factor="mfa"`. |
| **20** | Nested Object Resource ID Injection | Tampering with sub-resource IDs: `/organizations/1/departments/5/employees/99`. | Swap IDs across boundaries: Request Org 1 with Department 8 (owned by Org 2). | API verifies ownership across the entire hierarchy; returns `404 Not Found`. |
| **21** | HTTP Verb Tampering / Bypass | Endpoint checks permissions for `POST`, but allows unauthorized `PUT` or `PATCH`. | Change method: `curl -X PUT https://api.domain.com/v1/account/role -d '{"role":"admin"}'` | Permission checks applied consistently across all verbs; returns `405 Method Not Allowed` or `403`. |
| **22** | Mass Assignment of Privileged Attributes | Attacker injects `"role": "admin"` or `"is_verified": true` in registration payload. | `curl -X POST /v1/users -d '{"name":"attacker","role":"admin","credits":99999}'` | DB stores only explicit schema-permitted fields (`name`); privileged keys discarded. |
| **23** | Path Traversal via API Routing | Accessing internal microservices through gateway route misconfigurations. | Request `https://api.domain.com/v1/documents/..%2f..%2fadmin%2fconfig` | Gateway normalizes path before routing; returns `400 Bad Request` or `404`. |
| **24** | Cross-Tenant Pagination Leakage | Next-page cursors crafted to disclose records from adjacent tenants. | Modify base64 cursor string to inject secondary tenant offsets. | Cursor decryption validates tenant context; returns `400 Bad Request` on mismatch. |
| **25** | Unenforced Scope Restrictions | Token with `read:profile` scope successfully requests `write:billing`. | `curl -X POST -H "Authorization: Bearer <READ_TOKEN>" https://api.domain.com/v1/billing` | Endpoint validates OAuth scopes; returns `403 Forbidden` (`insufficient_scope`). |
| **26** | Bulk Import/Export Authorization Boundaries | Export endpoints fail to isolate jobs, allowing downloads of others' dumps. | `curl -H "Authorization: Bearer <TOKEN_A>" /v1/exports/<JOB_ID_OF_TENANT_B>` | Verification confirms export ownership; returns `404 Not Found`. |
| **27** | Webhook Subscription Takeover | User registers endpoint receiving webhook events meant for another tenant. | Subscribe to event `order.created` with an external URL; trigger order in foreign tenant. | System verifies subscription ownership and payload tenant identifier matches subscriber. |
| **28** | GraphQL Query Traversal / Authorization | Unauthorized field access by requesting nested internal schema elements. | Query: `{ user { id private_financial_records { balance } } }` with standard token. | Field-level authorization intercepts the query; returns `null` with a `403` field error. |
| **29** | Inverted State Transition Injection | Moving an order from "Delivered" back to "Created" to re-process payments. | `curl -X PATCH /v1/orders/123/status -d '{"status":"PENDING"}'` | State machine rejects illegal transitions with `422 Unprocessable Entity`. |
| **30** | Context Downgrade via Impersonation Tokens | Support impersonation token retained to perform actions after session close. | Issue impersonation session, revoke via admin dashboard, re-execute payload. | Gateway evaluates real-time token blocklist in Redis; request immediately denied (`401`). |

### Category C: Input Validation, Schema Enforcement & Injection (Items 31–42)

| ID | Security Verification Check | Attack Vector / Exploit Scenario | Verification Method / CLI Command | Pass Criteria |
|---|---|---|---|---|
| **31** | Strict JSON Schema Validation | Malformed types causing unhandled runtime exceptions (e.g., Array instead of String). | Send `{"user_id": ["nested", "array"]}` to endpoint expecting scalar string. | Request fails at gateway/model binding layer with `400 Bad Request` and structured validation error. |
| **32** | SQL / NoSQL Injection | Escape characters in search endpoints altering database logic. | Inject `' OR 1=1 --` or `{"$gt": ""}` into query and body parameters. | Zero query manipulation; parameterized queries/ORMs handle payload as literal value. |
| **33** | Command Injection via System Utilities | Filename parameter passed into image processing wrapper (e.g., ImageMagick). | Send `filename: "image.png; cat /etc/passwd"`. | Input rejected via regex; system executes exclusively via array-based `execFile` without shell interpolation. |
| **34** | SSRF (Server-Side Request Forgery) | Webhook setup pointing to cloud metadata: `http://169.254.169.254/latest/meta-data/`. | Provide AWS metadata IP and private subnets (`10.0.0.0/8`, `127.0.0.1`) as webhook target. | IP resolver detects private/link-local addresses; connection rejected prior to socket creation. |
| **35** | XML External Entity (XXE) Injection | Uploading XML documents containing external entity declarations. | Submit payload: `<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>`. | XML parser configured with `external-general-entities=false` and `disallow-doctype-decl=true`. |
| **36** | Regular Expression Denial of Service (ReDoS) | Exponential back-tracking payloads targeting unstructured email/regex filters. | Send string: `"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa!"` to vulnerable validation route. | Parser executes in constant or polynomial time (<50ms) or terminates via timeout. |
| **37** | Payload Size Limit Enforcement | Memory exhaustion via multi-gigabyte HTTP POST bodies. | `curl -X POST https://api.domain.com/v1/upload -d @/dev/urandom` (chunked transfer). | Reverse proxy halts payload processing at predefined limit (e.g., `10MB`); returns `413 Payload Too Large`. |
| **38** | Content-Type Spoofing | Attacker sends JSON payload with `Content-Type: text/plain` to bypass CORS/WAF. | Send POST request without `application/json` header containing raw JSON body. | Endpoint enforces strict header checks; returns `415 Unsupported Media Type`. |
| **39** | HTTP Parameter Pollution (HPP) | Supplying identical query parameters twice: `?user_id=1&user_id=2`. | Execute query with duplicate keys; observe backend framework array binding. | Gateway rejects or deterministically handles parameters; avoids privilege assignment bypass. |
| **40** | Unicode Normalization Attacks | Bypassing blacklists using homoglyphs or multi-byte unicode sequences. | Send visual equivalents (e.g., Cyrillic 'a') inside critical identifier fields. | System normalizes input via Unicode Normalization Form C (NFC) prior to validation. |
| **41** | CSV/Formula Injection via API Exports | Exporting data containing `=cmd|' /C calc'!A0` executing code on victim Excel instances. | Inject spreadsheet operators into name fields: `+SUM(1+1)`. | Export sanitization prepends an apostrophe `'` to any cell starting with `=`, `+`, `-`, or `@`. |
| **42** | Zip Slip / Unsafe Archive Decompression | Archive upload with relative path directory traversal (`../../bin/sh`). | Upload zip file generated with `evilarc` containing traversal file paths. | Decompressor validates target extraction path resides strictly within the destination directory. |

### Category D: Rate Limiting, Throttling & DoS Protection (Items 43–52)

| ID | Security Verification Check | Attack Vector / Exploit Scenario | Verification Method / CLI Command | Pass Criteria |
|---|---|---|---|---|
| **43** | Distributed Rate Limiting Consistency | Bypassing single-node rate limits by rotating requests across cluster nodes. | Dispatch 200 requests across all load balancer nodes using concurrent workers. | Global rate limiter backed by Redis returns `429 Too Many Requests` once ceiling is reached. |
| **44** | Tier-Based Identity Limiting | Unauthenticated callers consuming compute budgets allocated for paid tiers. | Test with: 1) No token, 2) Free tier token, 3) Tier-1 Enterprise token. | Limits enforced: Anonymous (20 req/min), Free (100 req/min), Enterprise (5000 req/min). |
| **45** | Tier-1 DoS on Expensive Relational Joins | Requesting high pagination limits on relational child tables: `?limit=100000`. | Request `/v1/transactions?limit=1000000&include=audit_logs`. | Server enforces hard maximum limit (e.g., `limit=100`); invalidates excessive values. |
| **46** | GraphQL Depth & Complexity Limiting | Denial of service via deeply nested circular schema requests. | Query depth > 10: `{ author { books { author { books { ... } } } } }`. | Query analyzer rejects graph before execution if complexity/depth threshold is exceeded. |
| **47** | Rate Limit Bypass via Header Spoofing | Spoofing client IPs via `X-Forwarded-For: 1.1.1.1` to reset per-IP quotas. | Send sequential requests mutating `X-Forwarded-For` with random public IPs. | Gateway strips and overwrites `X-Forwarded-For` from untrusted downstreams; uses true socket IP. |
| **48** | Slowloris / HTTP Request Smuggling | Holding connection sockets open indefinitely via slow partial headers/bodies. | Execute `slowhttptest -c 1000 -H -g -o slowhttp -i 10 -r 200 -t GET -u https://api.domain.com`. | Edge/Proxy closes idle connections exceeding timeout thresholds (e.g., 5-10s); maintains availability. |
| **49** | Out-of-Band Callback Flooding | Initiating thousands of webhook verifications against an external target. | Register 1,000 webhook subscriptions in 10 seconds pointing to a victim domain. | Webhook registration enforces independent rate limits and domain verification checks. |
| **50** | CPU Exhaustion via Asymmetric Crypto Operations | Flooding endpoints with invalid SSL renegotiations or malformed large RSA signatures. | Send rapid burst of malformed JWT signatures forcing expensive RSA verification. | Gateway rejects malformed envelopes cheaply; throttles failing IPs aggressively. |
| **51** | Response Buffering Memory Exhaustion | Forcing server to buffer huge payloads by advertising an ultra-low TCP window. | Connect with tiny TCP window size while requesting large response payloads. | Streaming responses pipe directly without unbounded server-side memory buffering. |
| **52** | Circuit Breaking under Upstream Failure | Upstream service degradation cascades, exhausting the entire API thread pool. | Inject 5000ms latency into internal microservice dependency. | Circuit breaker trips after error threshold; returns immediate `503 Service Unavailable` with fallback. |

### Category E: Cryptography, Secrets & TLS Configuration (Items 53–60)

| ID | Security Verification Check | Attack Vector / Exploit Scenario | Verification Method / CLI Command | Pass Criteria |
|---|---|---|---|---|
| **53** | TLS Protocol Version Enforcement | Downgrade attacks exposing session data (POODLE, BEAST). | `testssl.sh -p https://api.domain.com` | TLS 1.2 and TLS 1.3 supported exclusively; SSLv2, SSLv3, TLS 1.0, and TLS 1.1 disabled. |
| **54** | Weak Cipher Suite Deprecation | Eavesdropping via broken ciphers containing CBC or RC4. | `testssl.sh -E https://api.domain.com` | Only AEAD ciphers permitted (e.g., `ECDHE-ECDSA-AES128-GCM-SHA256`, `CHACHA20-POLY1305`). |
| **55** | HSTS Header Deployment | SSL stripping attacks intercepting the initial plaintext connection. | `curl -I https://api.domain.com` | Returns `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload`. |
| **56** | Zero Hardcoded Secrets in Codebases | Leaked API credentials and database passwords in source code history. | `trufflehog git file://. --since-commit HEAD~500` | Zero high-entropy strings, private keys, or known token structures identified. |
| **57** | Symmetric Key Encryption-at-Rest for Sensitive Fields | Direct database compromise revealing raw PII or client secrets. | Inspect direct database dump / raw rows in `users` and `credentials` tables. | Sensitive fields encrypted via AES-256-GCM or ChaCha20; ciphertexts include distinct nonces. |
| **58** | Safe Cryptographic Salt & Work Factor | Offline rainbow table attacks against dumped user password hashes. | Inspect hashing algorithm configuration in source code. | Passwords hashed using Argon2id (`m=65536, t=3, p=4`) or bcrypt (work factor >= 12). |
| **59** | Perfect Forward Secrecy (PFS) Enforcement | Compromise of server private key decrypts past recorded traffic. | Inspect TLS cipher negotiation list with `testssl.sh -f`. | All negotiated cipher suites utilize ephemeral Diffie-Hellman keys (`ECDHE` / `DHE`). |
| **60** | Ephemeral Token Signature Key Rotation | Stolen private signing key permanently compromises token integrity. | Query `/.well-known/jwks.json`; check key rotation automation. | JWKS endpoint lists multiple active `kid` records supporting scheduled, seamless rotation. |

### Category F: Logging, Observability & Error Handling (Items 61–65)

| ID | Security Verification Check | Attack Vector / Exploit Scenario | Verification Method / CLI Command | Pass Criteria |
|---|---|---|---|---|
| **61** | Zero Token / Password Leakage in Logs | Tokens harvested by operators or third-party log analytical pipelines. | Execute request with credentials; search Elasticsearch/CloudWatch logs for the token. | Zero authorization headers, refresh tokens, passwords, or credit card numbers in logs. |
| **62** | Production Stack Trace Suppression | Stack traces reveal internal directory structures, library versions, and credentials. | Submit broken JSON payload (`{"key":`) to trigger an internal error. | Returns standard RFC 7807 problem detail response; zero debug traces or internal code lines exposed. |
| **63** | W3C Trace Context Propagation | Inability to trace attacks traversing distributed microservices. | Send request with `traceparent` header; check downstream service logs. | Upstream spans correlate accurately across all downstream internal RPCs and trace events. |
| **64** | Security Audit Trail Immutability | Attacker deletes audit records to cover unauthorized access. | Attempt to update or delete records directly in the audit log collection/table. | Audit collection has append-only permissions enforced by IAM; updates/deletions fail at the database level. |
| **65** | Centralized Security Alerting Integration | High-volume auth failures go unnoticed until system-wide compromise occurs. | Trigger 100 failed auth calls; check SIEM alert feed (Datadog/Splunk/Wazuh). | Alert fires within 120 seconds of threshold breach; triggers PagerDuty security incident. |

---

## 2. Production-Grade CI/CD Security Automation Pipeline

Save this file directly to `.github/workflows/api-security-pipeline.yml`. It runs on every pull request and push to the `main` branch, scanning dependencies, static code analysis, and dynamic API contracts.

```yaml
name: Production API Security & Vulnerability Gate

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read
  security-events: write

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  semgrep-sast:
    name: Semgrep SAST & Custom Auth Rules
    runs-on: ubuntu-latest
    container:
      image: returntocorp/semgrep:1.68.0
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Run Semgrep SAST & Custom Rules
        run: |
          semgrep scan \
            --config "p/security-audit" \
            --config "p/owasp-top-ten" \
            --config ".github/semgrep/rules.yml" \
            --sarif \
            --output semgrep-results.sarif \
            --error

      - name: Upload Semgrep SARIF Report
        uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: semgrep-results.sarif

  trivy-sca-and-fs:
    name: Trivy Dependency & Secrets Scan
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Run Trivy Vulnerability Scanner
        uses: aquasecurity/trivy-action@0.18.0
        with:
          scan-type: 'fs'
          scan-ref: '.'
          format: 'sarif'
          output: 'trivy-results.sarif'
          severity: 'CRITICAL,HIGH'
          exit-code: '1'
          ignore-unfixed: true

      - name: Upload Trivy SARIF Report
        uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: trivy-results.sarif

  dast-schemathesis:
    name: Schemathesis Dynamic API Contract Fuzzing
    runs-on: ubuntu-latest
    needs: [semgrep-sast, trivy-sca-and-fs]
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install Dependencies
        run: |
          python -m pip install --upgrade pip
          pip install schemathesis

      - name: Build and Boot Local API Service
        run: |
          docker compose -f docker-compose.test.yml up -d --build
          # Wait for API readiness
          timeout 60s bash -c 'until curl -s http://localhost:8080/health; do sleep 2; done'

      - name: Run Schemathesis Dynamic Attack Suite
        run: |
          schemathesis run http://localhost:8080/openapi.json \
            --base-url=http://localhost:8080 \
            --checks all \
            --hypothesis-max-examples=100 \
            --hypothesis-deadline=1000 \
            --validate-schema=true \
            --stateful=links \
            --exitfirst

      - name: Teardown Services
        if: always()
        run: docker compose -f docker-compose.test.yml down -v
```

---

## 3. Custom Semgrep Rule Pack for Auth & API Vulnerabilities

Place this configuration file at `.github/semgrep/rules.yml`. It defines custom rules that target authorization bypasses, cryptographic misconfigurations, and BOLA patterns during CI/CD checks.

```yaml
rules:
  - id: express-route-missing-auth-guard
    languages: [javascript, typescript]
    severity: ERROR
    message: >-
      Exposed API route detected without an explicit authentication middleware.
      Ensure `requireAuth` or an equivalent middleware is present in the pipeline.
    patterns:
      - pattern-either:
          - pattern: app.$METHOD($ROUTE, (req, res) => { ... })
          - pattern: router.$METHOD($ROUTE, (req, res) => { ... })
      - metavariable-regex:
          metavariable: $METHOD
          regex: ^(get|post|put|delete|patch)$
      - pattern-not: app.$METHOD($ROUTE, $AUTH, ..., (req, res) => { ... })
      - pattern-not: router.$METHOD($ROUTE, $AUTH, ..., (req, res) => { ... })
      - pattern-not: app.use($AUTH)
      - pattern-not: router.use($AUTH)

  - id: insecure-jwt-none-algorithm
    languages: [javascript, typescript, python, go]
    severity: ERROR
    message: >-
      Insecure JWT verification: explicitly permitting the 'none' algorithm
      allows signature stripping attacks. Set algorithms explicitly to RS256, ES256, or EdDSA.
    pattern-either:
      - pattern: jwt.verify($TOKEN, $KEY, { algorithms: [..., "none", ...] })
      - pattern: jwt.verify($TOKEN, $KEY, { algorithms: [..., "NONE", ...] })
      - pattern: jwt.decode($TOKEN, verify=False)
      - pattern: jwt.Decode($TOKEN)

  - id: bola-direct-object-id-lookup
    languages: [javascript, typescript]
    severity: WARNING
    message: >-
      Potential BOLA/IDOR vulnerability: Database lookup uses route parameter directly
      without incorporating user/tenant context in the WHERE clause.
    patterns:
      - pattern-either:
          - pattern: |
              const $ID = req.params.id;
              ...
              $DB.findUnique({ where: { id: $ID } });
          - pattern: |
              $DB.findOne({ _id: req.params.id });
      - pattern-not: |
          $DB.findUnique({ where: { id: req.params.id, userId: req.user.id } });
      - pattern-not: |
          $DB.findUnique({ where: { id: req.params.id, tenantId: req.user.tenantId } });

  - id: hardcoded-jwt-signing-secret
    languages: [javascript, typescript, python, go]
    severity: ERROR
    message: >-
      High-risk security vulnerability: Hardcoded string literal used as JWT signing secret.
      Secrets must be loaded from external key stores (AWS KMS, HashiCorp Vault) or environment variables.
    pattern-either:
      - pattern: jwt.sign($PAYLOAD, "...", ...)
      - pattern: jwt.verify($TOKEN, "...", ...)
      - pattern: jwt.encode($PAYLOAD, "...", ...)
      - pattern: jwt.decode($TOKEN, "...", ...)
      - pattern: "[]byte(\"...\")"
    paths:
