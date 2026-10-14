import { apiFetch, jsonOrThrow } from "@/services/api/client";
import type { components } from "@/types/generated/api";

/** Whether this server has an AI model configured (GET /capabilities/ai): a step is called AI only
 * when one really runs it; otherwise the rules-based fallback is named as such. */
export async function getAiAvailability(): Promise<boolean> {
  const answer = await jsonOrThrow<components["schemas"]["AiAvailability"]>(await apiFetch("/capabilities/ai", { cache: "no-store" }), "Couldn't check whether AI is available");
  return answer.configured;
}
