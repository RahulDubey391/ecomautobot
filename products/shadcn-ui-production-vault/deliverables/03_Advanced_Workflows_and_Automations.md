# Module 3: Enterprise Dashboard Shells, Multi-Step Flows & Micro-Interactions

Enterprise applications live and die by their application shells, workflow friction, and perceived latency. When an interface drops frames during sidebar collapses, loses form state when a user navigates backward through a multi-step sequence, or presents a laggy command palette, users perceive the system as unreliable. 

This module provides production-grade architectural implementations for the structural pillars of complex B2B applications:
1. Zero-CLS (Cumulative Layout Shift) collapsible sidebar shells with cookie persistence.
2. Type-safe, keyboard-navigable multi-step form engines with schema-isolated validation.
3. Context-aware global Command (Cmd+K) architectures.
4. GPU-accelerated micro-interactions engineered with Framer Motion and Tailwind CSS.

---

## 1. Enterprise Dashboard Shell Architecture

A production-grade dashboard shell must satisfy three non-negotiable requirements:
* **Zero-flicker SSR hydration:** Sidebar state (expanded/collapsed) must resolve on the server via cookies, completely preventing layout shift during initial paint.
* **Full keyboard traversal:** The drawer, rail, and submenu trees must be accessible via standard ARIA navigation patterns.
* **Dynamic Breadcrumb Context:** Page trees must automatically reconcile route segments with resource titles without manual hardcoding on every route.

```
┌────────────────────────────────────────────────────────────────────────┐
│ AppHeader: [OrgSwitcher] [Breadcrumbs] ── [Cmd+K Search] [Notifications] [User] │
├──────────────┬─────────────────────────────────────────────────────────┤
│ Sidebar      │ Main Content Viewport                                   │
│ [Workspace]  │ ┌─────────────────────────────────────────────────────┐ │
│ ├─ NavGroup  │ │ Route Viewport                                      │ │
│ │  ├─ Item   │ │ (Auto-injected margin offset via CSS Variables)     │ │
│ │  └─ SubTree│ │                                                     │ │
│ ├─ NavGroup  │ │                                                     │ │
│ └─ FooterRail│ └─────────────────────────────────────────────────────┘ │
└──────────────┴─────────────────────────────────────────────────────────┘
```

### 1.1 Shell State & Context Implementation

Create `sidebar-context.tsx` to handle responsive state, keyboard shortcuts (`Ctrl/Cmd + B`), and cookie synchronization for Next.js App Router server components.

```tsx
"use client";

import * as React from "react";

const SIDEBAR_COOKIE_NAME = "sidebar_state";
const SIDEBAR_COOKIE_MAX_AGE = 60 * 60 * 24 * 7; // 7 days
const SIDEBAR_KEYBOARD_SHORTCUT = "b";

interface SidebarContextValue {
  isOpen: boolean;
  isMobileOpen: boolean;
  toggleSidebar: () => void;
  setIsOpen: (value: boolean | ((prev: boolean) => boolean)) => void;
  toggleMobileSidebar: () => void;
  setMobileOpen: (value: boolean) => void;
  isCollapsed: boolean;
}

const SidebarContext = React.createContext<SidebarContextValue | null>(null);

export function useSidebar(): SidebarContextValue {
  const context = React.useContext(SidebarContext);
  if (!context) {
    throw new Error("useSidebar must be used within a <SidebarProvider />");
  }
  return context;
}

interface SidebarProviderProps {
  children: React.ReactNode;
  defaultOpen?: boolean;
}

export function SidebarProvider({
  children,
  defaultOpen = true,
}: SidebarProviderProps) {
  const [isOpen, _setIsOpen] = React.useState<boolean>(defaultOpen);
  const [isMobileOpen, setMobileOpen] = React.useState<boolean>(false);

  const setIsOpen = React.useCallback(
    (value: boolean | ((prev: boolean) => boolean)) => {
      _setIsOpen((prev) => {
        const next = typeof value === "function" ? value(prev) : value;
        document.cookie = `${SIDEBAR_COOKIE_NAME}=${next}; path=/; max-age=${SIDEBAR_COOKIE_MAX_AGE}; SameSite=Lax`;
        return next;
      });
    },
    []
  );

  const toggleSidebar = React.useCallback(() => {
    setIsOpen((prev) => !prev);
  }, [setIsOpen]);

  const toggleMobileSidebar = React.useCallback(() => {
    setMobileOpen((prev) => !prev);
  }, []);

  React.useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        event.key === SIDEBAR_KEYBOARD_SHORTCUT &&
        (event.metaKey || event.ctrlKey)
      ) {
        event.preventDefault();
        toggleSidebar();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [toggleSidebar]);

  const contextValue = React.useMemo<SidebarContextValue>(
    () => ({
      isOpen,
      isMobileOpen,
      toggleSidebar,
      setIsOpen,
      toggleMobileSidebar,
      setMobileOpen,
      isCollapsed: !isOpen,
    }),
    [isOpen, isMobileOpen, toggleSidebar, setIsOpen, toggleMobileSidebar]
  );

  return (
    <SidebarContext.Provider value={contextValue}>
      <div
        style={
          {
            "--sidebar-width": "16rem",
            "--sidebar-width-collapsed": "4rem",
            "--sidebar-transition-duration": "200ms",
          } as React.CSSProperties
        }
        className="relative flex min-h-screen w-full bg-background"
      >
        {children}
      </div>
    </SidebarContext.Provider>
  );
}
```

