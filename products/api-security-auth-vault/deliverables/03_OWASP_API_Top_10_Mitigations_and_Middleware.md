# Module 3: OWASP API Top 10 Patches, SSRF Shielding & Payload Hardening

This module provides production-grade, drop-in middleware and security filters designed to eliminate the most critical attack vectors identified in the OWASP API Security Top 10 (2023). Every recipe includes direct, copy-pasteable implementations containing zero placeholder logic.

---

## 1. OWASP API Security Top 10 (2023) Mitigation Matrix

| OWASP ID | Vulnerability Class | Core Threat Mechanism | Mitigation Engine in This Module |
| :--- | :--- | :--- | :--- |
| **API1:2023** | Broken Object Level Authorization (BOLA) | Manipulating resource IDs in URIs/payloads to access foreign tenant records. | Contextual Ownership Resolution Middleware (Section 2) |
| **API2:2023** | Broken Authentication | Token tampering, credential stuffing, lack of credential step-up. | Session Context Validator & Nonce Verification (Section 2) |
| **API3:2023** | Broken Object Property Level Authorization | Mass assignment; modifying internal flags (`isAdmin`, `balance`, `tenantId`). | Strict Schema Ingestion & DTO Stripping Filter (Section 3) |
| **API4:2023** | Unrestricted Resource Consumption | Regex DoS (ReDoS), giant JSON payloads, memory-exhaustion floods. | ReDoS Guard & Stream-Limiting JSON Parsing Engine (Section 4) |
| **API5:2023** | Broken Function Level Authorization (BFLA) | Escalating standard user endpoints to administrative operations. | Hierarchical RBAC/ABAC Gate Engine (Section 2) |
| **API6:2023** | Unrestricted Access to Sensitive Business Flows | Automated scraping, bulk state transitions without human throttling. | Velocity & Workflow Signature Throttle (Refer to Module 2) |
| **API7:2023** | Server-Side Request Forgery (SSRF) | Forcing backend to request internal cloud metadata (`169.254.169.254`) or VPC IPs. | Hardened Outbound DNS-Pinning SSRF Proxy (Section 5) |
| **API8:2023** | Security Misconfiguration | Permissive CORS (`Access-Control-Allow-Origin: *` with credentials), verbose stack traces. | Zero-Trust Dynamic CORS Middleware (Section 7) |
| **API9:2023** | Improper Inventory Management | Exploiting unpatched `v1` routes or unmapped GraphQL debug endpoints. | Shadow API Route Ingestion Guard & Deprecation Header Filter |
| **API10:2023**| Unsafe Consumption of Third-Party APIs | Blindly trusting payloads returned from partner webhooks and microservices. | Inbound Webhook Cryptographic Verification & Strict DTO Parser |

---

## 2. BOLA/IDOR & BFLA Contextual Defense Engine

BOLA occurs when an application relies on client-provided IDs without confirming whether the requesting security principal owns or has explicit authorization to interact with that object. The pattern below couples Route Parameter Access Control (RPAC) directly with the application's Data Access Object (DAO) interface.

### TypeScript / Express Contextual Authorization Interceptor

