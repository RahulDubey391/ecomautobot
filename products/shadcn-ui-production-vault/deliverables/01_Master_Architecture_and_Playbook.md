# Module 1: Design System Foundations & Component Token Architecture

This module establishes the foundational layer of the Enterprise Component Vault. Before building composite data tables, multi-step validation forms, or complex command systems, your application must resolve three core architectural challenges:

1. **Deterministic Theme Resolution:** Eliminating runtime flash of unstyled content (FOUC), supporting multi-tenant white-label overrides without bundle bloat, and decoupling raw color definitions from semantic usage tokens.
2. **Predictable Class Precedence:** Preventing style leakage and specificity collisions across deeply nested compound primitives using deterministic merge rules.
3. **Headless Primitive Inheritance:** Standardizing access keys, focus rings, ARIA role mapping, and event lifecycles across Radix UI foundations.

---

## 1. Enterprise CSS Variables & Semantic Token Architecture

The token pipeline uses an OKLCH-based color space. Unlike legacy HSL or RGB channels, OKLCH provides perceptual uniformity: adjusting luminance across different hues does not inadvertently alter perceptual contrast, ensuring WCAG 2.1 AA/AAA compliance across light, dark, and custom-branded tenant states.

### 1.1 Complete `globals.css` Token Mapping

Paste this file directly into `app/globals.css` (Next.js App Router) or `src/styles/globals.css` (Vite / Remix). It contains the base resets, semantic system definitions, and a production-grade multi-tenant enterprise override (`tenant-emerald`).

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    /* Base Neutral Surface & Typography */
    --background: 0.99 0 0; /* OKLCH: L, C, H */
    --foreground: 0.15 0.01 260;

    /* Card & Modal Containers */
    --card: 1 0 0;
    --card-foreground: 0.15 0.01 260;
    --popover: 1 0 0;
    --popover-foreground: 0.15 0.01 260;

    /* Core Brand Tokens */
    --primary: 0.45 0.22 264;
    --primary-foreground: 0.99 0 0;
    --primary-hover: 0.40 0.22 264;
    --primary-active: 0.35 0.22 264;

    /* Secondary / Subdued Actions */
    --secondary: 0.96 0.01 260;
    --secondary-foreground: 0.25 0.02 260;

    /* Muted Backgrounds & Form Placeholders */
    --muted: 0.95 0.01 260;
    --muted-foreground: 0.50 0.02 260;

    /* Interactive Accents (Hover states, table selections) */
    --accent: 0.94 0.02 260;
    --accent-foreground: 0.20 0.02 260;

    /* Destructive System States */
    --destructive: 0.58 0.22 27;
    --destructive-foreground: 0.99 0 0;

    /* Structural Borders & Controls */
    --border: 0.90 0.01 260;
    --input: 0.90 0.01 260;
    --ring: 0.45 0.22 264;

    /* Radii Scale */
    --radius: 0.5rem;

    /* Data Visualization / Metric Gauges */
    --chart-1: 0.60 0.18 250;
    --chart-2: 0.55 0.15 160;
    --chart-3: 0.75 0.16 75;
    --chart-4: 0.50 0.19 310;
    --chart-5: 0.65 0.20 25;
  }

  .dark {
    --background: 0.13 0.01 260;
    --foreground: 0.98 0.01 260;

    --card: 0.16 0.01 260;
    --card-foreground: 0.98 0.01 260;
    --popover: 0.16 0.01 260;
    --popover-foreground: 0.98 0.01 260;

    --primary: 0.62 0.20 264;
    --primary-foreground: 0.10 0.01 260;
    --primary-hover: 0.68 0.20 264;
    --primary-active: 0.72 0.20 264;

    --secondary: 0.22 0.02 260;
    --secondary-foreground: 0.90 0.01 260;

    --muted: 0.20 0.02 260;
    --muted-foreground: 0.65 0.02 260;

    --accent: 0.24 0.02 260;
    --accent-foreground: 0.98 0.01 260;

    --destructive: 0.45 0.18 25;
    --destructive-foreground: 0.98 0.01 260;

    --border: 0.26 0.02 260;
    --input: 0.26 0.02 260;
    --ring: 0.62 0.20 264;

    --chart-1: 0.65 0.18 250;
    --chart-2: 0.60 0.15 160;
    --chart-3: 0.80 0.16 75;
    --chart-4: 0.58 0.19 310;
    --chart-5: 0.70 0.20 25;
  }

  /* Enterprise Custom Tenant Override Example: Emerald Theme */
  [data-tenant="emerald"] {
    --primary: 0.52 0.17 155;
    --primary-foreground: 0.99 0 0;
    --primary-hover: 0.46 0.17 155;
    --primary-active: 0.40 0.17 155;
    --ring: 0.52 0.17 155;
  }

  [data-tenant="emerald"].dark {
    --primary: 0.65 0.15 155;
    --primary-foreground: 0.10 0.02 155;
    --primary-hover: 0.70 0.15 155;
    --primary-active: 0.75 0.15 155;
    --ring: 0.65 0.15 155;
  }
}

