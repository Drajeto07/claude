import { apiFetch, jsonOrThrow } from "@/services/api/client";
import type { Usage } from "@/types/document";

/** This month's usage of the user's workspace (counted by the backend), and what it stores. */
export async function getUsage(): Promise<Usage> {
  return jsonOrThrow(await apiFetch("/api/usage", { cache: "no-store" }), "Couldn't load your usage");
}