### 1.2 Layout Core: Zero-CLS Sidebar Implementation

This component incorporates dynamic transition classes, tooltips during collapsed mode, sub-tree accordions, and accessibility tags.

```tsx
"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronDown, LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { useSidebar } from "./sidebar-context";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export interface NavItem {
  title: string;
  href: string;
  icon: LucideIcon;
  badge?: string | number;
  children?: { title: string; href: string }[];
}

interface AppSidebarProps {
  navigation: { group: string; items: NavItem[] }[];
}

export function AppSidebar({ navigation }: AppSidebarProps) {
  const { isOpen, isCollapsed } = useSidebar();
  const pathname = usePathname();

  return (
    <TooltipProvider delayDuration={0}>
      <aside
        aria-label="Application Sidebar"
        data-state={isOpen ? "expanded" : "collapsed"}
        className={cn(
          "sticky top-0 z-30 hidden h-screen border-r border-border bg-card transition-[width] ease-in-out md:flex md:flex-col",
          isOpen ? "w-[var(--sidebar-width)]" : "w-[var(--sidebar-width-collapsed)]"
        )}
      >
        <div className="flex h-14 items-center border-b border-border px-4">
          <Link
            href="/dashboard"
            className="flex items-center gap-2 overflow-hidden font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground font-bold text-xs">
              PV
            </div>
            {!isCollapsed && (
              <span className="truncate text-sm tracking-tight text-foreground">
                Vault Platform
              </span>
            )}
          </Link>
        </div>

        <nav className="flex-1 space-y-4 overflow-y-auto overflow-x-hidden p-2 scrollbar-thin">
          {navigation.map((section, idx) => (
            <div key={idx} className="space-y-1">
              {!isCollapsed && (
                <h4 className="px-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground/70">
                  {section.group}
                </h4>
              )}
              <div className="space-y-0.5">
                {section.items.map((item) => {
                  const isActive =
                    pathname === item.href ||
                    pathname.startsWith(`${item.href}/`);
                  const hasChildren = Boolean(item.children?.length);

                  if (isCollapsed) {
                    return (
                      <Tooltip key={item.href}>
                        <TooltipTrigger asChild>
                          <Link
                            href={item.href}
                            className={cn(
                              "flex h-9 w-9 items-center justify-center rounded-md mx-auto transition-colors",
                              isActive
                                ? "bg-primary text-primary-foreground shadow-sm"
                                : "text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                            )}
                          >
                            <item.icon className="h-4 w-4" />
                            <span className="sr-only">{item.title}</span>
                          </Link>
                        </TooltipTrigger>
                        <TooltipContent side="right" className="font-medium">
                          {item.title}
                          {item.badge && (
                            <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-[10px]">
                              {item.badge}
                            </span>
                          )}
                        </TooltipContent>
                      </Tooltip>
                    );
                  }

                  if (hasChildren) {
                    return (
                      <SidebarCollapsibleGroup
                        key={item.href}
                        item={item}
                        isActive={isActive}
                        pathname={pathname}
                      />
                    );
                  }

                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      className={cn(
                        "group flex h-9 items-center justify-between rounded-md px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        isActive
                          ? "bg-secondary text-secondary-foreground font-semibold"
                          : "text-muted-foreground hover:bg-muted hover:text-foreground"
                      )}
                    >
                      <div className="flex items-center gap-3 truncate">
                        <item.icon className="h-4 w-4 shrink-0" />
                        <span className="truncate">{item.title}</span>
                      </div>
                      {item.badge && (
                        <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary font-mono">
                          {item.badge}
                        </span>
                      )}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>
      </aside>
    </TooltipProvider>
  );
}

function SidebarCollapsibleGroup({
  item,
  isActive,
  pathname,
}: {
  item: NavItem;
  isActive: boolean;
  pathname: string;
}) {
  const [open, setOpen] = React.useState(isActive);

  return (
    <div className="space-y-1">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className={cn(
          "flex w-full h-9 items-center justify-between rounded-md px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          isActive
            ? "text-foreground"
            : "text-muted-foreground hover:bg-muted hover:text-foreground"
        )}
      >
        <div className="flex items-center gap-3 truncate">
          <item.icon className="h-4 w-4 shrink-0" />
          <span className="truncate">{item.title}</span>
        </div>
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 transition-transform duration-200",
            open && "rotate-180"
          )}
        />
      </button>
      {open && (
        <div className="ml-4 space-y-0.5 border-l border-border pl-3">
          {item.children?.map((child) => {
            const isChildActive = pathname === child.href;
            return (
              <Link
                key={child.href}
                href={child.href}
                className={cn(
                  "block h-8 rounded-md px-2 text-sm leading-8 transition-colors truncate focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  isChildActive
                    ? "font-semibold text-primary"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                {child.title}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
```

