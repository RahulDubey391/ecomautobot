# Module 1: The Master AI Coding & Agent Architecture Playbook

## 1. Why Default AI Coding Assistants Fail at Scale

Out of the box, LLM coding environments optimize for **plausible-looking completion** rather than **architectural integrity**. Without explicit guardrails, coding agents routinely exhibit five failure modes:

1. **Context Drift:** Forgetting your repository's folder structure, error-handling pattern, or ORM conventions halfway through a feature.
2. **Destructive Edits:** Deleting existing comments, edge-case guards, or unrelated functions while fixing a bug.
3. **Hallucinated Signatures:** Mixing v1 and v2 library APIs (e.g., Pydantic v1 `@validator` vs. v2 `@field_validator`, or Next.js Pages Router vs. App Router).
4. **Premature Implementation:** Writing 400 lines of code before clarifying ambiguous requirements or checking existing helper utilities.
5. **Unverified Output:** Declaring a task "complete" without running typechecks, linters, or unit tests.

---

## 2. The Universal File Placement Matrix

Copy the rules from Modules 2 and 3 into the file path corresponding to your editor:

| AI Coding Tool | File Path in Repository Root | Scoping Mechanism |
| :--- | :--- | :--- |
| **Cursor** | `.cursor/rules/00-core.mdc` (or `.cursorrules`) | Glob-based frontmatter (`globs: ["**/*.ts", "**/*.tsx"]`) |
| **Claude Code** | `CLAUDE.md` | Hierarchical (root `CLAUDE.md` + subdirectory `CLAUDE.md`) |
| **Windsurf** | `.windsurfrules` | Workspace root instructions |
| **GitHub Copilot** | `.github/copilot-instructions.md` | Repository-wide system prompt |

---

## 3. The Core Behavioral Kernel (Drop-In Base Template)

Paste this foundational block at the top of your `CLAUDE.md` or `.cursorrules` file in any project:

```markdown
# Core Engineering Operating System

## 1. Execution Protocol (Plan -> Verify -> Implement -> Test)
- **Read Before Writing:** Never propose edits to a file you have not read in full during the current session.
- **Reuse First:** Before creating any new utility, hook, schema, or helper, search the codebase for existing implementations.
- **Minimal Diff Principle:** Change the minimum number of lines required to solve the problem. Never reformat unrelated code or strip existing comments.
- **Explicit Uncertainty:** If a requirement has two conflicting interpretations, state the tradeoff in 3 bullet points and ask before writing code.

## 2. Code Quality & Modularity Invariants
- **No Silent Failures:** Never swallow exceptions with bare `catch {}` or `except Exception: pass`. Log structured context or re-raise domain-specific errors.
- **Strict Typing:** Never use `any` (TypeScript) or untyped dicts (Python) at module boundaries. Define explicit interfaces, Zod schemas, or Pydantic models.
- **File Size Ceiling:** Keep individual source files under 300 lines. When a module exceeds 300 lines, extract cohesive sub-modules.
- **Self-Verification:** After every code change, run the project's typechecker and test suite covering the modified path before reporting completion.
```

---

## 4. Persistent Project Memory (`MEMORY.md` Pattern)

For multi-week projects, create a `docs/AGENT_CONTEXT.md` file and add this rule to your agent config:

```markdown
## Session Continuity Protocol
1. At the start of every task, read `docs/AGENT_CONTEXT.md` to understand current architecture, active migrations, and known constraints.
2. When introducing a new dependency, environment variable, or database migration, append a 2-line entry to `docs/AGENT_CONTEXT.md`.
```

