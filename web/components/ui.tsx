/** Small hand-rolled UI primitives (light SaaS look) shared across pages. */

import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
} from "react";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/* ── Layout blocks ─────────────────────────────────────────────────────── */

export function Card({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-neutral-200 bg-white p-5 shadow-sm",
        className
      )}
    >
      {children}
    </div>
  );
}

export function PageTitle({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-neutral-900">
          {title}
        </h1>
        {subtitle && <p className="mt-1 text-sm text-neutral-500">{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h2 className="mb-3 text-base font-semibold text-neutral-900">{children}</h2>
  );
}

export function MetricCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
}) {
  return (
    <Card className="min-w-0">
      <p className="truncate text-xs font-medium uppercase tracking-wide text-neutral-500">
        {label}
      </p>
      <p className="mt-1 truncate text-2xl font-semibold text-neutral-900" title={hint}>
        {value}
      </p>
    </Card>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-neutral-300 bg-neutral-50 p-8 text-center text-sm text-neutral-500">
      {children}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-block size-4 animate-spin rounded-full border-2 border-neutral-300 border-t-indigo-600",
        className
      )}
    />
  );
}

/* ── Form controls ─────────────────────────────────────────────────────── */

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "outline" | "ghost";
};

export function Button({ variant = "primary", className, ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        variant === "primary" &&
          "bg-indigo-600 text-white hover:bg-indigo-700 active:bg-indigo-800",
        variant === "outline" &&
          "border border-neutral-300 bg-white text-neutral-700 hover:bg-neutral-50",
        variant === "ghost" && "text-neutral-600 hover:bg-neutral-100",
        className
      )}
      {...props}
    />
  );
}

export function Input({
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "w-full rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm text-neutral-900 placeholder-neutral-400 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100",
        className
      )}
      {...props}
    />
  );
}

export function Select({
  className,
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "w-full rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm text-neutral-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100",
        className
      )}
      {...props}
    >
      {children}
    </select>
  );
}

export function CheckboxRow({
  label,
  help,
  checked,
  onChange,
}: {
  label: string;
  help?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5 text-sm text-neutral-700">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 size-4 rounded border-neutral-300 accent-indigo-600"
      />
      <span>
        {label}
        {help && <span className="block text-xs text-neutral-400">{help}</span>}
      </span>
    </label>
  );
}

/* ── Badges ────────────────────────────────────────────────────────────── */

export function Badge({
  color = "neutral",
  children,
}: {
  color?: "green" | "red" | "amber" | "blue" | "neutral" | "indigo";
  children: ReactNode;
}) {
  const colors = {
    green: "bg-green-50 text-green-700 ring-green-600/20",
    red: "bg-red-50 text-red-700 ring-red-600/20",
    amber: "bg-amber-50 text-amber-700 ring-amber-600/20",
    blue: "bg-blue-50 text-blue-700 ring-blue-600/20",
    indigo: "bg-indigo-50 text-indigo-700 ring-indigo-600/20",
    neutral: "bg-neutral-100 text-neutral-600 ring-neutral-500/20",
  } as const;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        colors[color]
      )}
    >
      {children}
    </span>
  );
}

export function TrendBadge({ trend }: { trend: string }) {
  const map = {
    improving: { color: "green" as const, label: "▲ Improving" },
    declining: { color: "red" as const, label: "▼ Declining" },
    stable: { color: "amber" as const, label: "— Stable" },
    unknown: { color: "neutral" as const, label: "Unknown" },
  };
  const t = map[trend as keyof typeof map] ?? map.unknown;
  return <Badge color={t.color}>{t.label}</Badge>;
}

export function DeltaCell({ delta }: { delta: number | null }) {
  if (delta == null) return <span className="text-neutral-400">—</span>;
  if (delta === 0) return <span className="text-neutral-500">0</span>;
  // Negative delta = rank number went down = climbed = good.
  const good = delta < 0;
  return (
    <span className={good ? "font-medium text-green-600" : "font-medium text-red-600"}>
      {good ? "▲" : "▼"} {Math.abs(delta)}
    </span>
  );
}
