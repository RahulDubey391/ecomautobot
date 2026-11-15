# Module 4: 25 Surgical Prompts for Debugging, Security & Refactoring

Use these structured prompts inside Cursor Composer, Claude Code, or Windsurf whenever you hit a complex bug, security review, or refactoring milestone.

---

## Part A: Root-Cause Debugging Prompts

### 1. The 3-Hypothesis Root-Cause Debugger
> **Prompt:**
> "Do NOT write a fix yet. Analyze the error traceback and inspect the relevant call chain. List the 3 most likely root-cause hypotheses ranked by probability. For each hypothesis, cite the exact file and line numbers, explain the mechanism of failure, and specify one quick diagnostic check or log statement to confirm or rule it out."

### 2. Race Condition & Async State Hunter
> **Prompt:**
> "Trace the execution order of all concurrent/async operations in `<file_or_function>`. Identify any shared mutable state, unawaited promises/tasks, stale closures, or non-atomic read-modify-write sequences that could fail under concurrent requests. Show the exact interleaving timeline that triggers the bug, then propose an atomic fix."

### 3. Minimal Reproduction Test Generator
> **Prompt:**
> "Before modifying any production code, write a minimal failing unit/integration test in `<test_file>` that deterministically reproduces this bug. Run the test to confirm it fails for the expected reason, then implement the minimal fix and verify the test passes."

### 4. Production Memory Leak & Performance Profiler
> **Prompt:**
> "Inspect `<module>` for unbounded in-memory caches, unclosed file/socket/DB handles, event listeners that are never detached, or O(N^2) loops over collections. Rank each issue by severity under 100x load and refactor with bounded structures or streaming."

### 5. Git Regression Bisect Analyst
> **Prompt:**
> "Compare the current implementation of `<feature>` against its contract. Identify which edge case or state transition was broken by recent edits, and restore the invariant without reverting unrelated improvements."

---

## Part B: Security & Hardening Prompts (OWASP & Auth)

### 6. Authentication & Authorization Boundary Audit
> **Prompt:**
> "Audit all endpoints and server actions in `<directory>`. Verify that every route: (1) authenticates the caller, (2) checks ownership/tenant isolation (preventing IDOR where User A passes User B's resource ID), and (3) validates all payload fields against strict schemas. Output a table of endpoints and flag any missing checks."

### 7. Injection & Unvalidated Input Sweep
> **Prompt:**
> "Scan the codebase for any raw SQL string interpolation, shell command execution (`subprocess`, `exec`, `eval`), unescaped HTML rendering (`dangerouslySetInnerHTML`), or path traversal risks (`open(user_input)`). Replace each finding with parameterized queries, safe APIs, or strict allowlists."

### 8. Secrets & Sensitive Data Leak Check
> **Prompt:**
> "Check all config loaders, logger statements, error responses, and client-serialized payloads. Ensure no API keys, tokens, stack traces, or internal PII are ever logged in plaintext or returned in HTTP error bodies."

### 9. Rate Limiting, Idempotency & Webhook Security
> **Prompt:**
> "Review `<webhook_or_payment_handler>`. Ensure cryptographic signature verification uses constant-time comparison, replay attacks are blocked via timestamp + event ID deduplication, and database updates are idempotent if the webhook is delivered twice."

### 10. Dependency & Supply-Chain Surface Reduction
> **Prompt:**
> "Review our dependencies in `package.json` / `requirements.txt`. Identify any heavy, unmaintained, or single-function libraries that can be safely replaced with native standard-library APIs in under 30 lines of code."

---

## Part C: Zero-Regression Refactoring & Architecture Prompts

### 11. Legacy God-File Decomposition Plan
> **Prompt:**
> "Analyze `<large_file>` and design a step-by-step extraction plan to split it into cohesive modules under 250 lines each without breaking any existing imports. List each new file, its single responsibility, its public exports, and the exact order of extraction."