### 1.3 Server-Side Layout Bootstrap

To eliminate Cumulative Layout Shift (CLS), read the cookie on the server and pass it into the `defaultOpen` prop.

```tsx
// app/(dashboard)/layout.tsx
import { cookies } from "next/headers";
import { SidebarProvider } from "@/components/dashboard/sidebar-context";
import { AppSidebar } from "@/components/dashboard/app-sidebar";
import { LayoutDashboard, Settings, ShieldAlert, Users, Database } from "lucide-react";

const NAVIGATION_CONFIG = [
  {
    group: "Platform",
    items: [
      { title: "Overview", href: "/dashboard", icon: LayoutDashboard },
      {
        title: "Access Control",
        href: "/dashboard/access",
        icon: Users,
        children: [
          { title: "Roles & Policies", href: "/dashboard/access/roles" },
          { title: "Service Accounts", href: "/dashboard/access/service-accounts" },
        ],
      },
      { title: "Databases", href: "/dashboard/databases", icon: Database, badge: "3" },
    ],
  },
  {
    group: "Governance",
    items: [
      { title: "Audit Trail", href: "/dashboard/audit", icon: ShieldAlert },
      { title: "Settings", href: "/dashboard/settings", icon: Settings },
    ],
  },
];

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const cookieStore = await cookies();
  const rawSidebarState = cookieStore.get("sidebar_state")?.value;
  const defaultOpen = rawSidebarState !== undefined ? rawSidebarState === "true" : true;

  return (
    <SidebarProvider defaultOpen={defaultOpen}>
      <AppSidebar navigation={NAVIGATION_CONFIG} />
      <div className="flex flex-1 flex-col overflow-hidden">
        <main className="flex-1 overflow-y-auto bg-muted/30 p-6 md:p-8">
          <div className="mx-auto max-w-7xl">{children}</div>
        </main>
      </div>
    </SidebarProvider>
  );
}
```

