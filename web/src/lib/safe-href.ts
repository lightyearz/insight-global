/**
 * Only http(s) links are rendered. Source URLs are validated server side (https on NLM hosts), but the UI
 * never trusts that: anything else (javascript:, data:, vbscript:, relative paths) renders without a link.
 */
export function safeHref(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : undefined;
  } catch {
    return undefined;
  }
}
