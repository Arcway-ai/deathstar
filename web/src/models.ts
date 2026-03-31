import type { ProviderName, WorkflowKind } from "./types";

export type SpeedTier = "fast" | "medium" | "slow";
export type PriceTier = "budget" | "standard" | "premium";

export interface ModelPricing {
  inputPer1M: number;   // USD per 1M input tokens
  outputPer1M: number;  // USD per 1M output tokens
}

export interface ModelInfo {
  id: string;
  name: string;
  provider: ProviderName;
  speed: SpeedTier;
  price: PriceTier;
  pricing: ModelPricing;
  contextWindow: string;
  description: string;
  recommended?: boolean;
  recommendedFor?: WorkflowKind[];
}

export const MODEL_CATALOG: ModelInfo[] = [
  // ── Anthropic (Claude Code subscription) ────────────────────────
  {
    id: "claude-opus-4-6",
    name: "Claude Opus 4.6",
    provider: "anthropic",
    speed: "slow",
    price: "premium",
    pricing: { inputPer1M: 15.0, outputPer1M: 75.0 },
    contextWindow: "200K",
    description: "Most capable Claude model for complex reasoning",
    recommended: true,
    recommendedFor: ["patch", "review", "prompt"],
  },
  {
    id: "claude-sonnet-4-6",
    name: "Claude Sonnet 4.6",
    provider: "anthropic",
    speed: "medium",
    price: "standard",
    pricing: { inputPer1M: 3.0, outputPer1M: 15.0 },
    contextWindow: "200K",
    description: "Best balance of speed, cost, and capability",
  },
  {
    id: "claude-haiku-4-5-20251001",
    name: "Claude Haiku 4.5",
    provider: "anthropic",
    speed: "fast",
    price: "budget",
    pricing: { inputPer1M: 0.8, outputPer1M: 4.0 },
    contextWindow: "200K",
    description: "Fastest Claude, great for chat and simple tasks",
    recommendedFor: ["prompt"],
  },
];

export function modelsForProvider(provider: ProviderName): ModelInfo[] {
  return MODEL_CATALOG.filter((m) => m.provider === provider);
}

/** Find a model by provider + id. */
export function findModel(provider: ProviderName, modelId: string): ModelInfo | undefined {
  return MODEL_CATALOG.find((m) => m.provider === provider && m.id === modelId);
}

/** Estimate cost from token usage. Returns null if pricing or usage unavailable. */
export function estimateCost(
  provider: ProviderName,
  modelId: string,
  inputTokens: number | null | undefined,
  outputTokens: number | null | undefined,
): number | null {
  const model = findModel(provider, modelId);
  if (!model) return null;
  const inp = inputTokens ?? 0;
  const out = outputTokens ?? 0;
  if (inp === 0 && out === 0) return null;
  return (inp / 1_000_000) * model.pricing.inputPer1M + (out / 1_000_000) * model.pricing.outputPer1M;
}

/** Format cost as a readable string. */
export function formatCost(cost: number): string {
  if (cost < 0.001) return "<$0.001";
  if (cost < 0.01) return `$${cost.toFixed(4)}`;
  if (cost < 1) return `$${cost.toFixed(3)}`;
  return `$${cost.toFixed(2)}`;
}

export const SPEED_META: Record<SpeedTier, { label: string; color: string }> = {
  fast: { label: "Fast", color: "text-emerald-400 bg-emerald-400/10" },
  medium: { label: "Medium", color: "text-amber-400 bg-amber-400/10" },
  slow: { label: "Slow", color: "text-orange-400 bg-orange-400/10" },
};

export const PRICE_META: Record<PriceTier, { label: string; color: string }> = {
  budget: { label: "$", color: "text-emerald-400 bg-emerald-400/10" },
  standard: { label: "$$", color: "text-amber-400 bg-amber-400/10" },
  premium: { label: "$$$", color: "text-rose-400 bg-rose-400/10" },
};