---

## 2. Keyboard-Navigated Multi-Step Wizard Engine

Typical multi-step form tutorials fall apart in enterprise scenarios because they either:
1. Validate the *entire* schema upfront, breaking the UI with premature errors on subsequent tabs.
2. Store intermediate values in fragmented, isolated component states, leading to dropped changes on back-navigation.
3. Lack programmatic keyboard handling, trapping non-pointer users.

The pattern below utilizes a compound **Step Isolated Validation** architecture. Each step validates against an isolated sub-schema extracted from a root compound schema via Zod discards, while the parent React Hook Form state persists in memory.

```
┌────────────────────────────────────────────────────────┐
│ Wizard Context: Machine State [ActiveStep: 2 of 4]      │
├────────────────────────────────────────────────────────┤
│ Step Graph: [1. Domain] ➔ [2. Networking] ➔ [3. Auth]  │
├────────────────────────────────────────────────────────┤
│ Step Sub-Schema Validation:                            │
│  - Executes trigger(['subnets', 'natGateway'])         │
│  - Rejects forward progression on schema violations    │
│  - Retains backward historical state without mutations │
└────────────────────────────────────────────────────────┘
```

### 2.1 Multi-Step Wizard Schemas & Types

```typescript
// wizard-schema.ts
import { z } from "zod";

export const stepOneSchema = z.object({
  clusterName: z
    .string()
    .min(3, "Cluster name must be at least 3 characters")
    .max(32, "Cluster name cannot exceed 32 characters")
    .regex(/^[a-z0-9-]+$/, "Only lowercase alphanumeric characters and hyphens allowed"),
  region: z.enum(["us-east-1", "us-west-2", "eu-central-1"], {
    errorMap: () => ({ message: "Select a valid target deployment region" }),
  }),
  environment: z.enum(["development", "staging", "production"]),
});

export const stepTwoSchema = z.object({
  vpcCidr: z
    .string()
    .regex(
      /^([0-9]{1,3}\.){3}[0-9]{1,3}\/([0-9]|[1-2][0-9]|3[0-2])$/,
      "Must be a valid IPv4 CIDR block (e.g., 10.0.0.0/16)"
    ),
  enableNatGateway: z.boolean().default(true),
  subnets: z
    .array(
      z.object({
        id: z.string(),
        cidr: z.string(),
        zone: z.string(),
      })
    )
    .min(2, "At least two subnets are required for high availability"),
});

export const stepThreeSchema = z.object({
  adminEmail: z.string().email("A valid administrative email is required"),
  backupRetentionDays: z.coerce
    .number()
    .int()
    .min(1, "Minimum retention is 1 day")
    .max(90, "Maximum retention is 90 days"),
  enableDeletionProtection: z.boolean().default(true),
});

export const enterpriseDeploymentSchema = z.object({
  stepOne: stepOneSchema,
  stepTwo: stepTwoSchema,
  stepThree: stepThreeSchema,
});

export type EnterpriseDeploymentValues = z.infer<typeof enterpriseDeploymentSchema>;
```

### 2.2 Complete Wizard Controller Implementation

