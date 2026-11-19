# Module 1: Complete Authentication & Token Lifecycles

This deliverable provides the complete production architecture, data models, cryptographic validations, and deployment-ready code for modern API authentication. It focuses on OAuth 2.1 zero-trust flows, rotating refresh token families in Redis, cross-origin browser hardening, and instantaneous session revocation.

---

## 1. High-Level System Architecture

The following sequence details the zero-trust boundary separating Public Clients (SPA/Mobile), the Reverse Proxy/API Gateway, the Dedicated Authentication Service, Distributed Token Stores, and Downstream Resource Servers.

```
+---------------------------------------------------------------------------------------------------+
|                                      ZERO-TRUST AUTH BOUNDARY                                     |
+---------------------------------------------------------------------------------------------------+
 [ Public Client ]       [ API Gateway / Proxy ]     [ Auth Service ]    [ Redis Cluster ]  [ Resource Server ]
         |                          |                       |                   |                   |
         |-- 1. /authorize (PKCE) ->|---------------------->|                   |                   |
         |<- 2. Auth Code ----------|<----------------------|                   |                   |
         |                          |                       |                   |                   |
         |-- 3. /oauth/token ------>|---------------------->|                   |                   |
         |      (Code + Verifier)   |                       |-- 4. Store Family>|                   |
         |                          |                       |   State & JTI     |                   |
         |<- 5. Set __Host- Cookies-|<----------------------|                   |                   |
         |      (AT + RT Family)    |                       |                   |                   |
         |                          |                       |                   |                   |
         |-- 6. API Req + Cookie -->|                                                               |
         |                          |-- 7. Validate JWT Signature & Alg (stateless via JWKS) ------>|
         |                          |-- 8. Query Revocation Bloom / Redis Denylist (JTI) ---------->|
         |                          |-- 9. Strip Auth Cookie, Inject X-User-Id / Claims ----------->|
         |<- 10. HTTP 200 Response -|<--------------------------------------------------------------|
```

---

## 2. OAuth 2.0 / 2.1 Authorization Code Flow with PKCE

Public clients (Single Page Applications, Native Mobile, Desktop) MUST NOT use the Resource Owner Password Credentials Grant or the Implicit Grant. RFC 7636 (PKCE) is mandatory to eliminate authorization code interception attacks.

### 2.1 Cryptographic Verifier & Challenge Mechanics

The client generates a high-entropy cryptographic random string (`code_verifier`) using unreserved URL characters `[A-Z] / [a-z] / [0-9] / "-" / "." / "_" / "~"`, with a minimum length of 43 characters and a maximum of 128 characters.

$$\text{code\_challenge} = \text{BASE64URL-ENCODE}(\text{SHA256}(\text{ASCII}(\text{code\_verifier})))$$

#### Production Client Implementation (Web Crypto API / Node.js Runtime)

```typescript
// pkce.ts - Zero-dependency PKCE generation compatible with Browsers, Node 18+, and Edge Runtimes
export interface PKCEPair {
  codeVerifier: string;
  codeChallenge: string;
  codeChallengeMethod: 'S256';
}

function base64UrlEncode(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary)
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

export async function generatePKCE(): Promise<PKCEPair> {
  const randomBytes = new Uint8Array(64);
  crypto.getRandomValues(randomBytes);
  
  // RFC 7636 ABNF: unreserved characters
  const charset = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~';
  let verifier = '';
  for (let i = 0; i < randomBytes.length; i++) {
    verifier += charset[randomBytes[i] % charset.length];
  }

  const encoder = new TextEncoder();
  const data = encoder.encode(verifier);
  const digest = await crypto.subtle.digest('SHA-256', data);
  const challenge = base64UrlEncode(digest);

  return {
    codeVerifier: verifier,
    codeChallenge: challenge,
    codeChallengeMethod: 'S256',
  };
}
```

### 2.2 Wire-Level Payloads

#### Authorization Request
```http
GET /oauth/v2/authorize?
    response_type=code
    &client_id=spa-dashboard-prod
    &redirect_uri=https%3A%2F%2Fapp.platform.io%2Fauth%2Fcallback
    &scope=openid%20profile%20email%20offline_access%20billing%3Aread
    &state=af0ifjsldkj
    &code_challenge=E9Melhoa2OwvFrGMTJguCH5rtG6470-ZFlo_GZ0fqeM
    &code_challenge_method=S256 HTTP/1.1
Host: auth.platform.io
```

#### Token Exchange Request
```http
POST /oauth/v2/token HTTP/1.1
Host: auth.platform.io
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&client_id=spa-dashboard-prod
&code=SplxlOBeZQQYbYS6WxSbIA
&redirect_uri=https%3A%2F%2Fapp.platform.io%2Fauth%2Fcallback
&code_verifier=dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk
```