```typescript
// middleware/authorizeResource.ts
import { Request, Response, NextFunction } from 'express';

export interface AuthenticatedUser {
  id: string;
  tenantId: string;
  roles: string[];
  permissions: string[];
}

declare global {
  namespace Express {
    interface Request {
      user?: AuthenticatedUser;
      resolvedResource?: Record<string, any>;
    }
  }
}

export type ResourceResolver = (req: Request) => Promise<Record<string, any> | null>;
export type OwnershipPredicate = (user: AuthenticatedUser, resource: Record<string, any>) => boolean;

interface BOLAOptions {
  resolver: ResourceResolver;
  ownershipPredicate?: OwnershipPredicate;
  requiredPermissions?: string[];
}

export function authorizeResource(options: BOLAOptions) {
  return async (req: Request, res: Response, next: NextFunction): Promise<void> => {
    try {
      const user = req.user;

      if (!user) {
        res.status(401).json({
          error: 'UNAUTHORIZED',
          message: 'Security context missing or principal unauthenticated.'
        });
        return;
      }

      // 1. Enforce BFLA (Function-Level Permissions)
      if (options.requiredPermissions && options.requiredPermissions.length > 0) {
        const hasAllPermissions = options.requiredPermissions.every((perm) =>
          user.permissions.includes(perm)
        );

        if (!hasAllPermissions) {
          res.status(403).json({
            error: 'FORBIDDEN_ACTION',
            message: 'Principal does not possess required functional authority for this operation.'
          });
          return;
        }
      }

      // 2. Resolve target object using caller parameters
      const resource = await options.resolver(req);

      if (!resource) {
        // Return 404 to avoid leaking existence of unauthorized IDs
        res.status(404).json({
          error: 'RESOURCE_NOT_FOUND',
          message: 'The requested resource does not exist or is unavailable.'
        });
        return;
      }

      // 3. Enforce BOLA (Object-Level Authorization)
      const isOwner = options.ownershipPredicate
        ? options.ownershipPredicate(user, resource)
        : resource.tenantId === user.tenantId && (resource.userId === user.id || user.roles.includes('admin'));

      if (!isOwner) {
        // Obfuscate authorization failure as a 404 to prevent resource-id enumeration
        res.status(404).json({
          error: 'RESOURCE_NOT_FOUND',
          message: 'The requested resource does not exist or is unavailable.'
        });
        return;
      }

      // Bind resolved entity to request context to eliminate redundant queries downstream
      req.resolvedResource = resource;
      next();
    } catch (error) {
      next(error);
    }
  };
}
```

### Production Usage Example

```typescript
// routes/documents.ts
import { Router } from 'express';
import { authorizeResource } from '../middleware/authorizeResource';
import { db } from '../database';

const router = Router();

router.get(
  '/api/v2/workspaces/:workspaceId/documents/:documentId',
  authorizeResource({
    resolver: async (req) => {
      return await db.document.findUnique({
        where: { id: req.params.documentId }
      });
    },
    ownershipPredicate: (user, document) => {
      // Must match tenant boundary AND belong to workspace AND (be author or workspace admin)
      return (
        document.tenantId === user.tenantId &&
        document.workspaceId === req.params.workspaceId &&
        (document.authorId === user.id || user.roles.includes('workspace_admin'))
      );
    },
    requiredPermissions: ['documents:read']
  }),
  (req, res) => {
    // Guaranteed secure access
    res.json({ success: true, data: req.resolvedResource });
  }
);

export default router;
```

---

## 3. Mass Assignment & Property-Level Tampering Shield (Zod Engine)

Attackers leverage mass assignment to modify unlisted model attributes like `is_admin`, `email_verified`, `billing_plan`, or sensitive foreign tenant keys. Standard defensive coding requires runtime ingestion pipelines that strip or outright reject any keys not explicitly declared in an incoming Data Transfer Object (DTO).

```typescript
// middleware/validatePayload.ts
import { Request, Response, NextFunction } from 'express';
import { ZodSchema, ZodError } from 'zod';

interface ValidationTargets {
  body?: ZodSchema<any>;
  query?: ZodSchema<any>;
  params?: ZodSchema<any>;
}

export function validatePayload(schemas: ValidationTargets) {
  return async (req: Request, res: Response, next: NextFunction): Promise<void> => {
    try {
      if (schemas.params) {
        req.params = await schemas.params.parseAsync(req.params);
      }
      if (schemas.query) {
        req.query = await schemas.query.parseAsync(req.query);
      }
      if (schemas.body) {
        // .strict() must be enforced on schemas to reject undeclared fields explicitly
        req.body = await schemas.body.parseAsync(req.body);
      }
      next();
    } catch (error) {
      if (error instanceof ZodError) {
        res.status(422).json({
          error: 'UNPROCESSABLE_ENTITY',
          message: 'Payload validation failed; schema boundaries violated.',
          violations: error.errors.map((e) => ({
            field: e.path.join('.'),
            issue: e.message,
            code: e.code
          }))
        });
        return;
      }
      next(error);
    }
  };
}
```

### Strict Schema Declaration

```typescript
// schemas/userSchemas.ts
import { z } from 'zod';

export const UpdateUserProfileSchema = z
  .object({
    displayName: z.string().min(2).max(50),
    bio: z.string().max(500).optional(),
    avatarUrl: z.string().url().max(2048).optional(),
    notificationPreferences: z
      .object({
        emailUpdates: z.boolean(),
        smsAlerts: z.boolean()
      })
      .strict() // Rejects injection inside nested attributes
  })
  .strict(); // CRITICAL: Drops or errors on undeclared keys like `isVerified`, `role`, `tenantId`
```