@layer base {
  * {
    @apply border-border;
  }
  body {
    @apply bg-background text-foreground antialiased selection:bg-primary/20 selection:text-primary;
    font-feature-settings: "cv02", "cv03", "cv04", "cv11";
  }
  /* Normalize scrollbar behavior across enterprise desktop contexts */
  ::-webkit-scrollbar {
    width: 8px;
    height: 8px;
  }
  ::-webkit-scrollbar-track {
    background: transparent;
  }
  ::-webkit-scrollbar-thumb {
    @apply bg-muted-foreground/20 rounded-full hover:bg-muted-foreground/40 transition-colors;
  }
}
```

---

## 2. Production `tailwind.config.ts`

This configuration maps CSS variables directly into utility classes while exposing precise color opacity controls via the Tailwind CSS `oklch(var(--token) / <alpha-value>)` pipeline.

```typescript
import type { Config } from "tailwindcss";
import plugin from "tailwindcss/plugin";

const config = {
  darkMode: ["class"],
  content: [
    "./pages/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./app/**/*.{ts,tsx}",
    "./src/**/*.{ts,tsx}",
  ],
  prefix: "",
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
        border: "oklch(var(--border) / <alpha-value>)",
        input: "oklch(var(--input) / <alpha-value>)",
        ring: "oklch(var(--ring) / <alpha-value>)",
        background: "oklch(var(--background) / <alpha-value>)",
        foreground: "oklch(var(--foreground) / <alpha-value>)",
        primary: {
          DEFAULT: "oklch(var(--primary) / <alpha-value>)",
          foreground: "oklch(var(--primary-foreground) / <alpha-value>)",
          hover: "oklch(var(--primary-hover) / <alpha-value>)",
          active: "oklch(var(--primary-active) / <alpha-value>)",
        },
        secondary: {
          DEFAULT: "oklch(var(--secondary) / <alpha-value>)",
          foreground: "oklch(var(--secondary-foreground) / <alpha-value>)",
        },
        destructive: {
          DEFAULT: "oklch(var(--destructive) / <alpha-value>)",
          foreground: "oklch(var(--destructive-foreground) / <alpha-value>)",
        },
        muted: {
          DEFAULT: "oklch(var(--muted) / <alpha-value>)",
          foreground: "oklch(var(--muted-foreground) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "oklch(var(--accent) / <alpha-value>)",
          foreground: "oklch(var(--accent-foreground) / <alpha-value>)",
        },
        popover: {
          DEFAULT: "oklch(var(--popover) / <alpha-value>)",
          foreground: "oklch(var(--popover-foreground) / <alpha-value>)",
        },
        card: {
          DEFAULT: "oklch(var(--card) / <alpha-value>)",
          foreground: "oklch(var(--card-foreground) / <alpha-value>)",
        },
        chart: {
          1: "oklch(var(--chart-1) / <alpha-value>)",
          2: "oklch(var(--chart-2) / <alpha-value>)",
          3: "oklch(var(--chart-3) / <alpha-value>)",
          4: "oklch(var(--chart-4) / <alpha-value>)",
          5: "oklch(var(--chart-5) / <alpha-value>)",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "-apple-system", "sans-serif"],
        mono: ["var(--font-mono)", "monospace"],
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        "collapsible-down": {
          from: { height: "0" },
          to: { height: "var(--radix-collapsible-content-height)" },
        },
        "collapsible-up": {
          from: { height: "var(--radix-collapsible-content-height)" },
          to: { height: "0" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "collapsible-down": "collapsible-down 0.2s ease-out",
        "collapsible-up": "collapsible-up 0.2s ease-out",
      },
    },
  },
  plugins: [
    require("tailwindcss-animate"),
    plugin(({ addUtilities }) => {
      addUtilities({
        ".elevation-ring": {
          boxShadow:
            "0 0 0 1px oklch(var(--border) / 0.8), 0 1px 2px -1px oklch(var(--foreground) / 0.1), 0 2px 4px 0 oklch(var(--foreground) / 0.05)",
        },
        ".elevation-popover": {
          boxShadow:
            "0 0 0 1px oklch(var(--border) / 0.8), 0 4px 6px -2px oklch(var(--foreground) / 0.05), 0 10px 15px -3px oklch(var(--foreground) / 0.1)",
        },
      });
    }),
  ],
} satisfies Config;

