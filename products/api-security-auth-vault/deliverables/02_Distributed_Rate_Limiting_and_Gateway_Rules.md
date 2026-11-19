# Module 2: Distributed Rate Limiting, DDoS & Bot Defense Blueprints

Distributed rate limiting and volumetric defense systems protect stateful backends from cascading failure, credential stuffing, scraping, and application-layer (L7) denial of service. This module provides battle-tested architectures, atomic Redis Lua scripts, edge gateway rules (Envoy, NGINX, Cloudflare Workers), and anomaly detection heuristics designed to handle multi-gigabit traffic spikes while maintaining sub-millisecond evaluation latency.

---

## 1. Algorithm Selection & Topologies

Selecting the wrong rate-limiting algorithm causes memory exhaustion in cache clusters or lets traffic bursts bypass controls.

### 1.1 Comparative Engineering Matrix

| Algorithm | Redis Memory per Client Key | Accuracy Under Jitter | Burst Handling Capability | Redis Computational Complexity | Recommended Target Use Case |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Fixed Window** | ~64 bytes (String counter + TTL) | Low (2x burst at boundary) | Poor (traffic spikes at reset) | $O(1)$ (`INCR`, `EXPIRE`) | Basic internal microservice throttling |
| **Token Bucket** | ~128 bytes (Hash: tokens + timestamp) | High | Excellent (allows configured burst) | $O(1)$ (Math calculations in Lua) | Public API tiers, metered developer endpoints |
| **Leaky Bucket** | ~128 bytes (Hash: water level + timestamp) | High | None (smooths traffic to fixed rate) | $O(1)$ (Math calculations in Lua) | Data ingestion pipelines, webhook delivery queues |
| **Sliding Window Log** | Variable ($O(N)$ entries, ~40 bytes/request) | Absolute (100% precision) | Absolute enforcement | $O(\log N + M)$ (`ZREMRANGE`, `ZCARD`) | Zero-tolerance endpoints: `/auth/login`, `/billing/charge` |
| **Sliding Window Counter** | ~160 bytes (Hash: current/previous buckets) | Approximation (~99.5% accuracy) | Very Good (smoothed approximation) | $O(1)$ (Weighted sum in Lua) | High-volume public edge APIs ($>100\text{k RPS}$) |

### 1.2 Defense-in-Depth Tiered Architecture

Rate limiting must not be centralized into a single bottleneck. Implement defenses in a four-tier architecture:

```
[ Ingress Internet ]
        │
        ▼
[ Tier 1: Cloudflare Edge / Anycast WAF ]
  - Layer 3/4 SYN/UDP Flood Absorption
  - JA3/JA4 Fingerprint Dropping
  - ASN/Country/IP Reputation Filtering
  - Coarse Volumetric Limiting (Static Thresholds)
        │
        ▼
[ Tier 2: Edge Reverse Proxy (NGINX / Envoy Gateway) ]
  - TLS Termination & HTTP/2/3 Decompression
  - Local In-Memory Rate Limiting (Token Bucket per Worker)
  - Uniform Resource Identifier (URI) Normalization & Route Classification
        │
        ▼
[ Tier 3: Distributed Rate Limiting Cluster (Redis + Lua Engine) ]
  - Global Cross-Region Identity Tracking (Tenant ID, User ID, API Key)
  - Sliding Window Log & Token Bucket Execution
  - Dynamic Sliding Penalties (Exponential Backoff Tracking)
        │
        ▼
[ Tier 4: Application Core Services ]
  - Concurrency Limiting (Sempahores/Connection Pools)
  - Database Circuit Breakers
```

---

## 2. Production-Grade Redis Lua Scripts

Atomic execution inside Redis is mandatory to prevent race conditions during distributed reads, updates, and writes. Non-atomic implementations (e.g., separate `GET` then `INCR`) allow concurrency windows where thousands of requests bypass quotas.

### 2.1 High-Precision Sliding Window Log (ZSET Engine)

This script maintains a sorted set of microsecond timestamps. It guarantees zero boundary bursts at the cost of memory per request.

