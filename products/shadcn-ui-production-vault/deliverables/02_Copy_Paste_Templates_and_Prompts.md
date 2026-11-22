# Module 2: 60+ Production UI Components & TanStack Data Table Patterns

This deliverable provides complete, drop-in TypeScript and Tailwind CSS source code for enterprise-grade data management primitives. Every component adheres to WAI-ARIA standards, leverages TanStack Table v8, TanStack Virtual v3, and the standard Radix UI / Shadcn UI component primitive interface.

---

## 1. Environment & Package Prerequisites

Run the following command to ensure all required peer dependencies and primitives are present in your project:

```bash
npm install @tanstack/react-table @tanstack/react-virtual lucide-react class-variance-authority clsx tailwind-merge cmdk @radix-ui/react-dialog @radix-ui/react-popover @radix-ui/react-checkbox @radix-ui/react-dropdown-menu @radix-ui/react-tabs @radix-ui/react-slot
```

Verify your utility file located at `@/lib/utils.ts`:

```typescript
import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
```

---

## 2. Enterprise Virtualized Data Table with Inline Editing & Faceted Filters

This production implementation solves two critical performance bottlenecks in enterprise applications: rendering datasets exceeding 10,000 rows without DOM degradation, and providing isolated, accessible, cell-level state updates without triggering whole-table re-renders.

### 2.1 Type Definitions & Column Schema (`table-types.ts`)

```typescript
export type TransactionStatus = "completed" | "pending" | "processing" | "failed"
export type TransactionTier = "enterprise" | "growth" | "starter"

export interface TransactionRecord {
  id: string
  reference: string
  customerName: string
  customerEmail: string
  amount: number
  status: TransactionStatus
  tier: TransactionTier
  createdAt: string
}

export interface TableMeta<TData> {
  updateData: (rowIndex: number, columnId: string, value: unknown) => void
}
```

### 2.2 Faceted Multi-Filter Component (`data-table-faceted-filter.tsx`)

```tsx
import * as React from "react"
import { Column } from "@tanstack/react-table"
import { Check, PlusCircle } from "lucide-react"
import { cn } from "@/lib/utils"
import * as Popover from "@radix-ui/react-popover"

interface FacetedFilterProps<TData, TValue> {
  column?: Column<TData, TValue>
  title?: string
  options: {
    label: string
    value: string
    icon?: React.ComponentType<{ className?: string }>
  }[]
}

export function DataTableFacetedFilter<TData, TValue>({
  column,
  title,
  options,
}: FacetedFilterProps<TData, TValue>) {
  const facets = column?.getFacetedUniqueValues()
  const selectedValues = new Set(column?.getFilterValue() as string[])

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button className="flex h-8 items-center rounded-md border border-dashed border-zinc-300 dark:border-zinc-700 px-3 text-xs font-medium text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors">
          <PlusCircle className="mr-2 h-3.5 w-3.5 text-zinc-500" />
          {title}
          {selectedValues?.size > 0 && (
            <>
              <div className="mx-2 h-4 w-[1px] bg-zinc-300 dark:bg-zinc-700" />
              <div className="flex space-x-1">
                {selectedValues.size > 2 ? (
                  <span className="rounded bg-zinc-200 dark:bg-zinc-700 px-1.5 py-0.5 text-[10px] font-semibold">
                    {selectedValues.size} selected
                  </span>
                ) : (
                  options
                    .filter((opt) => selectedValues.has(opt.value))
                    .map((opt) => (
                      <span
                        key={opt.value}
                        className="rounded bg-zinc-200 dark:bg-zinc-700 px-1.5 py-0.5 text-[10px] font-semibold"
                      >
                        {opt.label}
                      </span>
                    ))
                )}
              </div>
            </>
          )}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={4}
          className="z-50 w-52 rounded-md border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 p-1 text-zinc-950 dark:text-zinc-50 shadow-md outline-none"
        >
          <div className="flex flex-col space-y-1">
            {options.map((option) => {
              const isSelected = selectedValues.has(option.value)
              return (
                <button
                  key={option.value}
                  onClick={() => {
                    if (isSelected) {
                      selectedValues.delete(option.value)
                    } else {
                      selectedValues.add(option.value)
                    }
                    const filterValues = Array.from(selectedValues)
                    column?.setFilterValue(
                      filterValues.length ? filterValues : undefined
                    )
                  }}
                  className={cn(
                    "flex items-center w-full px-2 py-1.5 text-xs rounded-sm transition-colors text-left",
                    isSelected
                      ? "bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 font-medium"
                      : "hover:bg-zinc-50 dark:hover:bg-zinc-900 text-zinc-600 dark:text-zinc-400"
                  )}
                >
                  <div
                    className={cn(
                      "mr-2 flex h-4 w-4 items-center justify-center rounded border",
                      isSelected
                        ? "border-zinc-900 dark:border-zinc-100 bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900"
                        : "border-zinc-300 dark:border-zinc-700"
                    )}
                  >
                    {isSelected && <Check className="h-3 w-3 stroke-[3]" />}
                  </div>
                  {option.icon && (
                    <option.icon className="mr-2 h-3.5 w-3.5 text-zinc-400" />
                  )}
                  <span className="flex-1 truncate">{option.label}</span>
                  {facets?.get(option.value) && (
                    <span className="ml-auto text-[10px] font-mono text-zinc-400">
                      {facets.get(option.value)}
                    </span>
                  )}
                </button>
              )
            })}
            {selectedValues.size > 0 && (
              <>
                <div className="my-1 h-[1px] bg-zinc-200 dark:bg-zinc-800" />
                <button
                  onClick={() => column?.setFilterValue(undefined)}
                  className="w-full text-center py-1 text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 font-medium"
                >
                  Clear filters
                </button>
              </>
            )}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
```