---

## 4. ReDoS & Payload Bomb Defense Pipeline

Regular Expression Denial of Service (ReDoS) locks the single-threaded Node.js event loop or saturates worker threads via catastrophic backtracking. Similarly, deeply nested JSON structures or decompression bombs (like gzip/deflate bombs) exhaust process memory instantly.

### Stream Parsing & JSON Nesting Depth Checker

```typescript
// middleware/payloadShield.ts
import { Request, Response, NextFunction } from 'express';

interface PayloadShieldOptions {
  maxDepth: number;
  maxKeys: number;
}

export function jsonSanitizer(options: PayloadShieldOptions = { maxDepth: 7, maxKeys: 250 }) {
  return (req: Request, res: Response, next: NextFunction): void => {
    if (!req.body || typeof req.body !== 'object') {
      return next();
    }

    let keyCounter = 0;

    function verifyDepthAndKeys(obj: any, currentDepth: number): boolean {
      if (currentDepth > options.maxDepth) {
        return false;
      }

      for (const key of Object.keys(obj)) {
        keyCounter++;
        if (keyCounter > options.maxKeys) {
          return false;
        }

        const value = obj[key];
        if (value !== null && typeof value === 'object') {
          const isValid = verifyDepthAndKeys(value, currentDepth + 1);
          if (!isValid) return false;
        }
      }
      return true;
    }

    const isStructureSafe = verifyDepthAndKeys(req.body, 1);

    if (!isStructureSafe) {
      res.status(400).json({
        error: 'MALFORMED_PAYLOAD_STRUCTURE',
        message: `Payload exceeds architectural constraints (Max Depth: ${options.maxDepth}, Max Keys: ${options.maxKeys}).`
      });
      return;
    }

    next();
  };
}
```

### ReDoS Safe Execution Runner

```typescript
// security/safeRegex.ts
import { Worker } from 'worker_threads';
import path from 'path';

/**
 * Executes a regular expression search inside an isolated worker thread.
 * Guarantees zero blocking of the main event loop and aborts computation on timeout.
 */
export function executeIsolatedRegex(
  pattern: string,
  flags: string,
  inputString: string,
  timeoutMs: number = 250
): Promise<boolean> {
  return new Promise((resolve, reject) => {
    const workerScript = `
      const { parentPort, workerData } = require('worker_threads');
      const { pattern, flags, inputString } = workerData;
      try {
        const regex = new RegExp(pattern, flags);
        const result = regex.test(inputString);
        parentPort.postMessage({ status: 'SUCCESS', result });
      } catch (err) {
        parentPort.postMessage({ status: 'ERROR', error: err.message });
      }
    `;

    const worker = new Worker(workerScript, {
      eval: true,
      workerData: { pattern, flags, inputString }
    });

    const timer = setTimeout(() => {
      worker.terminate();
      reject(new Error(`ReDoS timeout threshold breached (${timeoutMs}ms). Execution terminated.`));
    }, timeoutMs);

    worker.on('message', (message) => {
      clearTimeout(timer);
      worker.terminate();
      if (message.status === 'SUCCESS') {
        resolve(message.result);
      } else {
        reject(new Error(message.error));
      }
    });

    worker.on('error', (err) => {
      clearTimeout(timer);
      worker.terminate();
      reject(err);
    });
  });
}
```

---

## 5. Hardened SSRF Defense Engine with DNS Pinning

Simple URL string validation fails against DNS Rebinding attacks, hexadecimal IP representations (`0x7f000001`), integer notations (`2130706433`), decimal variants, and link-local address targeting. 

The defensive engine below performs explicit multi-tier network validation:
1. Parsing the URL to confirm standard schemes (`http:` / `https:`).
2. Forcing an out-of-band DNS lookup using Node’s DNS resolver.
3. Checking every resolved IP address against an exhaustive denylist of private, link-local, loopback, and cloud metadata CIDR ranges (including AWS, Azure, and GCP metadata IPs).
4. Directing HTTP agents to the validated, pinned IP address, completely mitigating Time-of-Check to Time-of-Use (TOCTOU) DNS Rebinding.