**File: `sliding_window_log.lua`**
```lua
-- KEYS[1]: Rate limit tracking key (e.g., ratelimit:sliding:usr_10928301)
-- ARGV[1]: Current UNIX timestamp in milliseconds (with microsecond fraction if available)
-- ARGV[2]: Window size in milliseconds (e.g., 60000 for 1 minute)
-- ARGV[3]: Maximum allowed requests within window
-- ARGV[4]: Unique Request ID (prevents collision if timestamps match)

local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local request_id = ARGV[4]

local clear_before = now - window

-- 1. Evict entries outside the sliding window
redis.call('ZREMRANGEBYSCORE', key, '-inf', clear_before)

-- 2. Fetch current number of requests inside window
local current_requests = redis.call('ZCARD', key)

-- 3. Check if current count exceeds maximum allowed limit
if current_requests < limit then
    -- Record this request with score as timestamp and member as timestamp:request_id
    local member = now .. ":" .. request_id
    redis.call('ZADD', key, now, member)
    -- Set TTL to ensure key expires if client goes dormant
    redis.call('PEXPIRE', key, window)
    
    -- Return: 1 = Allowed, Current Count, Remaining Tokens, Reset Time (ms)
    return {1, current_requests + 1, limit - (current_requests + 1), math.ceil(window / 1000)}
else
    -- Fetch the oldest entry still inside window to calculate exact retry delay
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = 0
    if oldest[2] then
        retry_after = math.ceil((tonumber(oldest[2]) + window - now) / 1000)
        if retry_after < 1 then retry_after = 1 end
    end
    
    -- Return: 0 = Rejected, Current Count, Remaining Tokens, Retry-After (seconds)
    return {0, current_requests, 0, retry_after}
end
```

### 2.2 Memory-Optimized Sliding Window Counter

This script avoids storing every request ID. It approximates the sliding window using a weighted sum of the current and previous discrete sub-windows, keeping memory fixed at ~160 bytes per identifier.

**File: `sliding_window_counter.lua`**
```lua
-- KEYS[1]: Base key for the counter (e.g., ratelimit:swc:api_prod_9918)
-- ARGV[1]: Current UNIX timestamp in seconds
-- ARGV[2]: Window size in seconds (e.g., 60)
-- ARGV[3]: Maximum allowed requests within window

local base_key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])

-- Determine current bucket and previous bucket IDs
local current_bucket = math.floor(now / window)
local previous_bucket = current_bucket - 1

local current_key = base_key .. ":" .. current_bucket
local previous_key = base_key .. ":" .. previous_bucket

-- Fetch counts from current and previous buckets
local current_count = tonumber(redis.call('GET', current_key) or "0")
local previous_count = tonumber(redis.call('GET', previous_key) or "0")

-- Calculate the position within the current window (0.0 to 1.0)
local time_into_current_bucket = now % window
local weight = (window - time_into_current_bucket) / window
local estimated_count = math.floor(previous_count * weight + current_count)

if estimated_count < limit then
    -- Atomically increment current bucket
    redis.call('INCR', current_key)
    -- Ensure expiration covers the lifecycle of two full windows
    redis.call('EXPIRE', current_key, window * 2)
    
    local remaining = limit - (estimated_count + 1)
    return {1, estimated_count + 1, remaining, window - time_into_current_bucket}
else
    local retry_after = window - time_into_current_bucket
    if retry_after < 1 then retry_after = 1 end
    return {0, estimated_count, 0, retry_after}
end
```

### 2.3 Token Bucket with Burst Capacity Handling

This script implements continuous rate refill with burst allowances. It is ideal for metered APIs where sustained volume must conform to an SLA, but low-latency bursts are allowed.

