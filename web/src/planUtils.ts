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

/* ── Plan prompts ────────────────────────────────────────────── */

/** JSON schema excerpt shared by both prompts. */
const PLAN_JSON_SCHEMA = [
  "{",
  '  "title": "Short descriptive title (under 80 chars)",',
  '  "overview": "1-3 sentence summary",',
  '  "complexity": "low | medium | high",',
  '  "phases": [{ "id": "phase-1", "name": "...", "description": "...", "tasks": [{ "id": "phase-1-task-1", "title": "...", "description": "...", "files": ["path/to/file.py"], "effort": "small | medium | large" }] }],',
  '  "risks": ["Concrete risk descriptions"],',
  '  "open_questions": ["Specific questions needing answers"]',
  "}",
].join("\n");

/** Prompt sent as a follow-up to restructure a raw plan into JSON. */
export const STRUCTURE_PLAN_PROMPT = [
  "Please restructure the plan you just created into a single JSON object matching this exact schema (output ONLY valid JSON, no markdown fences, no commentary):",
  "",
  PLAN_JSON_SCHEMA,
].join("\n");

/** Firmer follow-up prompt sent when the agent returned malformed plan JSON. */
export const RETRY_STRUCTURE_PLAN_PROMPT = [
  "Your previous response could not be parsed as valid JSON. Please try again — output ONLY a single valid JSON object with no markdown fences, no trailing commas, and no commentary before or after. Match this schema exactly:",
  "",
  PLAN_JSON_SCHEMA,
  "",
  "Double-check that every string is properly escaped and the JSON is valid before responding.",
].join("\n");