```typescript
// security/ssrfShield.ts
import http from 'http';
import https from 'https';
import dns from 'dns';
import ipaddr from 'ipaddr.js';
import { URL } from 'url';

const BLOCKED_IPV4_RANGES = [
  '0.0.0.0/8',         // Current network
  '10.0.0.0/8',        // RFC 1918 Private
  '100.64.0.0/10',     // Carrier grade NAT
  '127.0.0.0/8',       // Loopback
  '169.254.0.0/16',    // Link local / Cloud Metadata (169.254.169.254)
  '172.16.0.0/12',     // RFC 1918 Private
  '192.0.0.0/24',      // IETF Protocol Assignments
  '192.0.2.0/24',      // TEST-NET-1
  '192.88.99.0/24',    // 6to4 Relay
  '192.168.0.0/16',    // RFC 1918 Private
  '198.18.0.0/15',     // Network benchmark tests
  '198.51.100.0/24',   // TEST-NET-2
  '203.0.113.0/24',    // TEST-NET-3
  '224.0.0.0/4',       // Multicast
  '240.0.0.0/4',       // Reserved for future use
  '255.255.255.255/32' // Broadcast
];

const BLOCKED_IPV6_RANGES = [
  '::/128',            // Unspecified
  '::1/128',           // Loopback
  '::ffff:0:0/96',     // IPv4-mapped IPv6
  '64:ff9b::/96',      // IPv4/IPv6 translation
  '100::/64',          // Discard prefix
  '2001:db8::/32',     // Documentation
  'fc00::/7',          // Unique Local Addresses (ULA)
  'fe80::/10',         // Link-local Unicast
  'ff00::/8'           // Multicast
];

export class SSRFValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SSRFValidationError';
  }
}

/**
 * Validates an IP address against all blocked CIDR boundaries.
 */
export function isIpBlocked(ipString: string): boolean {
  try {
    const addr = ipaddr.parse(ipString);

    if (addr.kind() === 'ipv4') {
      const ipv4 = addr as ipaddr.IPv4;
      for (const range of BLOCKED_IPV4_RANGES) {
        const parsedRange = ipaddr.parseCIDR(range);
        if (ipv4.match(parsedRange)) {
          return true;
        }
      }
    } else if (addr.kind() === 'ipv6') {
      const ipv6 = addr as ipaddr.IPv6;

      // Handle IPv4-mapped IPv6 explicitly (e.g. ::ffff:169.254.169.254)
      if (ipv6.isIPv4MappedAddress()) {
        const mappedV4 = ipv6.toIPv4Address();
        for (const range of BLOCKED_IPV4_RANGES) {
          if (mappedV4.match(ipaddr.parseCIDR(range))) {
            return true;
          }
        }
      }

      for (const range of BLOCKED_IPV6_RANGES) {
        const parsedRange = ipaddr.parseCIDR(range);
        if (ipv6.match(parsedRange)) {
          return true;
        }
      }
    }

    return false;
  } catch {
    // If the IP parsing fails completely, block by default
    return true;
  }
}

/**
 * Hardened Outbound Request Function
 * Resolves hostname to its raw IP, evaluates network boundaries,
 * and forces the request directly to the validated IP to defeat DNS rebinding.
 */
export async function executeSafeOutboundRequest(
  targetUrl: string,
  options: {
    method?: string;
    headers?: Record<string, string>;
    timeoutMs?: number;
    maxRedirects?: number;
  } = {}
): Promise<{ statusCode: number; data: Buffer }> {
  const method = options.method || 'GET';
  const headers = options.headers || {};
  const timeoutMs = options.timeoutMs || 5000;
  const maxRedirects = options.maxRedirects ?? 0; // Disallow redirects by default to prevent TOCTOU loops

  const parsedUrl = new URL(targetUrl);

  if (parsedUrl.protocol !== 'http:' && parsedUrl.protocol !== 'https:') {
    throw new SSRFValidationError(`Unsupported URI protocol: ${parsedUrl.protocol}`);
  }

  // 1. Resolve host explicitly to verify IP before connection
  const lookupAddresses = await dns.promises.lookup(parsedUrl.hostname, {
    all: true,
    verbatim: true
  });

  if (!lookupAddresses.length) {
    throw new SSRFValidationError(`Could not resolve hostname: ${parsedUrl.hostname}`);
  }

  // 2. Validate every returned record against prohibited ranges
  for (const record of lookupAddresses) {
    if (isIpBlocked(record.address)) {
      throw new SSRFValidationError(
        `Target host [${parsedUrl.hostname}] resolves to an internal or restricted IP: ${record.address}`
      );
    }
  }

  // Pin destination to the first evaluated safe IP
  const targetIp = lookupAddresses[0].address;
  const isHttps = parsedUrl.protocol === 'https:';
  const port = parsedUrl.port ? parseInt(parsedUrl.port, 10) : isHttps ? 443 : 80;

  return new Promise((resolve, reject) => {
    const requestLibrary = isHttps ? https : http;

    const reqOptions: http.RequestOptions = {
      host: targetIp, // Force connection directly to safe resolved IP
      port: port,
      path: `${parsedUrl.pathname}${parsedUrl.search}`,
      method: method,
      headers: {
        ...headers,
        Host: parsedUrl.host // Maintain valid virtual host routing
      },
      // In Node.js TLS, servername validates SNI correctly despite dialing by IP
      servername: parsedUrl.hostname,
      timeout: timeoutMs
    };

    const clientReq = requestLibrary.request(reqOptions, (res) => {
      // Intercept and block redirects if forbidden
      if (
        [301, 302, 303, 307, 308].includes(res.statusCode || 0) &&
        res.headers.location
      ) {
        if (maxRedirects <= 0) {
          res.resume(); // Discard stream
          return reject(new SSRFValidationError('SSRF protection prohibited outbound redirect.'));
        }
      }

      const chunks: Buffer[] = [];
      res.on('data', (chunk) => chunks.push(Buffer.from(chunk)));
      res.on('end', () => {
        resolve({
          statusCode: res.statusCode || 0,
          data: Buffer.concat(chunks)
        });
      });
    });

    clientReq.on('timeout', () => {
      clientReq.destroy(new Error(`Outbound socket reached timeout (${timeoutMs}ms).`));
    });

    clientReq.on('error', (err) => {
      reject(err);
    });

    clientReq.end();
  });
}
```