**File: `token_bucket.lua`**
```lua
-- KEYS[1]: Bucket key (e.g., ratelimit:tb:tenant_org_44a)
-- ARGV[1]: Max bucket capacity (burst limit)
-- ARGV[2]: Refill rate in tokens per millisecond
-- ARGV[3]: Current UNIX timestamp in milliseconds
-- ARGV[4]: Cost in tokens for the incoming request (typically 1)

local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

-- Retrieve current state [1: tokens, 2: last_refill_timestamp]
local data = redis.call('HMGET', key, 'tokens', 'last_updated')

local tokens
local last_updated

if not data[1] then
    -- Cold start: Bucket starts full
    tokens = capacity
    last_updated = now
else
    tokens = tonumber(data[1])
    last_updated = tonumber(data[2])
end

-- Calculate generated tokens since last evaluation
local elapsed = now - last_updated
if elapsed > 0 then
    local generated = elapsed * refill_rate
    tokens = math.min(capacity, tokens + generated)
    last_updated = now
end

-- Evaluate allowance
if tokens >= requested then
    tokens = tokens - requested
    redis.call('HMSET', key, 'tokens', tokens, 'last_updated', last_updated)
    -- Keep key alive for time required to refill from 0 to capacity
    local ttl_ms = math.ceil(capacity / refill_rate)
    redis.call('PEXPIRE', key, ttl_ms)
    
    return {1, math.floor(tokens), 0}
else
    -- Reject request and compute backoff duration until requested tokens become available
    local missing_tokens = requested - tokens
    local retry_after_ms = math.ceil(missing_tokens / refill_rate)
    local retry_after_seconds = math.ceil(retry_after_ms / 1000)
    if retry_after_seconds < 1 then retry_after_seconds = 1 end
    
    return {0, math.floor(tokens), retry_after_seconds}
end
```

---

## 3. Gateway Implementations

### 3.1 Envoy Proxy Distributed Rate Limit Filter

Envoy decouples enforcement from state by calling an out-of-process gRPC rate limit service (`ratelimit`).

#### Envoy Filter Configuration Snippet (v3 API)

```yaml
http_filters:
  - name: envoy.filters.http.ratelimit
    typed_config:
      "@type": type.googleapis.com/envoy.extensions.filters.http.ratelimit.v3.RateLimit
      domain: internal-api-gateway
      stage: 0
      request_type: external
      timeout: 20ms
      failure_mode_deny: false
      rate_limited_as_resource_exhausted: true
      enable_x_ratelimit_headers: DRAFT_VERSION_03
      rate_limit_service:
        transport_api_version: V3
        grpc_service:
          envoy_grpc:
            cluster_name: ratelimit_service_cluster

clusters:
  - name: ratelimit_service_cluster
    type: STRICT_DNS
    lb_policy: ROUND_ROBIN
    http2_protocol_options: {}
    connect_timeout: 0.25s
    load_assignment:
      cluster_name: ratelimit_service_cluster
      endpoints:
        - lb_endpoints:
            - endpoint:
                address:
                  socket_address:
                    address: ratelimit.infrastructure.internal
                    port_value: 8081
```

#### Envoy Route Descriptors

Configure which requests trigger rate checks inside the route configuration:

```yaml
route_config:
  name: api_routes
  virtual_hosts:
    - name: api_service
      domains: ["api.production.domain.com"]
      routes:
        - match:
            prefix: "/v1/auth/"
          route:
            cluster: auth_backend
            rate_limits:
              - stage: 0
                actions:
                  - request_headers:
                      header_name: ":path"
                      descriptor_key: route_path
                  - remote_address: {}
        - match:
            prefix: "/v1/"
          route:
            cluster: api_backend
            rate_limits:
              - stage: 0
                actions:
                  - request_headers:
                      header_name: "X-Tenant-ID"
                      descriptor_key: tenant_id
```

#### Ratelimit Service Runtime Rules (`config.yaml`)

```yaml
domain: internal-api-gateway
descriptors:
  # Route 1: Auth path strict IP rate limiting
  - key: route_path
    value: /v1/auth/
    descriptors:
      - key: remote_address
        rate_limit:
          unit: minute
          requests_per_unit: 10

  # Route 2: Tenant-level tiered rate limits
  - key: tenant_id
    descriptors:
      - key: tier_free
        rate_limit:
          unit: hour
          requests_per_unit: 1000
      - key: tier_enterprise
        rate_limit:
          unit: second
          requests_per_unit: 500
```

### 3.2 NGINX High-Throughput Dual-Zone Configuration

This configuration uses a two-zone approach: a fast in-memory connection/burst smoother on the edge, combined with an authenticated identity limiter.