### 2.3 Inline Editable Cell (`editable-cell.tsx`)

```tsx
import * as React from "react"
import { CellContext } from "@tanstack/react-table"
import { TableMeta, TransactionRecord } from "./table-types"

interface EditableCellProps extends CellContext<TransactionRecord, unknown> {
  validator?: (value: unknown) => boolean
}

export function EditableCell({
  getValue,
  row: { index },
  column: { id },
  table,
  validator,
}: EditableCellProps) {
  const initialValue = getValue()
  const [value, setValue] = React.useState(initialValue)
  const [isEditing, setIsEditing] = React.useState(false)
  const [hasError, setHasError] = React.useState(false)
  const inputRef = React.useRef<HTMLInputElement>(null)

  React.useEffect(() => {
    setValue(initialValue)
  }, [initialValue])

  React.useEffect(() => {
    if (isEditing) {
      inputRef.current?.focus()
      inputRef.current?.select()
    }
  }, [isEditing])

  const onCommit = () => {
    setIsEditing(false)
    if (validator && !validator(value)) {
      setHasError(true)
      setValue(initialValue)
      return
    }
    setHasError(false)
    if (value !== initialValue) {
      const meta = table.options.meta as TableMeta<TransactionRecord>
      meta?.updateData(index, id, value)
    }
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      onCommit()
    } else if (e.key === "Escape") {
      setValue(initialValue)
      setIsEditing(false)
      setHasError(false)
    }
  }

  if (isEditing) {
    return (
      <input
        ref={inputRef}
        value={value as string}
        onChange={(e) => setValue(e.target.value)}
        onBlur={onCommit}
        onKeyDown={onKeyDown}
        className="w-full bg-white dark:bg-zinc-900 border border-zinc-950 dark:border-zinc-200 px-2 py-1 text-xs rounded text-zinc-900 dark:text-zinc-50 outline-none shadow-sm ring-1 ring-zinc-950 dark:ring-zinc-200"
      />
    )
  }

  return (
    <div
      onClick={() => setIsEditing(true)}
      tabIndex={0}
      onFocus={() => setIsEditing(true)}
      className={`cursor-pointer truncate px-2 py-1 text-xs rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors border border-transparent ${
        hasError ? "border-red-500 bg-red-50 text-red-700" : ""
      }`}
    >
      {String(value)}
    </div>
  )
}
```

### 2.4 Virtualized Table View (`virtual-data-table.tsx`)