```tsx
"use client";

import * as React from "react";
import { useForm, FormProvider, useFormContext } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { motion, AnimatePresence } from "framer-motion";
import {
  enterpriseDeploymentSchema,
  EnterpriseDeploymentValues,
} from "./wizard-schema";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Check, ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

const STEPS = [
  { id: "stepOne", title: "Cluster Specs", fields: ["stepOne.clusterName", "stepOne.region", "stepOne.environment"] as const },
  { id: "stepTwo", title: "Networking", fields: ["stepTwo.vpcCidr", "stepTwo.enableNatGateway", "stepTwo.subnets"] as const },
  { id: "stepThree", title: "Governance", fields: ["stepThree.adminEmail", "stepThree.backupRetentionDays", "stepThree.enableDeletionProtection"] as const },
] as const;

export function EnterpriseWizardForm() {
  const [currentStep, setCurrentStep] = React.useState<number>(0);
  const [direction, setDirection] = React.useState<number>(1);
  const [isSubmitting, setIsSubmitting] = React.useState<boolean>(false);

  const methods = useForm<EnterpriseDeploymentValues>({
    resolver: zodResolver(enterpriseDeploymentSchema),
    mode: "onTouched",
    defaultValues: {
      stepOne: {
        clusterName: "",
        region: "us-east-1",
        environment: "development",
      },
      stepTwo: {
        vpcCidr: "10.0.0.0/16",
        enableNatGateway: true,
        subnets: [
          { id: "sub-1", cidr: "10.0.1.0/24", zone: "us-east-1a" },
          { id: "sub-2", cidr: "10.0.2.0/24", zone: "us-east-1b" },
        ],
      },
      stepThree: {
        adminEmail: "",
        backupRetentionDays: 30,
        enableDeletionProtection: true,
      },
    },
  });

  const { trigger, handleSubmit } = methods;

  const navigateStep = async (nextIndex: number) => {
    if (nextIndex > currentStep) {
      // Validate current step fields before progressing forward
      const currentFields = STEPS[currentStep].fields;
      const isValid = await trigger(currentFields as unknown as (keyof EnterpriseDeploymentValues)[]);
      if (!isValid) return;
    }

    setDirection(nextIndex > currentStep ? 1 : -1);
    setCurrentStep(nextIndex);
  };

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.altKey && event.key === "ArrowRight") {
      event.preventDefault();
      if (currentStep < STEPS.length - 1) {
        navigateStep(currentStep + 1);
      }
    }
    if (event.altKey && event.key === "ArrowLeft") {
      event.preventDefault();
      if (currentStep > 0) {
        navigateStep(currentStep - 1);
      }
    }
  };

  const onSubmit = async (values: EnterpriseDeploymentValues) => {
    setIsSubmitting(true);
    try {
      // Process production dispatch payload
      await new Promise((resolve) => setTimeout(resolve, 2000));
      console.info("Deployment Configuration Dispatched Successfully:", values);
    } catch (error) {
      console.error("Payload transmission failed:", error);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <FormProvider {...methods}>
      <div
        onKeyDown={handleKeyDown}
        className="mx-auto w-full max-w-2xl rounded-xl border border-border bg-card p-6 shadow-sm sm:p-8"
      >
        {/* Step Indicator Header */}
        <nav aria-label="Wizard Steps" className="mb-8">
          <ol className="flex items-center justify-between">
            {STEPS.map((step, idx) => {
              const isCompleted = idx < currentStep;
              const isCurrent = idx === currentStep;

              return (
                <li key={step.id} className="relative flex flex-1 flex-col items-center">
                  <button
                    type="button"
                    onClick={() => navigateStep(idx)}
                    disabled={idx > currentStep}
                    aria-current={isCurrent ? "step" : undefined}
                    className="flex flex-col items-center group focus:outline-none"
                  >
                    <div
                      className={cn(
                        "flex h-9 w-9 items-center justify-center rounded-full border-2 text-xs font-semibold transition-colors duration-200",
                        isCompleted
                          ? "border-primary bg-primary text-primary-foreground"
                          : isCurrent
                          ? "border-primary bg-background text-primary ring-4 ring-primary/10"
                          : "border-muted bg-muted/40 text-muted-foreground group-hover:border-border"
                      )}
                    >
                      {isCompleted ? <Check className="h-4 w-4 stroke-[3]" /> : idx + 1}
                    </div>
                    <span
                      className={cn(
                        "mt-2 text-xs font-medium transition-colors",
                        isCurrent
                          ? "text-foreground font-semibold"
                          : "text-muted-foreground"
                      )}
                    >
                      {step.title}
                    </span>
                  </button>
                  {idx !== STEPS.length - 1 && (
                    <div
                      aria-hidden="true"
                      className={cn(
                        "absolute left-1/2 top-4 -z-10 h-[2px] w-full -translate-y-1/2",
                        idx < currentStep ? "bg-primary" : "bg-muted"
                      )}
                    />
                  )}
                </li>
              );
            })}
          </ol>
        </nav>

        {/* Form Body with Smooth Height Adaptations */}
        <form onSubmit={handleSubmit(onSubmit)}>
          <div className="relative overflow-hidden min-h-[320px]">
            <AnimatePresence mode="popLayout" custom={direction}>
              <motion.div
                key={currentStep}
                custom={direction}
                initial={{ opacity: 0, x: direction > 0 ? 40 : -40 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: direction > 0 ? -40 : 40 }}
                transition={{ duration: 0.2, ease: "easeInOut" }}
                className="space-y-4"
              >
                {currentStep === 0 && <StepOneView />}
                {currentStep === 1 && <StepTwoView />}
                {currentStep === 2 && <StepThreeView />}
              </motion.div>
            </AnimatePresence>
          </div>

          {/* Navigation Controls */}
          <div className="mt-8 flex items-center justify-between border-t border-border pt-4">
            <Button
              type="button"
              variant="outline"
              disabled={currentStep === 0 || isSubmitting}
              onClick={() => navigateStep(currentStep - 1)}
              className="gap-2"
            >
              <ChevronLeft className="h-4 w-4" /> Previous
            </Button>

            {currentStep < STEPS.length - 1 ? (
              <Button
                type="button"
                onClick={() => navigateStep(currentStep + 1)}
                className="gap-2"
              >
                Next <ChevronRight className="h-4 w-4" />
              </Button>
            ) : (
              <Button type="submit" disabled={isSubmitting} className="min-w-[120px]">
                {isSubmitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  "Deploy Cluster"
                )}
              </Button>
            )}
          </div>
        </form>
      </div>
    </FormProvider>
  );
}

function StepOneView() {
  const { register, formState: { errors }, setValue, watch } = useFormContext<EnterpriseDeploymentValues>();
  const region = watch("stepOne.region");
  const environment = watch("stepOne.environment");

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="clusterName">Cluster Identifier</Label>
        <Input
          id="clusterName"
          placeholder="production-east-k8s"
          {...register("stepOne.clusterName")}
          aria-invalid={Boolean(errors.stepOne?.clusterName)}
        />
        {errors.stepOne?.clusterName && (
          <p className="text-xs font-medium text-destructive">
            {errors.stepOne.clusterName.message}
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label>Deployment Region</Label>
          <Select
            value={region}
            onValueChange={(val: "us-east-1" | "us-west-2" | "eu-central-1") =>
              setValue("stepOne.region", val, { shouldValidate: true })
            }
          >
            <SelectTrigger>
              <SelectValue placeholder="Select Region" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="us-east-1">us-east-1 (N. Virginia)</SelectItem>
              <SelectItem value="us-west-2">us-west-2 (Oregon)</SelectItem>
              <SelectItem value="eu-central-1">eu-central-1 (Frankfurt)</SelectItem>
            </SelectContent>
          </Select>
          {errors.stepOne?.region && (
            <p className="text-xs font-medium text-destructive">
              {errors.stepOne.region.message}
            </p>
          )}
        </div>

        <div className="space-y-2">
          <Label>Environment Tier</Label>
          <Select
            value={environment}
            onValueChange={(val: "development" | "staging" | "production") =>
              setValue("stepOne.environment", val, { shouldValidate: true })
            }
          >
            <SelectTrigger>
              <SelectValue placeholder="Select Tier" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="development">Development</SelectItem>
              <SelectItem value="staging">Staging</SelectItem>
              <SelectItem value="production">Production</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>
    </div>
  );
}

function StepTwoView() {
  const { register, formState: { errors }, setValue, watch } = useFormContext<EnterpriseDeploymentValues>();
  const enableNatGateway = watch("stepTwo.enableNatGateway");

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <
