# Module 4: Accessibility Audits, Performance Optimization & UI Review Rubric

## 1. WCAG 2.1 AA Keyboard & Screen-Reader Verification Checklist

Enterprise-grade interfaces require deterministic accessibility. Radix UI primitives provide foundational accessibility, but custom composition, dynamic state changes, TanStack table cells, and custom interactions can compromise compliance if unverified.

### 1.1 Primitive Verification Matrix

Use this matrix to manually verify complex interactive widgets before moving PRs to production.

| Component Pattern | Required ARIA Attributes | Keyboard Traversal Requirements | Focus Management Target | Expected Screen Reader Output (NVDA/VoiceOver) |
| :--- | :--- | :--- | :--- | :--- |
| **Modal Dialog** (`<Dialog />`) | `role="dialog"`, `aria-modal="true"`, `aria-labelledby="[id]"`, `aria-describedby="[id]"` | `Tab` / `Shift+Tab` cycles inside bounds only. `Escape` dismisses. | Element with `autofocus`, or first interactive descendant. On close, return to trigger. | "Dialog name, dialog, [Description text]. Close button." |
| **Combobox / Autocomplete** (`<Command />`) | `role="combobox"`, `aria-expanded="true\|false"`, `aria-controls="[list-id]"`, `aria-activedescendant="[opt-id]"` | `ArrowDown`/`ArrowUp` moves active descendant. `Enter` selects. `Escape` closes popup. | Focus remains on the `<input>`. `aria-activedescendant` tracks visual selection. | "[Count] results available. Option [X] of [Y], selected." |
| **Dropdown Menu** (`<DropdownMenu />`) | `role="menu"`, `aria-haspopup="menu"`, `aria-expanded="true\|false"`, `role="menuitem"` | `ArrowDown`/`ArrowUp` moves focus. `Home`/`End` to boundaries. Typeahead by character key. | First menuitem on open via keyboard; trigger element on dismissal. | "Menu item, [X] of [Y]". Submenus announce "Submenu collapsed/expanded". |
| **Interactive Table** (`<Table />` / TanStack) | `role="table"` (or semantic `<table>`), `aria-sort="ascending\|descending\|none"`, `aria-colindex`, `aria-rowindex` | `Tab` navigates interactive cells. Left/Right/Up/Down arrow navigation if grid mode is enabled. | Active sort button retains focus through sorting state updates. | "Column header, [Name], Sortable, Sorted ascending/descending, Column [X] of [Y]". |
| **Tabs Layout** (`<Tabs />`) | `role="tablist"`, `role="tab"`, `role="tabpanel"`, `aria-selected="true\|false"`, `aria-controls="[panel-id]"` | `ArrowLeft`/`ArrowRight` switches tabs (horizontal). `Tab` enters active panel. | Selected tab retains focus; `Tab` key skips unselected tabs directly to content panel. | "Tab, [Name], [X] of [Y], selected". Panel announces "Tabpanel, [Name]". |
| **Slide-over Sheet** (`<Sheet />`) | `role="dialog"`, `aria-modal="true"`, `aria-label="[Title]"`, `inert` on root background app. | Strict focus trap (`Tab`/`Shift+Tab`). `Escape` dismisses sheet immediately. | First interactive control (or close button). Returns to triggering button on exit. | "Dialog, [Title], Complementary/Region". Background DOM must be invisible to reader. |

### 1.2 Screen Reader Audit Protocol: NVDA & VoiceOver

Run this test script before signing off on any custom composition or Radix-based component wrapper.

```markdown
### STEP 1: macOS VoiceOver (Cmd + F5) Testing Protocol
1. Navigate to trigger using Control + Option + Right Arrow (VO + Right).
2. Verify announcement: Ensure control role (button/link) and state (expanded/collapsed) are announced.
3. Activate control with VO + Space (or Space/Enter).
4. Verify initial focus: Does VoiceOver cursor jump to the panel root or dialog title without losing context?
5. Read content sequentially using VO + Right.
   - Verify every icon-only button (e.g., close buttons, row actions) has an unambiguous `sr-only` span or `aria-label`.
   - Verify descriptive text reads completely without getting cut off by nested containers.
6. Press Escape.
   - Verify modal closes instantly.
   - Verify VoiceOver cursor returns directly to the opening trigger element.

### STEP 2: Windows NVDA (Insert + N) Testing Protocol
1. Open NVDA Speech Viewer (NVDA Menu -> Tools -> Speech Viewer).
2. Use pure keyboard navigation (Tab, Shift+Tab, Arrow keys) — DO NOT USE MOUSE.
3. Verify Combobox / Popover transitions:
   - When typing in an autocompleting Command primitive, does NVDA speak the number of matched results via an `aria-live` region?
   - Does ArrowDown update speech output with the active item's text, index, and total count without moving physical DOM focus off the input?
4. Verify Form Error States:
   - Trigger a client-side validation error.
   - Tab into the invalid input.
   - Confirm NVDA announces: "Invalid entry, [Field Name], edit, [Error message text]".
   - Implementation check: Target input must have `aria-invalid="true"` and `aria-describedby="[error-message-id]"`.
```