```tsx
import * as React from "react"
import {
  ColumnDef,
  ColumnFiltersState,
  SortingState,
  flexRender,
  getCoreRowModel,
  getFacetedRowModel,
  getFacetedUniqueValues,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table"
import { useVirtualizer } from "@tanstack/react-virtual"
import { TransactionRecord, TableMeta } from "./table-types"
import { EditableCell } from "./editable-cell"
import { DataTableFacetedFilter } from "./data-table-faceted-filter"

const STATUS_OPTIONS = [
  { label: "Completed", value: "completed" },
  { label: "Pending", value: "pending" },
  { label: "Processing", value: "processing" },
  { label: "Failed", value: "failed" },
]

const TIER_OPTIONS = [
  { label: "Enterprise", value: "enterprise" },
  { label: "Growth", value: "growth" },
  { label: "Starter", value: "starter" },
]

export function VirtualDataTable({
  initialData,
  onRowSelect,
}: {
  initialData: TransactionRecord[]
  onRowSelect?: (record: TransactionRecord) => void
}) {
  const [data, setData] = React.useState<TransactionRecord[]>(initialData)
  const [sorting, setSorting] = React.useState<SortingState>([])
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([])

  const columns = React.useMemo<ColumnDef<TransactionRecord>[]>(
    () => [
      {
        accessorKey: "reference",
        header: "Reference",
        size: 140,
        cell: (info) => (
          <span className="font-mono text-xs font-semibold text-zinc-900 dark:text-zinc-100">
            {info.getValue() as string}
          </span>
        ),
      },
      {
        accessorKey: "customerName",
        header: "Customer",
        size: 200,
        cell: (props) => <EditableCell {...props} />,
      },
      {
        accessorKey: "status",
        header: "Status",
        size: 130,
        filterFn: (row, id, value) => {
          return value.includes(row.getValue(id))
        },
        cell: ({ getValue }) => {
          const val = getValue() as string
          const badgeStyles: Record<string, string> = {
            completed: "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-400 dark:border-emerald-800",
            pending: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-400 dark:border-amber-800",
            processing: "bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950 dark:text-blue-400 dark:border-blue-800",
            failed: "bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950 dark:text-rose-400 dark:border-rose-800",
          }
          return (
            <span
              className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize ${
                badgeStyles[val] || "bg-zinc-100 text-zinc-800"
              }`}
            >
              {val}
            </span>
          )
        },
      },
      {
        accessorKey: "tier",
        header: "Tier",
        size: 120,
        filterFn: (row, id, value) => {
          return value.includes(row.getValue(id))
        },
        cell: ({ getValue }) => (
          <span className="text-xs uppercase font-medium text-zinc-500">
            {getValue() as string}
          </span>
        ),
      },
      {
        accessorKey: "amount",
        header: "Amount",
        size: 120,
        cell: ({ getValue }) => {
          const formatted = new Intl.NumberFormat("en-US", {
            style: "currency",
            currency: "USD",
          }).format(Number(getValue()))
          return <span className="font-mono text-xs">{formatted}</span>
        },
      },
      {
        accessorKey: "createdAt",
        header: "Timestamp",
        size: 160,
        cell: ({ getValue }) => (
          <span className="text-xs text-zinc-400 font-mono">
            {new Date(getValue() as string).toISOString().split("T")[0]}
          </span>
        ),
      },
    ],
    []
  )

  const tableMeta = React.useMemo<TableMeta<TransactionRecord>>(
    () => ({
      updateData: (rowIndex: number, columnId: string, value: unknown) => {
        setData((old) =>
          old.map((row, index) => {
            if (index === rowIndex) {
              return {
                ...old[rowIndex],
                [columnId]: value,
              }
            }
            return row
          })
        )
      },
    }),
    []
  )

  const table = useReactTable({
    data,
    columns,
    state: {
      sorting,
      columnFilters,
    },
    meta: tableMeta,
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFacetedRowModel: getFacetedRowModel(),
    getFacetedUniqueValues: getFacetedUniqueValues(),
  })

  const { rows } = table.getRowModel()
  const tableContainerRef = React.useRef<HTMLDivElement>(null)

  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => tableContainerRef.current,
    estimateSize: () => 40,
    overscan: 10,
  })

  return (
    <div className="w-full space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex flex-1 items-center space-x-2">
          <input
            placeholder="Search records..."
            value={(table.getColumn("customerName")?.getFilterValue() as string) ?? ""}
            onChange={(event) =>
              table.getColumn("customerName")?.setFilterValue(event.target.value)
            }
            className="h-8 w-48 lg:w-64 rounded-md border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 px-3 text-xs placeholder:text-zinc-400 focus:outline-none focus:ring-1 focus:ring-zinc-950 dark:focus:ring-zinc-300"
          />
          {table.getColumn("status") && (
            <DataTableFacetedFilter
              column={table.getColumn("status")}
              title="Status"
              options={STATUS_OPTIONS}
            />
          )}
          {table.getColumn("tier") && (
            <DataTableFacetedFilter
              column={table.getColumn("tier")}
              title="Tier"
              options={TIER_OPTIONS}
            />
          )}
        </div>
        <div className="text-xs text-zinc-500 font-mono">
          Showing {rows.length} of {data.length} records
        </div>
      </div>

      <div
        ref={tableContainerRef}
        className="relative h-[500px] overflow-auto rounded-md border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950"
      >
        <table className="w-full grid border-collapse">
          <thead className="grid sticky top-0 z-10 bg-zinc-50 dark:bg-zinc-900 border-b border-zinc-200 dark:border-zinc-800">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id} className="flex w-full">
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    style={{ width: `${header.getSize()}px` }}
                    className="flex items-center px-4 py-2.5 text-left text-xs font-semibold text-zinc-500 select-none uppercase tracking-wider"
                  >
                    <div
                      {...{
                        className: header.column.getCanSort()
                          ? "cursor-pointer select-none flex items-center gap-1"
                          : "",
                        onClick: header.column.getToggleSortingHandler(),
                      }}
                    >
                      {flexRender(
                        header.column.columnDef.header,
                        header.getContext()
                      )}
                      {{
                        asc: " 🔼",
                        desc: " 🔽",
                      }[header.column.getIsSorted() as string] ?? null}
                    </div>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody
            className="grid relative"
            style={{ height: `${rowVirtualizer.getTotalSize()}px` }}
          >
            {rowVirtualizer.getVirtualItems().map((virtualRow) => {
              const row = rows[virtualRow.index]
              return (
                <tr
                  key={row.id}
                  data-index={virtualRow.index}
                  ref={(node) => rowVirtualizer.measureElement(node)}
                  onClick={() => onRowSelect?.(row.original)}
                  className="flex items-center absolute w-full hover:bg-zinc-50/80 dark:hover:bg-zinc-900/80 border-b border-zinc-100 dark:border-zinc-900 cursor-pointer transition-colors"
                  style={{
                    transform: `translateY(${virtualRow.start}px)`,
                  }}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td
                      key={cell.id}
                      style={{ width: `${cell.column.getSize()}px` }}
                      className="px-4 py-2 flex items-center text-zinc-700 dark:text-zinc-300 overflow-hidden"
                    >
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext()
                      )}
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
```

---

## 3. Nested Drawer Inspector Pattern

This slide-over inspection component is designed to mount adjacent to or over the virtualized data table, allowing operators to execute mutations, read raw payload details, and audit transaction logs without losing their filter context or scroll offset.

```tsx
import * as React from "react"
import * as Dialog from "@radix-ui/react-dialog"
import * as Tabs from "@radix-ui/react-tabs"
import { X, CheckCircle2, Clock, AlertOctagon, Terminal } from "lucide-react"
import { TransactionRecord } from "./table-types"

interface DrawerInspectorProps {
  record: TransactionRecord | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSave?: (updated: TransactionRecord) => Promise<void>
}

export function DrawerInspector({
  record,
  open,
  onOpenChange,
  onSave,
}: DrawerInspectorProps) {
  const [isSubmitting, setIsSubmitting] = React.useState(false)
  const [customerName, setCustomerName] = React.useState("")

  React.useEffect(() => {
    if (record) {
      setCustomerName(record.customerName)
    }
  }, [record])

  if (!record) return null

  const handleUpdate = async () => {
    if (!onSave) return
    setIsSubmitting(true)
    try {
      await onSave({ ...record, customerName })
      onOpenChange(false)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <Dialog.Content className="fixed inset-y-0 right-0 z-50 flex h-full w-full max-w-xl flex-col border-l border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 p-6 shadow-2xl transition ease-in-out data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right duration-300">
          
          {/* Header */}
          <div className="flex items-center justify-between pb-4 border-b border-zinc-200 dark:border-zinc-800">
            <div>
              <Dialog.Title className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
                Transaction {record.reference}
              </Dialog.Title>
              <Dialog.Description className="text-xs text-zinc-500">
                Internal Unique Identifier: {record.id}
              </Dialog.Description>
            </div>
            <Dialog.Close className="rounded-md p-1.5 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-900 transition-colors">
              <X className="h-4 w-4" />
              <span className="sr-only">Close panel</span>
            </Dialog.Close>
          </div>

          {/* Tab Navigation & Body */}
          <Tabs.Root defaultValue="overview" className="flex flex-1 flex-col mt-4">
            <Tabs.List className="flex border-b border-zinc-200 dark:border-zinc-800 mb-4">
              <Tabs.Trigger
                value="overview"
                className="px-3 py-2 text-xs font-medium text-zinc-500 border-b-2 border-transparent data-[state=active]:border-zinc-900 dark:data-[state=active]:border-zinc-100 data-[state=active]:text-zinc-900 dark:data-[state=active]:text-zinc-100 transition-all"
              >
                Overview
              </Tabs.Trigger>
              <Tabs.Trigger
                value="audit"
                className="px-3 py-2 text-xs font-medium text-zinc-500 border-b-2 border-transparent data-[state=active]:border-zinc-900 dark:data-[state=active]:border-zinc-100 data-[state=active]:text-zinc-900 dark:data-[state=active]:text-zinc-100 transition-all"
              >
                Audit Trail
              </Tabs.Trigger>
              <Tabs.Trigger
                value="payload"
                className="px-3 py-2 text-xs font-medium text-zinc-500 border-b-2 border-transparent data-[state=active]:border-zinc-900 dark:data-[state=active]:border-zinc-100 data-[state=active]:text-zinc-900 dark:data-[state=active]:text-zinc-100 transition-all"
              >
                Raw Data
              </Tabs.Trigger>
            </Tabs.List>

            <Tabs.Content value="overview" className="flex-1 space-y-4 focus:outline-none">
              <div className="grid grid-cols-2 gap-4">
                <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 p-3 bg-zinc-50 dark:bg-zinc-900/50">
                  <span className="text-[10px] uppercase font-bold text-zinc-400">Total Settled</span>
                  <p className="text-lg font-mono font-bold text-zinc-900 dark:text-zinc-100">
                    ${record.amount.toFixed(2)}
                  </p>
                </div>
                <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 p-3 bg-zinc-50 dark:bg-zinc-900/50">
                  <span className="text-[10px] uppercase font-bold text-zinc-400">Status</span>
                  <div className="mt-1 flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full bg-emerald-500" />
                    <span className="text-sm font-semibold capitalize text-zinc-900 dark:text-zinc-100">
                      {record.status}
                    </span>
                  </div>
                </div>
              </div>

              <div className="space-y-3">
                <div>
                  <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                    Customer Organization
                  </label>
                  <input
                    type="text"
                    value={customerName}
                    onChange={(e) => setCustomerName(e.target.value)}
                    className="mt-1 w-full rounded-md border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-1 focus:ring-zinc-950 dark:focus:ring-zinc-200"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                    Routing Email
                  </label>
                  <input
                    type="text"
                    disabled
                    value={record.customerEmail}
                    className="mt-1 w-full rounded-md border border-zinc-200 dark:border-zinc-800 bg-zinc-100 dark:bg-zinc-900 px-3 py-2 text-xs text-zinc-500 cursor-not-allowed"
                  />
                </div>
              </div>
            </Tabs.Content>

            <Tabs.Content value="audit" className="flex-1 space-y-4 focus:outline-none">
              <div className="relative pl-6 space-y-4 border-l border-zinc-200 dark:border-zinc-800 ml-
