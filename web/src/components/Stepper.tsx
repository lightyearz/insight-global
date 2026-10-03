import { Check } from "lucide-react";
import { cx } from "./ui";

export type StageKey = "research" | "review" | "report";

export interface Stage {
  key: StageKey;
  label: string;
  description: string;
  state: "done" | "current" | "upcoming" | "failed";
}

interface Props {
  stages: Stage[];
  viewing: StageKey;
  onSelect: (key: StageKey) => void;
}

/** Three-stage progress indicator; reached stages are buttons that switch the view. */
export function Stepper({ stages, viewing, onSelect }: Props) {
  return (
    <nav aria-label="Briefing progress" className="no-print">
      <ol className="grid grid-cols-3 gap-2">
        {stages.map((s, i) => {
          const reachable = s.state !== "upcoming";
          const isViewing = viewing === s.key;
          return (
            <li key={s.key} className="min-w-0">
              <button
                type="button"
                disabled={!reachable}
                onClick={() => onSelect(s.key)}
                aria-current={isViewing ? "step" : undefined}
                className={cx(
                  "flex w-full items-center gap-2.5 rounded-md border px-3 py-2 text-left transition-colors",
                  isViewing ? "border-accent bg-accent-soft" : "border-line bg-surface",
                  reachable ? "hover:border-accent-line" : "cursor-not-allowed opacity-70",
                )}
              >
                <span
                  aria-hidden="true"
                  className={cx(
                    "grid size-7 shrink-0 place-items-center rounded-full text-xs font-semibold",
                    s.state === "done" && "bg-ok text-white",
                    s.state === "current" && "bg-accent text-white",
                    s.state === "upcoming" && "border border-line-strong bg-surface text-muted",
                    s.state === "failed" && "bg-danger text-white",
                  )}
                >
                  {s.state === "done" ? <Check className="size-4" /> : i + 1}
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-ink">{s.label}</span>
                  <span className="hidden truncate text-xs text-muted sm:block">{s.description}</span>
                  <span className="sr-only">
                    {s.state === "done" ? "(completed)" : s.state === "current" ? "(in progress)" : s.state === "failed" ? "(failed)" : "(not started)"}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