---

## 3. Production Token Rotation & Reuse Detection (Redis Engine)

The token rotation lifecycle prevents replay attacks by issuing a single-use refresh token that advances the state of a "Token Family." If a token from a family is presented more than once, the engine triggers an automatic compromise protocol, invalidating all current and descendant tokens across the entire family.

```
       [ Family Root (UUIDv4) ]
                  |
         [ RT-1 (Consumed) ]  <-- Attacker replays RT-1!
                  |
         [ RT-2 (Consumed) ]  <-- ENGINE DETECTS BREACH:
                  |               Revokes Family Root immediately.
         [ RT-3 (Active)   ]  <-- Invalidates RT-3. Legitimate user forced to re-auth.
```

### 3.1 Redis Data Structures

*   `token_family:<family_id>`: `HASH` containing family metadata, user ID, status (`ACTIVE` | `REVOKED`), and current active refresh token hash.
*   `refresh_token:<token_hash>`: `HASH` storing `family_id`, `iteration`, and state (`VALID` | `CONSUMED` | `REVOKED`).
*   `user_sessions:<user_id>`: `SET` of active `family_id` strings belonging to the subject.

### 3.2 Atomic Token Exchange Lua Script

Using a Redis Lua script prevents race conditions when concurrent requests attempt to swap the same refresh token.

```lua
-- KEYS[1]: refresh_token:<incoming_token_hash>
-- KEYS[2]: token_family:<family_id>
-- ARGV[1]: expected_family_id
-- ARGV[2]: new_token_hash
-- ARGV[3]: new_token_ttl (seconds)
-- ARGV[4]: client_ip
-- ARGV[5]: user_agent

local token_key = KEYS[1]
local family_key = KEYS[2]

local incoming_family = ARGV[1]
local new_token_hash = ARGV[2]
local token_ttl = tonumber(ARGV[3])
local client_ip = ARGV[4]
local user_agent = ARGV[5]

-- 1. Check if the incoming token exists
local token_data = redis.call('HMGET', token_key, 'family_id', 'status', 'iteration')
local family_id = token_data[1]
local status = token_data[2]
local iteration = tonumber(token_data[3])

if not family_id then
    return redis.error_reply("ERR_TOKEN_NOT_FOUND")
end

-- 2. Verify Family ID integrity
if family_id ~= incoming_family then
    return redis.error_reply("ERR_FAMILY_MISMATCH")
end

-- 3. REUSE DETECTION: If token is already CONSUMED or family is REVOKED
local family_status = redis.call('HGET', family_key, 'status')
if status == 'CONSUMED' or family_status == 'REVOKED' then
    -- Mark family as compromised
    redis.call('HSET', family_key, 'status', 'REVOKED', 'revoked_reason', 'REUSE_DETECTED')
    -- Expire family metadata quickly to allow garbage collection
    redis.call('EXPIRE', family_key, 86400)
    return redis.error_reply("ERR_TOKEN_REUSE_DETECTED")
end

-- 4. Mark incoming token as CONSUMED (keep for a short grace window or audit)
redis.call('HSET', token_key, 'status', 'CONSUMED', 'consumed_at', redis.call('TIME')[1])
redis.call('EXPIRE', token_key, 300) -- Retain for 5 mins to catch race conditions

-- 5. Register new token
local new_iteration = iteration + 1
local new_token_key = 'refresh_token:' .. new_token_hash

redis.call('HMSET', new_token_key,
    'family_id', family_id,
    'status', 'VALID',
    'iteration', new_iteration,
    'created_at', redis.call('TIME')[1],
    'ip', client_ip,
    'user_agent', user_agent
)
redis.call('EXPIRE', new_token_key, token_ttl)

-- 6. Update Family pointer
redis.call('HMSET', family_key,
    'active_token_hash', new_token_hash,
    'last_rotated_at', redis.call('TIME')[1]
)
redis.call('EXPIRE', family_key, token_ttl)

return { "OK", family_id, tostring(new_iteration) }
```

### 3.3 Node.js / TypeScript Orchestrator

