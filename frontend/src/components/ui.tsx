import { clsx } from "clsx";
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "quiet";

export function Button({
  variant = "secondary",
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type="button"
      {...rest}
      className={clsx(
        "inline-flex min-h-[38px] items-center justify-center gap-2 rounded-lg px-4 text-sm font-medium transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-50",
        variant === "primary" && "bg-accent font-semibold text-white hover:bg-accent-hover",
        variant === "secondary" && "border border-[#D4D4DA] bg-surface text-ink hover:bg-chip",
        variant === "quiet" && "text-muted hover:bg-chip hover:text-ink",
        className,
      )}
    />
  );
}

export function Card({ className, ...rest }: HTMLAttributes<HTMLElement>) {
  return <section {...rest} className={clsx("rounded-card border border-line bg-surface", className)} />;
}

type Tone = "neutral" | "accent" | "good" | "warm" | "bad";

export function Chip({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-md px-2 py-0.5 text-xs",
        tone === "neutral" && "bg-chip font-medium text-body",
        tone === "accent" && "bg-accent-tint font-semibold text-accent-ink",
        tone === "good" && "bg-good-tint font-semibold text-good",
        tone === "warm" && "bg-warm-tint font-semibold text-warm",
        tone === "bad" && "bg-bad-tint font-semibold text-bad",
      )}
    >
      {children}
    </span>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-card border border-dashed border-[#C9C9D0] px-6 py-10 text-center">
      <p className="font-semibold">{title}</p>
      {children && <div className="mt-1 text-sm text-muted">{children}</div>}
    </div>
  );
}

export function PageHeader({ eyebrow, title, children }: { eyebrow?: string; title: string; children?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="flex flex-col gap-1">
        {eyebrow && <span className="text-[13px] font-medium text-muted">{eyebrow}</span>}
        <h1 className="text-[26px] font-bold tracking-tight">{title}</h1>
      </div>
      {children && <div className="flex flex-wrap items-center gap-3">{children}</div>}
    </header>
  );
}
