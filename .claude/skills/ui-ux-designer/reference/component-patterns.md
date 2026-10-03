# Component Patterns

## Contents

- [Buttons](#buttons)
- [Form fields](#form-fields)
- [Cards](#cards)
- [Status badges](#status-badges)
- [Dialogs](#dialogs)
- [Toasts and inline alerts](#toasts-and-inline-alerts)
- [Empty, loading and error states](#empty-loading-and-error-states)
- [Chat bubbles](#chat-bubbles)

All examples use utilities generated from the tokens in the `design-tokens.md` reference. Prefer a headless, accessible primitive library (Radix UI, React Aria, Headless UI) for dialogs, menus, comboboxes, tabs and tooltips; style it with tokens rather than hand-rolling focus and keyboard behaviour.

## Buttons

One primary button per view or dialog. Variants by intent, not by colour:

```tsx
const base =
  "inline-flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-semibold " +
  "transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring " +
  "disabled:cursor-not-allowed disabled:opacity-50 min-h-10";

const variants = {
  primary:     "bg-primary text-on-primary hover:bg-primary-hover",
  secondary:   "border border-border-strong bg-surface text-text hover:bg-surface-muted",
  ghost:       "bg-transparent text-text hover:bg-surface-muted",
  destructive: "bg-danger text-text-inverse hover:opacity-90",
} as const;

// Loading: keep the width, swap the icon, announce busy
<button type="submit" className={`${base} ${variants.primary}`} disabled={pending} aria-busy={pending}>
  {pending ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : <Save className="size-4" aria-hidden="true" />}
  Save changes
</button>

// Icon-only: needs an accessible name and a 40px hit area
<button type="button" className={`${base} ${variants.ghost} size-10 px-0`} aria-label="Close panel">
  <X className="size-5" aria-hidden="true" />
</button>
```

Rules:

- Label with a verb and object ("Save changes", "Export CSV"), not "OK" or "Submit".
- Destructive actions use the destructive variant and a confirmation that names the thing being destroyed. Prefer undo over confirm for reversible actions.
- Do not disable a submit button to signal validation errors; let it submit and show the errors.
- Links navigate, buttons act. Do not style a `<Link>` as a button for an in-page action or a `<button>` as a link for navigation.
- If the destructive fill uses `--color-danger`, check its foreground contrast in both themes; in dark mode the light red fill needs a dark foreground.

## Form fields

```tsx
<div className="space-y-1.5">
  <label htmlFor="email" className="text-sm font-medium text-text">Work email</label>
  <input
    id="email"
    type="email"
    autoComplete="email"
    aria-invalid={!!error}
    aria-describedby={error ? "email-error" : "email-help"}
    className="block w-full rounded-md border border-border-strong bg-surface px-3 py-2 text-text
               placeholder:text-text-subtle
               focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus-ring
               aria-[invalid=true]:border-danger"
  />
  {error ? (
    <p id="email-error" className="flex items-center gap-1.5 text-sm text-danger">
      <AlertCircle className="size-4" aria-hidden="true" /> {error}
    </p>
  ) : (
    <p id="email-help" className="text-sm text-text-muted">We send the report link here.</p>
  )}
</div>
```

Rules:

- Visible label above every field. Placeholder is an example, never the label.
- Mark the minority: if most fields are required, mark the optional ones "(optional)".
- Validate on blur or submit, not on every keystroke. On submit, show an error summary at the top that links to each field and move focus to it.
- Error text says what is wrong and how to fix it ("Enter a date after 1 Jan 2024"), not "Invalid input".
- Use the right `type`, `inputMode` and `autoComplete` so mobile keyboards and password managers work.
- Group related radios and checkboxes in `<fieldset>` with a `<legend>`.

## Cards

```tsx
<article className="rounded-lg border border-border bg-surface p-6 shadow-sm">
  <div className="mb-4 flex size-12 items-center justify-center rounded-md bg-primary-subtle text-on-primary-subtle">
    <BarChart3 className="size-6" aria-hidden="true" />
  </div>
  <h3 className="mb-2 text-lg font-semibold text-text">Feature title</h3>
  <p className="text-text-muted">One or two sentences on what this does for the user.</p>
</article>
```

- A clickable card has exactly one link or button inside it; stretch its hit area with an `after:absolute after:inset-0` pseudo-element on the link instead of wrapping the whole card in an anchor (keeps the accessible name short and nested controls usable).
- Hover elevation (`hover:shadow-md`) only on cards that are actually interactive.

## Status badges

```tsx
const statusStyles = {
  neutral: "bg-neutral-surface text-neutral",
  info:    "bg-info-surface text-info",
  success: "bg-success-surface text-success",
  warning: "bg-warning-surface text-warning",
  danger:  "bg-danger-surface text-danger",
} as const;

const statusIcons = { neutral: Circle, info: Info, success: CheckCircle2, warning: AlertTriangle, danger: XOctagon } as const;

function StatusBadge({ level, label }: { level: keyof typeof statusStyles; label: string }) {
  const Icon = statusIcons[level];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${statusStyles[level]}`}>
      <Icon className="size-3.5" aria-hidden="true" />
      {label}
    </span>
  );
}
```

Always icon + label. A bare coloured dot is acceptable only next to a visible text label that already states the status.

## Dialogs

- Use a primitive (Radix `Dialog`, React Aria `Modal`) or the native `<dialog>` element with `showModal()`. Requirements: focus moves into the dialog on open, focus is trapped, `Esc` closes, focus returns to the trigger on close, background is inert, the dialog has `aria-labelledby` pointing at its title.
- Overlay `bg-overlay`; panel `bg-surface rounded-xl shadow-lg`, `max-w-lg` for confirmations, `max-w-2xl` for forms, full-screen sheet below `sm`.
- Title states the decision; primary action on the right (or bottom on mobile) labelled with the verb; secondary "Cancel".
- Do not open a dialog from a dialog. Do not use a dialog for content users need to compare against the page behind it; use a side panel.

## Toasts and inline alerts

- Toasts are for confirmation of something the user just did ("Report exported"). Render them in a container with `role="status"` (polite) so screen readers announce them; use `role="alert"` only for urgent failures.
- Keep a toast on screen at least 5 seconds, pause the timer on hover and focus, and include an action (Undo, View) when there is one. Errors that need action are not toasts; show an inline alert next to the thing that failed.
- Inline alert: status surface + icon + title + one sentence + optional action, using the status tokens.

## Empty, loading and error states

- **Loading:** skeletons that match the final layout for content regions (cards, table rows); a spinner only for short, bounded actions. Avoid layout shift when data arrives. Show a skeleton only after ~300ms to avoid flicker on fast responses.
- **Empty (first use):** say what will appear here, why it is empty, and the one action that fills it ("No reports yet. Create your first report.").
- **Empty (no results):** echo the query or filters and offer to clear them.
- **Error:** what happened in plain language, whether data was lost, and what to do next (Retry, Contact support). Never show a raw stack trace or status code alone.
- **Partial failure:** render what loaded and mark the failed region in place; do not blank the whole page.

## Chat bubbles

For chat or assistant surfaces, theme bubbles through feature-scoped tokens so users can switch accent themes without touching components (themes defined in the `themes-and-dark-mode.md` reference):

```tsx
<div className="flex justify-end">
  <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-[var(--chat-user-bubble)] px-4 py-2 text-[var(--chat-user-text)]">
    {userMessage}
  </div>
</div>
<div className="flex justify-start">
  <div className="max-w-[80%] rounded-2xl rounded-bl-sm bg-[var(--chat-assistant-bubble)] px-4 py-2 text-[var(--chat-assistant-text)]">
    {assistantMarkdown}
  </div>
</div>
```

- Message list is a `role="log"` region with `aria-live="polite"`; announce the completed assistant message once, not every streamed token.
- Bubble text pairs must pass 4.5:1 in every theme; the bubble itself need not contrast with the page background because it is not a control.
- Long code blocks and tables scroll inside the bubble (`overflow-x-auto`), never the page.
- Show sending, streaming, failed (with Retry) and stopped states on the user's and the assistant's messages.