---

## 2. Tailwind CSS Bundle-Size Optimization & Purging Guide

Unoptimized Tailwind setups in enterprise applications commonly suffer from CSS bloat caused by dynamic string interpolation, overly broad scanning paths (such as `node_modules`), and unpurged third-party CSS.

### 2.1 The Dynamic Class Anti-Pattern vs. Safe Construction

Tailwind extracts classes by scanning static tokens in your source files before executing JavaScript. Dynamically constructed strings break the scanner and either purge needed classes or force developers into massive, uncontrolled safelists.

```typescript
// ❌ CRITICAL ANTI-PATTERN: Scanner cannot extract dynamic template literals.
// This results in missing production styles or broken variant states.
export function MetricCard({ color = "emerald" }: { color: "emerald" | "amber" | "rose" }) {
  return (
    <div className={`p-4 bg-${color}-500/10 border-${color}-500/20 text-${color}-600`}>
      Dynamic Content
    </div>
  );
}

// ✅ PRODUCTION PATTERN 1: Static maps parsed cleanly by the Tailwind compiler.
const COLOR_VARIANTS = {
  emerald: "bg-emerald-500/10 border-emerald-500/20 text-emerald-600 dark:text-emerald-400",
  amber: "bg-amber-500/10 border-amber-500/20 text-amber-600 dark:text-amber-400",
  rose: "bg-rose-500/10 border-rose-500/20 text-rose-600 dark:text-rose-400",
} as const;

export function MetricCardStatic({ color = "emerald" }: { color: keyof typeof COLOR_VARIANTS }) {
  return (
    <div className={`p-4 border rounded-lg ${COLOR_VARIANTS[color]}`}>
      Safe Compiled Content
    </div>
  );
}

// ✅ PRODUCTION PATTERN 2: class-variance-authority (cva) for type-safe variants.
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold transition-colors",
  {
    variants: {
      intent: {
        success: "border-emerald-500/30 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300",
        warning: "border-amber-500/30 bg-amber-50 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300",
        destructive: "border-rose-500/30 bg-rose-50 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300",
      },
      size: {
        sm: "text-[10px] px-1.5 py-0.25",
        md: "text-xs px-2.5 py-0.5",
      },
    },
    defaultVariants: {
      intent: "success",
      size: "md",
    },
  }
);

interface BadgeProps extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {}

export function StatusBadge({ className, intent, size, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ intent, size }), className)} {...props} />;
}
```

### 2.2 Hardened `tailwind.config.ts` Configuration

This enterprise configuration targets your exact application files, ignores dev tools, and prevents `node_modules` pollution while handling isolated UI packages.

```typescript
import type { Config } from "tailwindcss";
import tailwindcssAnimate from "tailwindcss-animate";

const config: Config = {
  darkMode: ["class"],
  // Explicitly target components, apps, and packages. NEVER pass generic paths like "./node_modules/**"
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    // If using a monorepo structure with shared UI packages:
    "../../packages/ui/src/**/*.{js,ts,jsx,tsx}",
  ],
  // Prevent arbitrary wildcard additions. If you must safelist, scope to strict regex.
  safelist: [
    // Safelist only dynamic utility variations generated by external CMS content if mandatory:
    {
      pattern: /^(bg|text|border)-(emerald|amber|rose)-(500|600)\/(10|20|30)$/,
    },
  ],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [tailwindcssAnimate],
};

export default config;
```

### 2.3 CI Bundle-Size Assertion Gate

Add this script to your build pipeline (`scripts/assert-css-size.mjs`). It checks the generated `.next/static/css` or `dist/assets` directory and halts deployment if production styles exceed the performance budget (max 45 KB gzipped).

