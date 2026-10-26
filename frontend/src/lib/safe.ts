// Research and job data come from automation, not from a form: read it defensively before it reaches the page.

/** The strings in a list, skipping anything else (a list of objects, a number, null). */
export function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((x): x is string => typeof x === "string") : [];
}

/** The URL if it's http(s), so a `javascript:` link can never reach an href. */
export function safeUrl(value: string | null | undefined): string | undefined {
  if (!value) return undefined;
  try {
    return ["http:", "https:"].includes(new URL(value).protocol) ? value : undefined;
  } catch {
    return undefined;
  }
}