```nginx
http {
    # Extract Real IP when behind an L4/L7 load balancer or Cloudflare
    set_real_ip_from 10.0.0.0/8;
    set_real_ip_from 172.16.0.0/12;
    set_real_ip_from 192.168.0.0/16;
    real_ip_header X-Forwarded-For;
    real_ip_recursive on;

    # Exemption Map for internal health probes and monitoring agents
    map $http_x_internal_token $limit_bypass {
        "SecretTelemetryProbeTokenString4490" 0;
        default 1;
    }

    # Binary IP Mapping for Memory Efficiency (10MB handles ~160,000 active sessions)
    map $limit_bypass $limitable_ip {
        0 "";
        1 $binary_remote_addr;
    }

    # Extract authenticated Tenant/Key or fall back to client IP
    map $http_authorization $client_identity {
        "" $limitable_ip;
        default $http_authorization;
    }

    # Global IP Concurrency Limit (Prevents socket starvation attacks)
    limit_conn_zone $limitable_ip zone=ip_conn_pool:10m;

    # API Request Rate Limits
    # Zone 1: Strict Per-IP Zone for unauthenticated/auth endpoints (5 RPS baseline)
    limit_req_zone $limitable_ip zone=strict_auth_zone:20m rate=5r/s;

    # Zone 2: Per-Identity Public API Zone (100 RPS baseline)
    limit_req_zone $client_identity zone=standard_api_zone:50m rate=100r/s;

    # RFC 6585 compliance status code
    limit_req_status 429;
    limit_conn_status 429;

    server {
        listen 443 ssl http2;
        server_name api.production.domain.com;

        # TLS parameters omitted for brevity

        # Max 50 concurrent open TCP connections per single IP
        limit_conn ip_conn_pool 50;

        # Endpoint 1: Auth/Password attempts - zero tolerance burst
        location ~ ^/v[0-9]+/auth/ {
            limit_req zone=strict_auth_zone burst=5 nodelay;
            
            proxy_pass http://upstream_auth_backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        # Endpoint 2: Standard platform API - allows dynamic 50-request burst
        location / {
            limit_req zone=standard_api_zone burst=50 nodelay;

            # Custom rate limit exhaustion headers
            add_header X-RateLimit-Limit 100 always;
            add_header Retry-After 1 always;

            proxy_pass http://upstream_core_backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }
    }
}
```

### 3.3 Kong Gateway Declarative Configuration (`kong.yml`)

This configuration enforces a Redis-backed multi-tier limit across multiple consumer groups.

```yaml
_format_version: "3.0"

services:
  - name: enterprise-core-api
    url: http://core-api-internal.internal:8080
    routes:
      - name: core-api-route
        paths:
          - /v2/data

consumers:
  - username: client_tier_free
    custom_id: free_consumer_001
  - username: client_tier_enterprise
    custom_id: enterprise_consumer_002

plugins:
  - name: rate-limiting-advanced
    service: enterprise-core-api
    config:
      limit:
        - 100
        - 50000
      window_size:
        - 60
        - 86400
      identifier: consumer
      strategy: redis
      redis:
        host: redis-sentinel.internal
        port: 26379
        sentinel_master: mymaster
        sentinel_role: master
        timeout: 2000
        database: 2
        ssl: true
      sync_rate: 100
      namespace: kong_rate_limits
      hide_client_headers: false
      error_code: 429
      error_message: "API rate limit exceeded. Check X-RateLimit-Remaining-Minute."
```

---

## 4. Cloudflare Worker WAF & Edge Defense Script

This standalone Cloudflare Worker (JavaScript/ES module) inspects edge metadata before traffic touches origin infrastructure. It checks the JA4 TLS fingerprint, evaluates Cloudflare threat intelligence, and runs an atomic Sliding Window log against Upstash/Global Redis over HTTPS.

