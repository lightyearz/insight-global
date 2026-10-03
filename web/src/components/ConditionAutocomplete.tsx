"use client";

import { useEffect, useId, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { ConditionSuggestion } from "@/lib/types";
import { cx } from "./ui";

interface Props {
  value: string;
  onChange: (value: string) => void;
  invalid?: boolean;
  describedBy?: string;
}

/** ARIA 1.2 combobox with a listbox popup, fed by GET /api/conditions/suggest. */
export function ConditionAutocomplete({ value, onChange, invalid, describedBy }: Props) {
  const listId = useId();
  const inputId = "condition";
  const [suggestions, setSuggestions] = useState<ConditionSuggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [query, setQuery] = useState("");
  const blurTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      api.suggestConditions(q, controller.signal).then(
        (items) => {
          setSuggestions(items);
          setActive(-1);
        },
        () => setSuggestions([]),
      );
    }, 200);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  const visible = open && query.trim().length >= 2 && suggestions.length > 0;

  const choose = (s: ConditionSuggestion) => {
    onChange(s.label);
    setOpen(false);
    setActive(-1);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((i) => (suggestions.length ? (i + 1) % suggestions.length : -1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => (suggestions.length ? (i <= 0 ? suggestions.length - 1 : i - 1) : -1));
    } else if (e.key === "Enter" && visible && active >= 0) {
      const s = suggestions[active];
      if (s) {
        e.preventDefault();
        choose(s);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
      setActive(-1);
    }
  };

  return (
    <div className="relative">
      <input
        id={inputId}
        name="condition"
        type="text"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={visible}
        aria-controls={listId}
        aria-activedescendant={visible && active >= 0 ? `${listId}-opt-${active}` : undefined}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        autoComplete="off"
        spellCheck={false}
        value={value}
        placeholder="e.g. Type 2 diabetes"
        onChange={(e) => {
          onChange(e.target.value);
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => {
          blurTimer.current = setTimeout(() => setOpen(false), 120);
        }}
        onKeyDown={onKeyDown}
        className={cx(
          "w-full rounded-md border bg-surface px-3 py-2 text-sm text-ink placeholder:text-muted",
          invalid ? "border-danger" : "border-line-strong",
        )}
      />
      <ul
        id={listId}
        role="listbox"
        aria-label="Condition suggestions"
        hidden={!visible}
        className="absolute z-20 mt-1 max-h-72 w-full overflow-auto rounded-md border border-line bg-surface py-1 shadow-lg"
      >
        {suggestions.map((s, i) => (
          <li
            key={`${s.source}-${s.label}-${s.code ?? ""}`}
            id={`${listId}-opt-${i}`}
            role="option"
            aria-selected={i === active}
            onMouseDown={(e) => {
              e.preventDefault();
              if (blurTimer.current) clearTimeout(blurTimer.current);
              choose(s);
            }}
            onMouseEnter={() => setActive(i)}
            className={cx(
              "flex cursor-pointer items-center justify-between gap-3 px-3 py-1.5 text-sm",
              i === active ? "bg-accent-soft text-ink" : "text-ink-2",
            )}
          >
            <span>{s.label}</span>
            <span className="font-mono text-xs text-muted">
              {s.code ?? (s.source === "replay" ? "recorded" : s.source)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