export default config;
```

---

## 3. High-Performance Utility Infrastructure (`lib/utils.ts`)

A production mistake in compound components is class collisions resolving incorrectly (e.g., `p-2` overriding `px-4 py-6` unpredictable depending on bundle order). We enforce strict deterministic merging by pairing `clsx` with a configured `tailwind-merge` instance.

```typescript
import { type ClassValue, clsx } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * Configure tailwind-merge to recognize custom CSS variable semantic class names
 * preventing incorrect drops of semantic classes during merging.
 */
const customTwMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: ["xs", "sm", "base", "lg", "xl", "2xl", "3xl"] }],
      elevation: ["elevation-ring", "elevation-popover"],
    },
  },
});

/**
 * Merges arbitrary class names with full resolution for conflicting Tailwind classes.
 * 
 * @param inputs - Array of class values, objects, or arrays compatible with clsx.
 * @returns Optimized, deterministic string of merged classes.
 */
export function cn(...inputs: ClassValue[]): string {
  return customTwMerge(clsx(inputs));
}

/**
 * Formats a tenant identifier safely for DOM injection without CSS injection vulnerabilities.
 */
export function sanitizeTenantAttribute(tenantId: string): string {
  return tenantId.toLowerCase().replace(/[^a-z0-9_-]/g, "");
}
```

---

## 4. Multi-Tenant Theme Provider Implementation

Enterprise SaaS applications require dynamic run-time switching between dark/light modes and dynamic tenant configurations (e.g., switching primary brands on subdomains or user workspaces).

### 4.1 Implementation: `components/theme-provider.tsx`

```tsx
"use client";

import * as React from "react";
import { createContext, useContext, useEffect, useState, useMemo } from "react";

type Theme = "dark" | "light" | "system";

type ThemeProviderProps = {
  children: React.ReactNode;
  defaultTheme?: Theme;
  storageKey?: string;
  attribute?: string;
  enableSystem?: boolean;
  tenantId?: string;
};

type ThemeProviderState = {
  theme: Theme;
  resolvedTheme: "dark" | "light";
  tenantId: string | null;
  setTheme: (theme: Theme) => void;
  setTenantId: (tenant: string) => void;
};

const initialState: ThemeProviderState = {
  theme: "system",
  resolvedTheme: "light",
  tenantId: null,
  setTheme: () => null,
  setTenantId: () => null,
};

const ThemeProviderContext = createContext<ThemeProviderState>(initialState);