### 12. Characterization Test Harness Builder
> **Prompt:**
> "Before refactoring `<function_or_class>`, write a comprehensive suite of characterization tests capturing its current behavior across normal inputs, boundary values, null/empty inputs, and error conditions. Confirm 100% pass rate before changing a single line of implementation."

### 13. Database Migration Zero-Downtime Reviewer
> **Prompt:**
> "Review this schema migration for zero-downtime compatibility (expand-and-contract pattern). Flag any table-locking operations, non-nullable column additions without defaults, or column renames that would break currently running application instances during rolling deployment."

### 14. API Contract & Error Standardization
> **Prompt:**
> "Standardize all error responses across `<api_directory>` so every failure returns a consistent JSON envelope (`code`, `message`, `details`, `request_id`) with accurate HTTP status codes, while preserving existing success response shapes."

### 15. Dead Code & Orphaned Export Pruner
> **Prompt:**
> "Scan `<directory>` for unused functions, unreferenced types, commented-out code blocks, and feature flags that are permanently enabled. Verify via workspace-wide search that nothing references them dynamically, then remove them cleanly."

---

## Part D: High-Velocity Feature Delivery Prompts

### 16. Vertical Slice Spec-First Builder
> **Prompt:**
> "We need to build `<feature_name>`. First, write a 1-page technical spec covering: (1) Data model changes, (2) API/Server Action signature & validation schema, (3) UI states (loading, empty, error, success), and (4) Edge cases. Wait for my approval before implementing."

### 17. Edge-Case Matrix Generator
> **Prompt:**
> "Review the implementation of `<feature>`. Generate a checklist of 10 realistic production edge cases (network drop mid-request, double-click submission, empty state, unicode/special characters, timezone boundary, expired session) and harden the code against any unhandled ones."

### 18. Optimistic UI & Rollback Implementer
> **Prompt:**
> "Enhance `<mutation_component>` with instant optimistic UI updates so the interface responds in 0ms, while cleanly rolling back the local state and showing an actionable toast notification if the server request fails."

### 19. CLI & Developer Experience (DX) Polish
> **Prompt:**
> "Add clear `--help` documentation, input validation with actionable error messages, structured JSON output mode, and non-zero exit codes on failure to `<cli_script>`."

### 20. Pre-PR Self-Review Checklist
> **Prompt:**
> "Run `git diff` on all uncommitted changes. Review the diff as a strict Principal Engineer: check for leftover debug logs, hardcoded values, missing types, unhandled errors, or untested branches. Fix any issues found and summarize the clean diff."

---

## Part E: Multi-Agent & Prompt Engineering Prompts

### 21. Subagent Task Decomposition Prompt
> **Prompt:**
> "Break this epic into independent, non-overlapping work packages that can be executed in parallel without merge conflicts. For each package, define the exact files it owns, its input/output interface contract, and its verification command."

### 22. LLM Structured Output Schema Hardener
> **Prompt:**
> "Review this Pydantic/JSON schema used for LLM structured outputs. Add concise `Field(description=...)` docstrings, constrain free-text strings to `Literal` enums where appropriate, and flatten deeply nested objects to maximize model adherence."

### 23. RAG Retrieval & Chunking Optimizer
> **Prompt:**
> "Analyze our document chunking and retrieval pipeline. Propose concrete improvements to chunk boundaries, metadata filtering, hybrid lexical+vector scoring, and context window packing to eliminate retrieval misses."

### 24. Prompt Evaluation & Regression Dataset Builder
> **Prompt:**
> "Create a JSONL evaluation dataset of 15 representative test cases (including adversarial, ambiguous, and boundary inputs) along with deterministic assertion functions to score our prompt/agent pipeline after every edit."

### 25. Documentation & Architecture Diagram Generator
> **Prompt:**
> "Inspect the codebase and generate an up-to-date `ARCHITECTURE.md` featuring a Mermaid sequence diagram of the core request flow, a directory map, environment variable reference table, and 3-step local quickstart."

