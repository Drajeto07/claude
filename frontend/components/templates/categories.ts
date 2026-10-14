import type { Messages } from "@/i18n/messages/en";

/** Categories offered when editing a template. The backend accepts any short
 * text, so a template can carry one not listed here; it is shown as-is. */
export const TEMPLATE_CATEGORIES = ["general", "academic", "professional", "business", "official", "legal"] as const;

/** A category's name in the interface language; one this list doesn't know, as written. */
export function categoryLabel(value: string, m: Messages): string {
  const labels: Record<string, string> = m.templatesPage.categories;
  return labels[value] ?? value;
}
