import clsx from "clsx";
import type { ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, TextareaHTMLAttributes } from "react";

export function Button({
  variant = "primary",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" }) {
  return (
    <button
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
        variant === "primary" && "bg-accent text-accent-fg hover:opacity-90",
        variant === "secondary" && "border border-border bg-surface hover:bg-surface-2",
        variant === "ghost" && "hover:bg-surface-2",
        className,
      )}
      {...props}
    />
  );
}

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={clsx("rounded-lg border border-border bg-surface p-5", className)} {...props} />;
}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={clsx(
        "w-full rounded-md border border-border bg-surface px-3 py-2 text-sm placeholder:text-muted",
        className,
      )}
      {...props}
    />
  );
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={clsx(
        "w-full rounded-md border border-border bg-surface px-3 py-2 font-mono text-sm placeholder:text-muted",
        className,
      )}
      {...props}
    />
  );
}

export function Label({ className, ...props }: HTMLAttributes<HTMLLabelElement> & { htmlFor?: string }) {
  return <label className={clsx("mb-1 block text-sm font-medium", className)} {...props} />;
}

export function Badge({
  tone = "neutral",
  className,
  ...props
}: HTMLAttributes<HTMLSpanElement> & { tone?: "neutral" | "ok" | "warn" | "danger" | "accent" }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium",
        tone === "neutral" && "border-border text-muted",
        tone === "ok" && "border-ok/40 text-ok",
        tone === "warn" && "border-warn/40 text-warn",
        tone === "danger" && "border-danger/40 text-danger",
        tone === "accent" && "border-accent/40 text-accent",
        className,
      )}
      {...props}
    />
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={clsx("animate-pulse rounded bg-surface-2", className)} />;
}

/** Renders a number with its source, or "not measured" when null (§B16). */
export function Metric({ label, value, source }: { label: string; value: string | number | null | undefined; source: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value ?? <span className="text-base text-muted">not measured</span>}</div>
      <div className="mt-0.5 text-xs text-muted">source: {source}</div>
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <p role="alert" className="rounded-md border border-danger/40 bg-danger/5 px-3 py-2 text-sm text-danger">
      {msg}
    </p>
  );
}