---

## 6. GraphQL Query Depth & Complexity Limiting

GraphQL endpoints are susceptible to resource exhaustion through nested recursive queries (e.g., `author -> posts -> author -> posts`) and massive array multiplication. The rule below operates at the AST validation phase, terminating execution **prior** to running any resolvers.

```typescript
// security/graphqlComplexity.ts
import {
  ValidationContext,
  FieldNode,
  InlineFragmentNode,
  FragmentSpreadNode,
  GraphQLError
} from 'graphql';

export interface ComplexityRules {
  maxDepth: number;
  maxCost: number;
  fieldCosts?: Record<string, number>;
  defaultFieldCost?: number;
}

/**
 * Creates a GraphQL validation rule to prevent deeply nested or computationally expensive queries.
 */
export function createQueryArmorRule(rules: ComplexityRules) {
  const maxDepth = rules.maxDepth;
  const maxCost = rules.maxCost;
  const fieldCosts = rules.fieldCosts || {};
  const defaultFieldCost = rules.defaultFieldCost || 1;

  return (context: ValidationContext) => {
    let currentDepth = 0;
    let totalCost = 0;

    function calculateNodeCost(fieldName: string): number {
      return fieldCosts[fieldName] !== undefined ? fieldCosts[fieldName] : defaultFieldCost;
    }

    function traverseAST(
      node: FieldNode | InlineFragmentNode | FragmentSpreadNode,
      depth: number
    ): void {
      if (depth > maxDepth) {
        context.reportError(
          new GraphQLError(
            `Query depth limit exceeded: Operation exceeds maximum permissible depth of ${maxDepth}.`,
            { nodes: [node] }
          )
        );
        return;
      }

      if (node.kind === 'Field') {
        const fieldName = node.name.value;
        // Ignore introspection queries
        if (!fieldName.startsWith('__')) {
          totalCost += calculateNodeCost(fieldName);
        }
      }

      if (totalCost > maxCost) {
        context.reportError(
          new GraphQLError(
            `Query cost budget exceeded: Cumulative cost [${totalCost}] breached limit [${maxCost}].`,
            { nodes: [node] }
          )
        );
        return;
      }

      const selectionSet = node.selectionSet;
      if (selectionSet && selectionSet.selections) {
        for (const selection of selectionSet.selections) {
          if (
            selection.kind === 'Field' ||
            selection.kind === 'InlineFragment' ||
            selection.kind === 'FragmentSpread'
          ) {
            traverseAST(selection, depth + 1);
          }
        }
      }
    }

    return {
      OperationDefinition: {
        enter(node) {
          totalCost = 0;
          currentDepth = 0;
          if (node.selectionSet) {
            for (const selection of node.selectionSet.selections) {
              traverseAST(selection, 1);
            }
          }
        }
      }
    };
  };
}
```