```javascript
#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";

const CSS_DIRECTORY = path.resolve(process.cwd(), ".next/static/css");
const MAX_BUDGET_KB = 45; // Max allowed gzipped size for total production CSS

if (!fs.existsSync(CSS_DIRECTORY)) {
  console.error(`[CSS BUDGET] Directory not found: ${CSS_DIRECTORY}. Run 'next build' first.`);
  process.exit(1);
}

const files = fs.readdirSync(CSS_DIRECTORY).filter((file) => file.endsWith(".css"));
let totalBytes = 0;
let totalGzipBytes = 0;

for (const file of files) {
  const filePath = path.join(CSS_DIRECTORY, file);
  const content = fs.readFileSync(filePath);
  const gzipped = zlib.gzipSync(content);

  totalBytes += content.length;
  totalGzipBytes += gzipped.length;
}

const rawKb = (totalBytes / 1024).toFixed(2);
const gzipKb = (totalGzipBytes / 1024).toFixed(2);

console.log(`[CSS BUDGET] Total Generated CSS: ${rawKb} KB (${gzipKb} KB gzipped)`);

if (totalGzipBytes > MAX_BUDGET_KB * 1024) {
  console.error(
    `❌ [CSS BUDGET EXCEEDED] CSS exceeds maximum budget of ${MAX_BUDGET_KB} KB gzipped! (Current: ${gzipKb} KB)`
  );
  process.exit(1);
}

console.log(`✅ [CSS BUDGET PASSED] Within limits: ${gzipKb} KB <= ${MAX_BUDGET_KB} KB`);
process.exit(0);
```

Add this script to your `package.json`:

```json
{
  "scripts": {
    "build": "next build",
    "postbuild": "node scripts/assert-css-size.mjs"
  }
}
```

---

## 3. Cumulative Layout Shift (CLS) Debugging Cheat Sheet

Cumulative Layout Shift (CLS) degrades user experience and hurts Google Core Web Vitals rankings. Target a production CLS score under **0.05** (the WCAG / Web Vitals standard requires < 0.1).

### 3.1 Layout Shift Score Formula & Inspection

$$\text{Layout Shift Score} = \text{Impact Fraction} \times \text{Distance Fraction}$$

*   **Impact Fraction:** Area of viewport shifted by unstable elements.
*   **Distance Fraction:** Greatest distance unstable elements moved relative to the viewport dimension.

#### Diagnostic Workflow in Chrome DevTools:
1. Open Chrome DevTools -> **Performance Panel**.
2. Check **Screenshots** and **Web Vitals**.
3. Click **Record**, interact with UI (toggle sorting, open tabs, load dashboard), click **Stop**.
4. Check the **Experience** lane: Red blocks flag Layout Shifts.
5. Select a layout shift entry: DevTools highlights the element, displays the shift score, and points directly to the offending DOM node in the bottom summary under **Related Node**.

### 3.2 Common UI Shift Triggers & Fixes

```markdown
| Root Cause | Mechanism | Mitigation Pattern |
| :--- | :--- | :--- |
| **Data Table Async Hydration** | Dynamic data fetched on client snaps table container from 0px to 600px. | Allocate explicit min-height or render exact-row Skeleton mirrors. |
| **Icon / Avatar Placeholders** | Icons or user avatars render only after the script executes, shifting inline copy. | Render fixed-box placeholders (`w-4 h-4 aspect-square`) via `inline-block`. |
| **Collapsible / Accordion Drawers** | Expanding elements adjust heights via `height: auto` without frame transition. | Use Radix Collapsible CSS variables: `--radix-collapsible-content-height`. |
| **Custom Web Fonts** | Unstyled text renders, then snaps into new dimensions when web font swaps (FOUT). | Apply Next.js `next/font` with built-in size adjustment fallback parameters. |
```

### 3.3 Zero-CLS Skeleton Mirror for TanStack Data Tables

To prevent layout shifts during filtering, page transitions, and data revalidation, your skeleton state must mirror the exact dimensions of the loaded table.