```typescript
// tokenEngine.ts
import { createHash, randomBytes } from 'crypto';
import Redis from 'ioredis';
import { SignJWT } from 'jose';

const redis = new Redis(process.env.REDIS_URL || 'redis://127.0.0.1:6379');

const ROTATE_LUA_SCRIPT = `
-- [Insert Lua Script From Section 3.2 Here]
`;

redis.defineCommand('rotateRefreshToken', {
  numberOfKeys: 2,
  lua: ROTATE_LUA_SCRIPT,
});

declare module 'ioredis' {
  interface RedisCommander<Context> {
    rotateRefreshToken(
      tokenKey: string,
      familyKey: string,
      expectedFamilyId: string,
      newTokenHash: string,
      tokenTtl: number,
      clientIp: string,
      userAgent: string
    ): Promise<[string, string, string]>;
  }
}

export function hashToken(token: string): string {
  return createHash('sha256').update(token).digest('hex');
}

export interface RotationResult {
  accessToken: string;
  refreshToken: string;
  familyId: string;
  iteration: number;
}

export async function rotateSession(
  rawRefreshToken: string,
  familyId: string,
  userId: string,
  clientIp: string,
  userAgent: string,
  privateKey: Uint8Array | CryptoKey
): Promise<RotationResult> {
  const currentTokenHash = hashToken(rawRefreshToken);
  const newRawRefreshToken = randomBytes(48).toString('base64url');
  const newTokenHash = hashToken(newRawRefreshToken);

  const tokenKey = `refresh_token:${currentTokenHash}`;
  const familyKey = `token_family:${familyId}`;
  const REFRESH_TOKEN_TTL = 30 * 24 * 60 * 60; // 30 days

  try {
    const result = await redis.rotateRefreshToken(
      tokenKey,
      familyKey,
      familyId,
      newTokenHash,
      REFRESH_TOKEN_TTL,
      clientIp,
      userAgent
    );

    const iteration = parseInt(result[2], 10);

    // Generate new Access Token (Stateless, 10 min lifetime)
    const accessToken = await new SignJWT({
      sub: userId,
      fam: familyId,
      itr: iteration,
    })
      .setProtectedHeader({ alg: 'EdDSA', typ: 'JWT' })
      .setIssuedAt()
      .setIssuer('https://auth.platform.io')
      .setAudience('https://api.platform.io')
      .setExpirationTime('10m')
      .sign(privateKey);

    return {
      accessToken,
      refreshToken: newRawRefreshToken,
      familyId,
      iteration,
    };
  } catch (error: any) {
    if (error.message.includes('ERR_TOKEN_REUSE_DETECTED')) {
      // Security Alert Trigger: Notify SIEM / User Security Center
      await handleSecurityBreach(userId, familyId, clientIp);
    }
    throw error;
  }
}

async function handleSecurityBreach(userId: string, familyId: string, ip: string): Promise<void> {
  // 1. Invalidate all active family sessions for this user if configured
  console.error(`ALERT: Token reuse detected for User ${userId}, Family ${familyId} from IP ${ip}`);
  // Add audit logging and SIEM hooks here
}
```

---

## 4. Cross-Origin Cookie Security & Hardening

Storing tokens in `localStorage` or `sessionStorage` exposes tokens directly to Cross-Site Scripting (XSS) extraction. Single Page Applications and decoupled Web Frontends must store tokens in cryptographically protected, browser-managed cookies.

### 4.1 Cookie Flags Specification

| Attribute | Value | Explicit Functionality & Security Property |
| :--- | :--- | :--- |
| **Prefix** | `__Host-` | Enforces that the cookie MUST be sent only to the host serving it (no subdomains), MUST be set from a secure origin (`https://`), and MUST have path set to `/`. |
| `HttpOnly` | `true` | Prevents read access through JavaScript (`document.cookie`), neutralizing token theft via XSS. |
| `Secure` | `true` | Browser restricts transmission exclusively to encrypted TLS channels. |
| `SameSite` | `Strict` or `Lax` | `Strict` ensures the cookie is never sent with cross-site requests (e.g., following external links). `Lax` allows top-level navigations. For pure REST APIs, use `Strict`. |
| `Partitioned`| `true` | Opts the cookie into Chips (Cookies Having Independent Partitioned State), securing embedded contexts across top-level boundaries. |

### 4.2 Fastify / Express Production Cookie Setter

```typescript
// cookieSecurity.ts
import { Response } from 'express';

const IS_PROD = process.env.NODE_ENV === 'production';

export function setAuthCookies(
  res: Response, 
  accessToken: string, 
  refreshToken: string
): void {
  // Access Token: Ephemeral, strict lifecycle (10 minutes)
  res.cookie('__Host-access_token', accessToken, {
    httpOnly: true,
    secure: IS_PROD,
    sameSite: 'strict',
    path: '/',
    maxAge: 10 * 60 * 1000, // 10 minutes
  });

  // Refresh Token: Long-lived, pinned to refresh endpoint via reverse proxy
  // Note: __Host- prefix mandates path="/" so endpoint scoping must be enforced at Gateway
  res.cookie('__Host-refresh_token', refreshToken, {
    httpOnly: true,
    secure: IS_PROD,
    sameSite: 'strict',
    path: '/',
    maxAge: 30 * 24 * 60 * 60 * 1000, // 30 days
  });
}

export function clearAuthCookies(res: Response): void {
  res.clearCookie('__Host-access_token', { path: '/', httpOnly: true, secure: IS_PROD, sameSite: 'strict' });
  res.clearCookie('__Host-refresh_token', { path: '/', httpOnly: true, secure: IS_PROD, sameSite: 'strict' });
}
```