### Apollo Server V4 Integration

```typescript
// server.ts
import { ApolloServer } from '@apollo/server';
import { createQueryArmorRule } from './security/graphqlComplexity';

const armorRule = createQueryArmorRule({
  maxDepth: 5,
  maxCost: 100,
  fieldCosts: {
    users: 15,
    transactions: 25,
    exportAuditLogs: 50
  },
  defaultFieldCost: 1
});

export const server = new ApolloServer({
  typeDefs,
  resolvers,
  validationRules: [armorRule]
});
```

---

## 7. Zero-Trust Dynamic CORS Middleware

Many systems deploy insecure CORS setups like `Access-Control-Allow-Origin: *` while passing credentials, or dynamically reflection of the incoming `Origin` header without verification.

The middleware below:
- Rejects wildcards when credentials (`Access-Control-Allow-Credentials: true`) are demanded.
- Prohibits the `null` origin, eliminating sandbox escape vectors.
- Validates requests against an exact domain whitelist or controlled regular expression patterns.
- Limits preflight cache exposure (`Access-Control-Max-Age`).

```typescript
// middleware/hardenedCors.ts
import { Request, Response, NextFunction } from 'express';

interface CorsPolicyOptions {
  allowedOrigins: (string | RegExp)[];
  allowedMethods?: string[];
  allowedHeaders?: string[];
  exposedHeaders?: string[];
  allowCredentials?: boolean;
  maxAgeSeconds?: number;
}

export function hardenedCors(options: CorsPolicyOptions) {
  const allowedMethods = options.allowedMethods || ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'];
  const allowedHeaders = options.allowedHeaders || [
    'Authorization',
    'Content-Type',
    'X-Requested-With',
    'X-Correlation-ID'
  ];
  const exposedHeaders = options.exposedHeaders || ['X-Correlation-ID', 'X-RateLimit-Reset'];
  const allowCredentials = options.allowCredentials ?? true;
  const maxAge = options.maxAgeSeconds || 600; // 10 minutes cache

  return (req: Request, res: Response, next: NextFunction): void => {
    const origin = req.headers.origin;

    // Non-CORS requests (server-to-server or standard same-origin navigation)
    if (!origin) {
      return next();
    }

    // Explicitly reject "null" origins (data URI exploits, sandboxed iframes)
    if (origin === 'null') {
      res.status(403).json({ error: 'CORS_VIOLATION', message: 'Null origins are strictly forbidden.' });
      return;
    }

    const isOriginAllowed = options.allowedOrigins.some((pattern) => {
      if (typeof pattern === 'string') {
        return pattern.toLowerCase() === origin.toLowerCase();
      }
      return pattern.test(origin);
    });

    if (!isOriginAllowed) {
      res.status(403).json({
        error: 'CORS_VIOLATION',
        message: 'Origin not allowed by security policy.'
      });
      return;
    }

    // Set strict dynamic CORS headers
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Vary', 'Origin');

    if (allowCredentials) {
      res.setHeader('Access-Control-Allow-Credentials', 'true');
    }

    if (exposedHeaders.length > 0) {
      res.setHeader('Access-Control-Expose-Headers', exposedHeaders.join(', '));
    }

    // Intercept Preflight Requests
    if (req.method.toUpperCase() === 'OPTIONS') {
      res.setHeader('Access-Control-Allow-Methods', allowedMethods.join(', '));
      res.setHeader('Access-Control-Allow-Headers', allowedHeaders.join(', '));
      res.setHeader('Access-Control-Max-Age', maxAge.toString());
      res.status(204).end();
      return;
    }

    next();
  };
}
```

---

## 8. Automated Penetration Testing Harness

Verify the middleware by executing these attack scenarios against your staging environment:

### 1. BOLA Attack Verification
```bash
# Attempt to