export function ThemeProvider({
  children,
  defaultTheme = "system",
  storageKey = "ui-theme-mode",
  attribute = "class",
  enableSystem = true,
  tenantId: initialTenantId,
}: ThemeProviderProps) {
  const [theme, setThemeState] = useState<Theme>(() => {
    if (typeof window === "undefined") return defaultTheme;
    try {
      return (localStorage.getItem(storageKey) as Theme) || defaultTheme;
    } catch {
      return defaultTheme;
    }
  });

  const [tenant, setTenant] = useState<string | null>(initialTenantId ?? null);
  const [resolvedTheme, setResolvedTheme] = useState<"dark" | "light">("light");

  useEffect(() => {
    const root = window.document.documentElement;
    root.classList.remove("light", "dark");

    let computedTheme: "dark" | "light" = "light";

    if (theme === "system" && enableSystem) {
      const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      computedTheme = systemDark ? "dark" : "light";
    } else {
      computedTheme = theme === "dark" ? "dark" : "light";
    }

    root.classList.add(computedTheme);
    setResolvedTheme(computedTheme);

    // Synchronize multi-tenant attribute
    if (tenant) {
      root.setAttribute("data-tenant", tenant);
    } else {
      root.removeAttribute("data-tenant");
    }
  }, [theme, tenant, enableSystem]);

  useEffect(() => {
    if (theme !== "system" || !enableSystem) return;

    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = (e: MediaQueryListEvent) => {
      const root = window.document.documentElement;
      root.classList.remove("light", "dark");
      const nextTheme = e.matches ? "dark" : "light";
      root.classList.add(nextTheme);
      setResolvedTheme(nextTheme);
    };

    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, [theme, enableSystem]);

  const value = useMemo(
    () => ({
      theme,
      resolvedTheme,
      tenantId: tenant,
      setTheme: (newTheme: Theme) => {
        try {
          localStorage.setItem(storageKey, newTheme);
        } catch {}
        setThemeState(newTheme);
      },
      setTenantId: (nextTenant: string) => {
        setTenant(nextTenant);
      },
    }),
    [theme, resolvedTheme, tenant, storageKey]
  );

  return (
    <ThemeProviderContext.Provider value={value}>
      {children}
    </ThemeProviderContext.Provider>
  );
}

export const useTheme = (): ThemeProviderState => {
  const context = useContext(ThemeProviderContext);
  if (!context) {
    throw new Error("useTheme must be used within an enterprise ThemeProvider context.");
  }
  return context;
};
```

---

## 5. Radical Component Architecture: Polymorphic Primitive

To construct flexible compound layouts, components must implement Radix UI's Slot primitive (polymorphism via the `asChild` pattern). This prevents DOM invalidation errors (e.g., rendering a `<button>` inside an `<a>` tag) while maintaining access key delegation, focus traps, and styling.

### 5.1 Gold Standard Button: `components/ui/button.tsx`

This enterprise Button pattern demonstrates:
- Polymorphism via `@radix-ui/react-slot`.
- Comprehensive size, intent, and layout variants via `class-variance-authority`.
- Dedicated spinner slot with accessible screen-reader live updates.
- Focus-visible ring consistency adhering to Section 508.

```tsx
import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-colors outline-none select-none disabled:pointer-events-none disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background active:scale-[0.98]",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm",
        destructive:
          "bg-destructive text-destructive-foreground hover:bg-destructive/90 shadow-sm",
        outline:
          "border border-input bg-background hover:bg-accent hover:text-accent-foreground shadow-sm",
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2",
        xs: "h-7 rounded px-2 text-xs",
        sm: "h-8 rounded-md px-3 text-xs",
        lg: "h-11 rounded-md px-8 text-base",
        icon: "h-9 w-9",
        "icon-sm": "h-7 w-7",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
  loadingText?: string;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant,
      size,
      asChild = false,
      loading = false,
      loadingText,
      disabled,
      children,
      ...props
    },
    ref
  ) => {
    // If asChild is true, we delegate rendering entirely to the child element
    if (asChild) {
      return (
        <Slot
          className={cn(buttonVariants({ variant, size, className }))}
          ref={ref}
          {...props}
        >
          {children}
        </Slot>
      );
    }

    return (
      <button
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        disabled={disabled || loading}
        aria-busy={loading}
        aria-disabled={disabled || loading}
        {...props}
      >
        {loading ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
            <span>{loadingText || children}</span>
            <span className="sr-only">Loading</span>
          </>
        ) : (
          children
        )}
      </button>
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
```

---

## 6. Radix UI Foundation Integration Blueprint

When composing custom UI with Radix Primitives (`@radix-ui/react-*`), map standard interactions directly to token architecture:

| UI Layer | Radix Primitive | Accessibility Contract | Enterprise Token Implementation |
| :--- | :--- | :--- | :--- |
| **Focus Rings** | All Primitives | WAI-ARIA Focus Visible | `focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background` |
| **Overlays** | `@radix-ui/react-dialog` | Modal inert trap, dynamic scroll lock | `bg-background/80 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out` |
| **Popovers** | `@radix-ui/react-popover` | Viewport collision detection, escape dismiss | `z-50 rounded-md border bg-popover text-popover-foreground elevation-popover outline-none` |
| **Menus** | `@radix-ui/react-dropdown-menu`| Roving tab index, typeahead search | `bg-popover text-popover-foreground min-w-[8rem] rounded-md border p-1 shadow-md` |
| **Data Pickers** | Custom Compositions | ARIA Grid, Arrow navigation | `aria-selected:bg-accent aria-selected:text-accent-foreground` |

---

## 7. Enterprise Token Migration Checklist

Follow this linear checklist when migrating existing enterprise software, internal admin portals, or design agency applications to this token foundation:

- [ ] **Step 1: Color Space Decoupling**
  - Verify every hex (`#FFFFFF`) or pure functional HSL token in your codebase is replaced with semantic OKLCH CSS variables.
  - Test colors with the WCAG 2.1 Contrast Checker to guarantee all text tokens meet minimum 4.5:1 contrast against their respective canvas/card background.

- [ ] **Step 2: Elimination of Arbitrary Tailwind Directives**
  - Search project for patterns like `bg-[#1a1a1a]` or `text-[#f3f4f6]`.
  - Replace instances with semantic utility classes: `bg-background`, `text-foreground`, `bg-muted`.

- [ ] **Step 3: Component Slot Auditing**
  - Review custom wrappers to ensure components accepting interactive elements implement the Radix UI `Slot` pattern via `asChild`.
  - Eliminate nested interactive tags (`<button><a /></button>`) to guarantee DOM compliance.

- [ ] **Step 4: Screen Reader and State Testing**
  - Verify interactive components (Buttons, Toggles, Tabs) expose their loading, opened, or disabled state via standard ARIA attributes (`aria-busy`, `aria-expanded`, `aria-disabled`).
  - Validate state updates using keyboard-only navigation (`Tab`, `Shift+Tab`, `Space`, `Enter`).

- [ ] **Step 5: Tenant Context Integrity**
  - Apply `data-tenant="<tenantId>"` at the root level and verify all components inherit client brand variables dynamically without client-side bundle re-evaluation.