### 4.3 Nginx Gateway Strict CORS & Header Hardening

```nginx
# /etc/nginx/conf.d/security_api.conf

map $http_origin $allowed_origin {
    default "";
    "https://app.platform.io" "$http_origin";
    "https://admin.platform.io" "$http_origin";
}

server {
    listen 443 ssl http2;
    server_name api.platform.io;

    ssl_certificate /etc/letsencrypt/live/api.platform.io/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.platform.io/privkey.pem;

    # SSL Hardening (A+ Configuration)
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;

    # Defense In Depth Headers
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Content-Security-Policy "default-src 'none'; frame-ancestors 'none';" always;

    location / {
        # Strict Dynamic CORS Handling
        if ($allowed_origin = "") {
            return 403;
        }

        # Handling Preflights
        if ($request_method = 'OPTIONS') {
            add_header 'Access-Control-Allow-Origin' "$allowed_origin" always;
            add_header 'Access-Control-Allow-Credentials' 'true' always;
            add_header 'Access-Control-Allow-Methods' 'GET, POST, PUT, PATCH, DELETE, OPTIONS' always;
            add_header 'Access-Control-Allow-Headers' 'Authorization, Content-Type, X-Request-ID, Traceparent' always;
            add_header 'Access-Control-Max-Age' 86400 always;
            add_header 'Content-Type' 'text/plain charset=UTF-8';
            add_header 'Content-Length' 0;
            return 204;
        }

        add_header 'Access-Control-Allow-Origin' "$allowed_origin" always;
        add_header 'Access-Control-Allow-Credentials' 'true' always;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;

        proxy_pass http://internal_api_upstream;
    }
}
```

---

## 5. Stateless JWT Cryptographic Validation

Resource servers perform stateless verification without database queries on every HTTP request. Authentication verifies the JWT signature, verifies valid issuance window parameters, and matches expected claims.

### 5.1 Verification Logic (TypeScript via `jose`)

```typescript
// jwtValidator.ts
import { createRemoteJWKSet, jwtVerify, JWTVerifyResult } from 'jose';

const JWKS_URI = new URL('https://auth.platform.io/.well-known/jwks.json');

// Memory-cached JWKS fetcher with auto-cooldown and rotation handling
const remoteJWKS = createRemoteJWKSet(JWKS_URI, {
  cacheMaxAge: 10 * 60 * 1000, // 10 minutes cache
  cooldownDuration: 30 * 1000,   // Prevent DoS through forced misses
});

export interface AppJWTPayload {
  sub: string;
  fam: string;
  itr: number;
  roles?: string[];
  permissions?: string[];
}

export async function validateAccessToken(token: string): Promise<AppJWTPayload> {
  try {
    const { payload }: JWTVerifyResult = await jwtVerify(token, remoteJWKS, {
      issuer: 'https://auth.platform.io',
      audience: 'https://api.platform.io',
      algorithms: ['RS256', 'EdDSA'], // Explicitly whitelist cryptographic algorithms; prevent alg: "none"
      clockTolerance: 5, // 5 seconds grace window for skew
    });

    return {
      sub: payload.sub as string,
      fam: payload.fam as string,
      itr: payload.itr as number,
      roles: payload['https://api.platform.io/roles'] as string[] | undefined,
      permissions: payload['https://api.platform.io/permissions'] as string[] | undefined,
    };
  } catch (error: any) {
    throw new Error(`JWT Validation Failed: ${error.message}`);
  }
}
```

---

## 6. Zero-Trust Real-Time Session Revocation Architecture

Short-lived JWTs (5–15 minutes) reduce reliance on a central database. However, events like privilege revocations, administrative lockouts, or breach containment require **instant** invalidation, without waiting for the token's natural expiration.

### 6.1 Two-Tier Invalidation Strategy

1.  **Tier 1 (Stateless):** JWT validity checks against signature, expiration, and issuer.
2.  **Tier 2 (Real-Time Invalidation Layer):** API Gateways check a sub-millisecond centralized memory cache (Redis Bloom Filter or Set) to confirm the token ID (`jti`) or Token Family (`fam`) has not been revoked.

