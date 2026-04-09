import type { StructuredPlan } from "./types";

/** Strip optional markdown code fences and parse JSON. */
export function tryParseJSON(content: string): unknown | null {
  try {
    let raw = content.trim();
    if (raw.startsWith("```")) {
      const firstNewline = raw.indexOf("\n");
      raw = raw.slice(firstNewline + 1);
      if (raw.endsWith("```")) raw = raw.slice(0, -3).trim();
    }
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/** Attempt to parse content as a StructuredPlan JSON object. */
export function tryParsePlan(content: string): StructuredPlan | null {
  const parsed = tryParseJSON(content);
  if (
    parsed &&
    typeof parsed === "object" &&
    "title" in parsed &&
    "phases" in parsed &&
    Array.isArray((parsed as StructuredPlan).phases)
  ) {
    return parsed as StructuredPlan;
  }
  return null;
}