```typescript
import * as React from "react";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface DataTableSkeletonProps {
  columnCount: number;
  rowCount?: number;
  isCompact?: boolean;
}

export function DataTableSkeleton({
  columnCount,
  rowCount = 10,
  isCompact = false,
}: DataTableSkeletonProps) {
  const rowHeightClass = isCompact ? "h-10" : "h-16";

  return (
    <div className="w-full rounded-md border border-border bg-card">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent border-b border-border">
            {Array.from({ length: columnCount }).map((_, index) => (
              <TableHead key={`head-${index}`} className="h-11 px-4">
                <Skeleton className="h-4 w-full max-w-[120px]" />
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {Array.from({ length: rowCount }).map((_, rowIndex) => (
            <TableRow
              key={`row-${rowIndex}`}
              className={`border-b border-border/50 hover:bg-transparent ${rowHeightClass}`}
            >
              {Array.from({ length: columnCount }).map((_, colIndex) => (
                <TableCell key={`cell-${rowIndex}-${colIndex}`} className="px-4">
                  <Skeleton
                    className={`h-4 w-full ${
                      colIndex === 0
                        ? "max-w-[180px]"
                        : colIndex === columnCount - 1
                        ? "max-w-[60px]"
                        : "max-w-[100px]"
                    }`}
                  />
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {/* Explicit pagination height reservation */}
      <div className="flex items-center justify-between px-4 py-4 border-t border-border min-h-[60px]">
        <Skeleton className="h-4 w-32" />
        <div className="flex items-center space-x-2">
          <Skeleton className="h-8 w-20" />
          <Skeleton className="h-8 w-20" />
        </div>
      </div>
    </div>
  );
}
```

---

## 4. Enterprise Component API Design Rubric & Scorecard

Use this rubric during design reviews and pull request approvals. Components must score at least **22 / 25** points to be merged into the production codebase.

### 4.1 Evaluation Criteria

1.  **Polymorphism & Slot Pattern (0–5 pts):** Uses Radix `Slot` (`asChild`) to let consumers swap the underlying DOM element without breaking markup hierarchies or accessibility trees.
2.  **Strict Styling Isolation (0–5 pts):** Root containers expose `className` and wrap definitions in `cn()` to cleanly merge class names without `!important` overrides.
3.  **Encapsulated State Machine (0–5 pts):** Supports both controlled and uncontrolled states (e.g., `value` + `onValueChange` alongside optional `defaultValue`).
4.  **Forwarded Refs & HTML Attributes (0–5 pts):** Exposes clean `React.forwardRef<TargetElement, Props>` types while extending standard HTML interfaces.
5.  **Strict Typing & CVA Completeness (0–5 pts):** Defines variants using `class-variance-authority`. Does not leak untyped strings or arbitrary property shapes.

### 4.2 Scorecard Template

```markdown
### PR Review Scorecard: UI Component API
**Evaluator:** Senior Frontend Architect
**Target Component:** `<MetricTrendCard />`

| Category | Score (1-5) | Audit Observations |
| :--- | :--- | :--- |
| **1. Polymorphism (`asChild`)** | 5 / 5 | Full Radix Slot integration. Allows wrapping `next/link` cleanly. |
| **2. Styling Merging & Isolation** | 4 / 5 | Uses `cn()`. Missing responsive spacing on padding variable. |
| **3. State Model (Ctrl vs Unctrl)** | 5 / 5 | Leverages Radix primitive control flow cleanly. |
| **4. Ref Forwarding & Prop Extension**| 5 / 5 | Ref passes directly to root `HTMLDivElement`. All native props bubble. |
| **5. Strict Typing & Variants** | 5 / 5 | `VariantProps<typeof trendCardVariants>` exposed and exported. |

**TOTAL SCORE:** 24 / 25 -> **STATUS: APPROVED**
```

### 4.3 Production Refactor Example

#### ❌ The Anti-Pattern (Fails review: non-polymorphic, unforwarded ref, hardcoded styles, broken typing)

```typescript
// FAILS: Score 6/25
export const BadMetricCard = ({ title, value, change, isPositive, onClick }: any) => {
  return (
    <div
      onClick={onClick}
      className={`p-6 border rounded-xl bg-white ${isPositive ? "border-green-500" : "border-red-500"}`}
    >
      <h3 className="text-gray-500 text-sm">{title}</h3>
      <div className="text-2xl font-bold">{value}</div>
      <span className={isPositive ? "text-green-600" : "text-red-600"}>{change}</span>
    </div>
  );
};
```

#### ✅ The Gold-Standard Vault Pattern (Meets all production requirements)