```
Incoming Request -> [ JWT Valid? ] -> NO  -> [ Return 401 ]
                           |
                          YES
                           v
                   [ Redis: Exists in ] -> YES -> [ Block Request: Return 401 ]
                   [ 'revoked:jti' or ]
                   [ 'revoked:fam' ?  ]
                           |
                          NO
                           v
              [ Forward to Resource Server ]
```

### 6.2 Redis Fast Revocation Store

```typescript
// revocationManager.ts
import Redis from 'ioredis';

const redis = new Redis(process.env.REDIS_URL || 'redis://127.0.0.1:6379');

export class RevocationManager {
  /**
   * Revokes an explicit access token by JTI until its natural expiration.
   */
  public static async revokeJti(jti: string, expiresAtUnixSeconds: number): Promise<void> {
    const now = Math.floor(Date.now() / 1000);
    const ttl = expiresAtUnixSeconds - now;

    if (ttl > 0) {
      await redis.set(`revoked:jti:${jti}`, '1', 'EX', ttl);
    }
  }

  /**
   * Revokes an entire token family instantly across all sessions.
   */
  public static async revokeFamily(familyId: string, ttlSeconds: number = 86400): Promise<void> {
    await redis.set(`revoked:fam:${familyId}`, '1', 'EX', ttlSeconds);
  }

  /**
   * Evaluates if the token JTI or Family ID has been blacklisted.
   */
  public static async isRevoked(jti: string, familyId?: string): Promise<boolean> {
    const keysToCheck = [`revoked:jti:${jti}`];
    if (familyId) {
      keysToCheck.push(`revoked:fam:${familyId}`);
    }

    const hits = await redis.exists(...keysToCheck);
    return hits > 0;
  }
}
```

### 6.3 Event-Driven Revocation Webhook (CloudEvents Spec)

When a security incident or session kill occurs, dispatch this standard JSON event to invalidate tokens immediately across multi-region API Gateways:

```json
{
  "specversion": "1.0",
  "type": "com.platform.auth.session.revoked",
  "source": "https://auth.platform.io/audit",
  "id": "f81d4fae-7dec-11d0-a765-00a0c91e6bf6",
  "time": "2026-03-31T09:12:28Z",
  "datacontenttype": "application/json",
  "data": {
    "userId": "usr_99x8172dfa",
    "familyId": "fam_a023b984-7a42-49da",
    "jti": "urn:uuid:6c84fb90-12c4-11e1-840d-7b25c5ee775a",
    "reason": "ADMINISTRATIVE_REVOCATION",
    "revocationScope": "FAMILY",
    "expiresAt": 1774948348
  }
}
```

---

## 7. Production Hardening Checklist

Verify every parameter before deploying this auth stack to production:

```markdown
### 1. Protocol & Grant Types
- [ ] Implicit Flow disabled on all Authorization Servers.
- [ ] Resource Owner Password Credentials (ROPC) grant completely deprecated.
- [ ] Authorization Code Grant strictly requires PKCE (code_challenge_method=S256 enforced).
- [ ] Redirect URIs strictly matched using exact string comparison (no dynamic wildcards).

### 2. Cookie Hardening
- [ ] Cookies generated using the `__Host-` prefix.
- [ ] `HttpOnly` flag enabled on both Access and Refresh tokens.
- [ ] `Secure` flag enabled (rejects HTTP cleartext traffic).
- [ ] `SameSite=Strict` deployed on state-changing API channels.
- [ ] `Path` forced to `/` (mandatory for `__Host-`).

### 3. Token Rotation Engine
- [ ] Refresh tokens rotated on every single use via atomic transaction/Lua.
- [ ] Old refresh tokens placed in a temporary grace window (< 30s) or destroyed immediately.
- [ ] Token Reuse Detection drops the entire family hierarchy to status `REVOKED`.
- [ ] High-entropy cryptographically secure pseudo-random generators (`crypto.getRandomValues`) used exclusively.

### 4. JWT & Cryptographic Identity
- [ ] Algorithm agility attacks prevented: Validation code explicitly whitelists valid signatures (e.g., `['EdDSA', 'RS256']`).
- [ ] Symmetric algorithms (e.g., `HS256`) explicitly prohibited on public endpoints.
- [ ] Audience (`aud`), Issuer (`iss`), and Expiration (`exp`) validated deterministically.
- [ ] JWKS fetcher leverages cached memory mechanisms with strict rate limits and error cooldowns.
- [ ] Access token TTL limited to a maximum of 15 minutes.
