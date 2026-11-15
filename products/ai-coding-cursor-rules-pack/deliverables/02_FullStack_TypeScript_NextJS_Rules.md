# Module 2: Full-Stack TypeScript, React 19 & Next.js App Router Rules

Copy this template into `.cursor/rules/typescript-nextjs.mdc`, `CLAUDE.md`, or `.windsurfrules` for TypeScript/Next.js projects.

```markdown
---
description: Production rules for TypeScript, React 19, Next.js App Router, Tailwind CSS, and Prisma/Drizzle
globs: ["**/*.ts", "**/*.tsx"]
---

# Full-Stack TypeScript & Next.js Engineering Rules

## 1. TypeScript Strictness
- Always write strict TypeScript. `any` is strictly forbidden; use `unknown` with narrow type guards or Zod schemas at runtime boundaries.
- Prefer `interface` for public object contracts and `type` for unions, intersections, and utility types.
- Derive types from runtime schemas (`type UserInput = z.infer<typeof UserInputSchema>`) rather than duplicating interfaces manually.

## 2. Next.js App Router & Server/Client Boundaries
- **Server Components by Default:** Every component in `app/` is a React Server Component (RSC) unless it directly uses browser APIs, event listeners (`onClick`, `onChange`), or React state/effects (`useState`, `useEffect`).
- **Leaf-Level `"use client"`:** Push `"use client"` boundaries as far down the component tree as possible. Never mark an entire page or layout as `"use client"` just to support one interactive button or modal.
- **Data Fetching & Mutations:**
  - Fetch data directly in Server Components using `async/await` through a dedicated data-access layer (`src/server/queries/`).
  - Validate every Server Action and Route Handler input with **Zod** before touching the database.
  - Always verify authentication and resource authorization inside every Server Action (`auth()` check at the top of the function, never relying solely on middleware).

## 3. State Management & React Best Practices
- Avoid `useEffect` for derived state. Compute derived values during render or with `useMemo` when computationally expensive.
- Use URL search parameters (`useSearchParams` / `nuqs`) as the single source of truth for filterable tables, pagination, Tabs, and shareable UI state.
- Ensure every async action exposes explicit `loading`, `error`, and `empty` states in the UI.

## 4. Database & ORM Hygiene (Prisma / Drizzle)
- Never execute N+1 queries inside loops. Use `include`/`select` joins or batch `inArray` queries.
- Wrap multi-step database writes in an explicit transaction (`db.$transaction` or `db.transaction`).
- Always select only the columns required by the view; never return raw password hashes, internal tokens, or unredacted PII to client components.

## 5. Styling & Accessibility (Tailwind CSS + Shadcn UI)
- Use semantic HTML (`<main>`, `<nav>`, `<section>`, `<button>`, `<dialog>`) and ensure all interactive elements are keyboard-navigable with visible `:focus-visible` rings.
- Combine conditional classes cleanly using `cn()` (`clsx` + `twMerge`). Avoid inline `style={{ ... }}` unless computing dynamic coordinates.
```

