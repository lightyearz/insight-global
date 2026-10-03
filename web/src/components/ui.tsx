import Link from "next/link";
import type { ComponentPropsWithoutRef, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANT: Record<Variant, string> = {
  primary:
    "bg-accent text-white hover:bg-accent-hover border border-transparent disabled:bg-subtle disabled:text-muted disabled:border-line",
  secondary: "bg-surface text-ink border border-line-strong hover:bg-subtle disabled:text-muted",
  ghost: "bg-transparent text-ink-2 border border-transparent hover:bg-subtle disabled:text-muted",
  danger: "bg-surface text-danger border border-line-strong hover:bg-danger-soft disabled:text-muted",
};

const BASE =
  "inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

interface ButtonProps extends ComponentPropsWithoutRef<"button"> {
  variant?: Variant;
}

export function Button({ variant = "secondary", className, type = "button", ...rest }: ButtonProps) {
  return <button type={type} className={cx(BASE, VARIANT[variant], className)} {...rest} />;
}

interface ButtonLinkProps extends ComponentPropsWithoutRef<typeof Link> {
  variant?: Variant;
}

export function ButtonLink({ variant = "secondary", className, ...rest }: ButtonLinkProps) {
  return <Link className={cx(BASE, VARIANT[variant], className)} {...rest} />;
}

export function Card({
  className,
  children,
  ...rest
}: ComponentPropsWithoutRef<"section"> & { children: ReactNode }) {
  return (
    <section className={cx("rounded-lg border border-line bg-surface", className)} {...rest}>
      {children}
    </section>
  );
}

type Tone = "neutral" | "accent" | "ok" | "warn" | "danger" | "info";

const TONE: Record<Tone, string> = {
  neutral: "bg-subtle text-ink-2 border-line",
  accent: "bg-accent-soft text-accent border-accent-line",
  ok: "bg-ok-soft text-ok border-ok/30",
  warn: "bg-warn-soft text-warn border-warn-line",
  danger: "bg-danger-soft text-danger border-danger/30",
  info: "bg-info-soft text-info border-info/30",
};

export function Badge({
  tone = "neutral",
  className,
  children,
  title,
}: {
  tone?: Tone;
  className?: string;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-0.5 text-xs font-medium",
        TONE[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Callout({
  tone = "neutral",
  icon,
  title,
  children,
  className,
  role,
}: {
  tone?: Tone;
  icon?: ReactNode;
  title?: ReactNode;
  children?: ReactNode;
  className?: string;
  role?: "alert" | "status" | "note";
}) {
  return (
    <div role={role} className={cx("flex gap-2.5 rounded-md border px-3 py-2.5 text-sm", TONE[tone], className)}>
      {icon ? <span className="mt-0.5 shrink-0">{icon}</span> : null}
      <div className="min-w-0">
        {title ? <p className="font-semibold">{title}</p> : null}
        {children ? <div className={cx(title ? "mt-0.5" : undefined, "text-ink-2")}>{children}</div> : null}
      </div>
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <span role="status" className="inline-flex items-center gap-2 text-sm text-muted">
      <span
        aria-hidden="true"
        className="size-4 animate-spin rounded-full border-2 border-line-strong border-t-accent"
      />
      {label}
    </span>
  );
}

export function SectionHeading({ id, children, aside }: { id?: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
      <h2 id={id} className="text-base font-semibold text-ink">
        {children}
      </h2>
      {aside}
    </div>
  );
}