```typescript
import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const metricCardVariants = cva(
  "rounded-xl border p-6 shadow-sm transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
  {
    variants: {
      trend: {
        neutral: "border-border bg-card text-card-foreground",
        positive: "border-emerald-500/20 bg-card text-card-foreground",
        negative: "border-rose-500/20 bg-card text-card-foreground",
      },
      density: {
        compact: "p-4",
        normal: "p-6",
      },
    },
    defaultVariants: {
      trend: "neutral",
      density: "normal",
    },
  }
);

export interface MetricCardProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof metricCardVariants> {
  asChild?: boolean;
}

export const MetricCard = React.forwardRef<HTMLDivElement, MetricCardProps>(
  ({ className, trend, density, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "div";
    return (
      <Comp
        ref={ref}
        className={cn(metricCardVariants({ trend, density }), className)}
        {...props}
      />
    );
  }
);
MetricCard.displayName = "MetricCard";

export const MetricCardHeader = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div ref={ref} className={cn("flex items-center justify-between space-y-0 pb-2", className)} {...props} />
));
MetricCardHeader.displayName = "MetricCardHeader";

export const MetricCardTitle = React.forwardRef<
  HTMLHeadingElement,
  React.HTMLAttributes<HTMLHeadingElement>
>(({ className, ...props }, ref) => (
  <h3 ref={ref} className={cn("text-sm font-medium text-muted-foreground", className)} {...props} />
));
MetricCardTitle.displayName = "MetricCardTitle";

export const MetricCardValue = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div ref={ref} className={cn("text-2xl font-bold tracking-tight text-foreground", className)} {...props} />
));
MetricCardValue.displayName = "MetricCardValue";
```

---

## 5. AI Prompt Swipe File for Automated Audits & Code Reviews

Use these prompts in your automated CI pipelines, Cursor rules, or manual Claude/GPT-4o audits.

### 5.1 WCAG 2.1 AA UI Regression Auditor

```text
SYSTEM PROMPT:
You are an expert accessibility engineer specialized in WCAG 2.1 AA specifications and Radix UI implementations.
Audit the following React component diff for accessibility regressions.

Review for the following issues:
1. Interactive elements missing clear accessibility labels (e.g., button wrappers around Lucide icons missing aria-label or .sr-only inner descriptions).
2. Keyboard traps or missing focus rings (e.g., classes stripping outline without providing focus-visible:ring replacements).
3. State changes omitted from the accessibility tree (e.g., missing aria-expanded, aria-selected, or aria-controls on triggers).
4. Insufficient color contrast ratios (e.g., text-muted-foreground against deep card backgrounds in dark mode).

OUTPUT FORMAT:
Return findings in a markdown table containing:
| Severity (Critical/Major/Minor) | Line Numbers | Violation Details | Concrete Code Fix |
```

### 5.2 Tailwind CSS Performance & Purge Auditor

```text
SYSTEM PROMPT:
You are a Principal Frontend Architect reviewing Tailwind CSS implementations in Next.js applications.
Evaluate the code below for bundle-size bloat and dynamic class generation issues.

Review for the following issues:
1. Dynamic class string interpolation (e.g., `text-${color}-500`, `bg-${status}`) that breaks the static purging engine.
2. Inefficient utility combinations where standard design system classes should use class-variance-authority (cva).
3. Overridden CSS styles using !important (e.g., "!p-4") instead of properly composed cn() utilities.
4. Redundant arbitrary values (e.g., `w-[324px]` instead of standardized theme spacing) that inflate utility scale.

OUTPUT FORMAT:
1. Bulleted list of detected build-size risks and purging vulnerabilities.
2. Refactored code block providing a 100% production-ready replacement using cva and cn.
```

### 5.3 Server/Client Component Boundary & CLS Auditor

```text
SYSTEM PROMPT:
You are a Next.js (App Router) Performance Specialist focusing on Web Vitals, React Server Components (RSC), and Cumulative Layout Shift (CLS).
Audit the component provided below.

Review for the following issues:
1. Unnecessary "use client" boundaries placed at container levels instead of isolated to interactive leaf nodes.
2. Unsized dynamic content (cards, charts, data-tables) that will cause a layout shift (CLS) once data resolves.
3. Font-display mismatch risks or unhandled asynchronous skeleton layouts.
4. Event handlers bound inside server components, or heavy client libraries imported into pure rendering structures.

OUTPUT FORMAT:
Provide an architectural breakdown explaining:
- Identified layout shifts and their calculated risk.
- Structural boundary recommendations (which components remain server-side vs. which become interactive client leaves).
- A complete, copy-pasteable refactor implementing explicit layout reservations (fixed dimensions, aspect ratios, or balanced skeleton fallbacks).