**File: `edge-waf-ratelimiter.js`**
```javascript
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // 1. Bypass static resources to prevent unnecessary Redis calls
    if (url.pathname.match(/\.(css|js|woff2|png|jpg|ico|svg)$/)) {
      return fetch(request);
    }

    // 2. Extract edge client telemetry
    const clientIp = request.headers.get("cf-connecting-ip") || "unknown-ip";
    const cf = request.cf || {};
    const ja4 = cf.ja4 || "unknown-ja4";
    const threatScore = cf.threatScore || 0; // 0 = Clean, 100 = Malicious
    const botScore = cf.botManagement?.score || 100; // 1 = Verified Automated, 99 = Human

    // 3. Automated Heuristic Threat Dropping at the Edge
    if (threatScore > 50 || botScore < 10) {
      return new Response(JSON.stringify({
        type: "https://api.domain.com/errors/security-violation",
        title: "Forbidden Request",
        status: 403,
        detail: "Edge threat mitigation triggered based on security profile.",
        instance: url.pathname
      }), {
        status: 403,
        headers: { "Content-Type": "application/problem+json" }
      });
    }

    // 4. Determine rate limiting key
    // Prefer authenticated Authorization Bearer, fall back to IP + JA4 combo
    let limiterKey = `ratelimit:${clientIp}:${ja4}`;
    const authHeader = request.headers.get("authorization");
    if (authHeader && authHeader.startsWith("Bearer ")) {
      const token = authHeader.substring(7);
      // Fast hash identifier instead of sending full JWT over wire
      const tokenHash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token))
        .then(buf => Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('').substring(0, 16));
      limiterKey = `ratelimit:auth:${tokenHash}`;
    }

    // 5. Query Edge Redis (e.g., Upstash REST API)
    const redisEndpoint = env.UPSTASH_REDIS_REST_URL;
    const redisToken = env.UPSTASH_REDIS_REST_TOKEN;

    const windowSeconds = 60;
    const maxAllowed = 120; // 120 requests per minute
    const nowMs = Date.now();
    const requestId = crypto.randomUUID();

    // High precision sliding window via REST pipeline
    const pipelinePayload = [
      ["ZREMRANGEBYSCORE", limiterKey, "-inf", nowMs - (windowSeconds * 1000)],
      ["ZCARD", limiterKey],
      ["ZADD", limiterKey, nowMs, `${nowMs}:${requestId}`],
      ["EXPIRE", limiterKey, windowSeconds]
    ];

    try {
      const redisResponse = await fetch(`${redisEndpoint}/pipeline`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${redisToken}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(pipelinePayload)
      });

      if (!redisResponse.ok) {
        // FAIL-OPEN: Log error to edge analytics and proceed to avoid taking down origin
        console.error("RateLimit Redis failed:", await redisResponse.text());
        return fetch(request);
      }

      const results = await redisResponse.json();
      const currentUsage = results[1].result; // ZCARD output

      const remainingTokens = Math.max(0, maxAllowed - (currentUsage + 1));
      const isRateLimited = currentUsage >= maxAllowed;

      if (isRateLimited) {
        return new Response(JSON.stringify({
          type: "https://api.domain.com/errors/rate-limit-exceeded",
          title: "Too Many Requests",
          status: 429,
          detail: `Rate limit of ${maxAllowed} requests per ${windowSeconds}s reached.`,
          retry_after: windowSeconds
        }), {
          status: 429,
          headers: {
            "Content-Type": "application/problem+json",
            "Retry-After": String(windowSeconds),
            "RateLimit-Limit": String(maxAllowed),
            "RateLimit-Remaining": "0",
            "RateLimit-Reset": String(Math.ceil(nowMs / 1000) + windowSeconds)
          }
        });
      }

      // 6. Forward Request with Appended Context Headers
      const modifiedRequestHeaders = new Headers(request.headers);
      modifiedRequestHeaders.set("X-Edge-JA4", ja4);
      modifiedRequestHeaders.set("X-Edge-Client-IP", clientIp);

      const originResponse = await fetch(new Request(request, {
        headers: modifiedRequestHeaders
      }));

      // 7. Inject Standardized RFC Headers into Upstream Response
      const updatedResponseHeaders = new Headers(originResponse.headers);
      updatedResponseHeaders.set("RateLimit-Limit", String(maxAllowed));
      updatedResponseHeaders.set("RateLimit-Remaining", String(remainingTokens));
      updatedResponseHeaders.set("RateLimit-Reset", String(Math.ceil(nowMs / 1000) + windowSeconds));

      return new Response(originResponse.body, {
        status: originResponse.status,
        statusText: originResponse.statusText,
        headers: updatedResponseHeaders
      });

    } catch (err) {
      console.error("Edge rate limit exception (Failing open):", err);
      return fetch(request);
    }
  }
};
```

---

## 5. Anomaly Detection & Behavioral Defenses

Volumetric rate limits cannot stop low-and-slow brute force or distributed credential stuffing. If 5,000 distinct residential IP addresses each attempt 1 login per hour, typical IP-based limits never trigger.

### 5.1 Credential Stuffing & Distributed Anomaly Script

This Redis Lua script detects distributed credential stuffing targeting the same user ID or username across rotating IP pools.

**File: `detect_distributed_stuffing.lua`**
```lua
-- KEYS[1]: Target Resource Key (e.g., target:user:john_doe_99)
-- KEYS[2]: Global Security Alert Stream
-- ARGV[1]: Origin IP attempting the login
-- ARGV[2]: Current UNIX Timestamp
-- ARGV[3]: Maximum Unique IPs allowed per user window before trip
-- ARGV[4]: Window lifespan in seconds (e.g., 900 for 15 mins)

local target_key = KEYS[1]
local stream_alert_key = KEYS[2]
local current_ip = ARGV[1]
local now = tonumber(ARGV[2])
local max_unique_ips = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])

-- 1. Insert IP into a HyperLogLog (or Set) dedicated to this entity
redis.call('SADD', target_key, current_ip)
redis.call('EXPIRE', target_key, ttl)

-- 2. Count distinct IPs seen within the current lifecycle
local distinct_ip_count = redis.call('SCARD', target_key)

-- 3. Trigger alert and enforce defensive block if threshold is crossed
if distinct_ip_count > max_unique_ips then
    redis.call('XADD', stream_alert_key, '*',
        'event_type', 'CREDENTIAL_STUFFING_SUSPECTED',
        'target', target_key,
        'unique_ips', distinct_ip_count,
        'latest_ip', current_ip,
        'timestamp', now
    )
    -- Return: 0 = Attack Detected, Block Request / Require CAPTCHA
    return {0, distinct_ip_count}
end

-- Return: 1 = Clean
return {1, distinct_ip_count}
```

### 5.2 Dynamic Exponential Backoff Engine (Penalty Box)

This component dynamically penalizes offenders by tracking their violation history and applying exponentially scaling blocks.

**File: `penalty_box.lua`**
```lua
-- KEYS[1]: Offender Tracking Key (e.g., penalty:offender:198.51.100.22)
-- KEYS[2]: Active Block Status Key
-- ARGV[1]: Current UNIX Timestamp
-- ARGV[2]: Base Penalty Duration in seconds (e.g., 300 = 5 mins)
-- ARGV[3]: Max Exponential Factor (e.g., 6 = 2^6 * base = 64 * 300 = 19200s)

local tracker_key = KEYS[1]
local block_key = KEYS[2]
local now = tonumber(ARGV[1])
local base_penalty = tonumber(ARGV[2])
local max_exponent = tonumber(ARGV[3])

-- 1. Check if user is currently blocked
local is_blocked = redis.call('GET', block_key)
if is_blocked then
    local remaining_ttl = redis.call('TTL', block_key)
    return {0, remaining_ttl} -- Reject, return remaining seconds
end

-- 2. Increment historical violation counter
local violations = redis.call('INCR', tracker_key)
if violations == 1 then
    -- Reset strike counter after 24 hours of clean behavior
    redis.call('EXPIRE', tracker_key, 86400)
end

-- 3. Calculate dynamic exponential backoff: base_penalty * 2^(violations - 1)
local exponent = math.min(violations - 1, max_exponent)
local block_duration = base_penalty * (2 ^ exponent)

-- 4. Set the lock key
redis.call('SET', block_key, "blocked", 'EX', block_duration)

return {1, block_duration}
```

---

## 6. Standardized Response Headers

When throttling traffic, use the modern standard format defined by the IETF `RateLimit-*` draft specification alongside RFC 6585.

### 6.1 Standard Headers Reference

| Header Name | Type | Example | Description |
| :--- | :--- | :--- | :--- |
| `Retry-After` | Integer | `30` | Number of seconds the client must wait before retrying (RFC 7231). |
| `RateLimit-Limit` | Integer | `100` | The maximum number of requests allowed in the current evaluation window. |
| `RateLimit-Remaining` | Integer | `0` | The
