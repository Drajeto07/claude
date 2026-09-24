/** Categories offered when editing a template. The backend accepts any short
 * text, so a template can carry one not listed here; it is shown as-is. */
export const TEMPLATE_CATEGORIES: readonly { value: string; label: string }[] = [
  { value: "general", label: "General" },
  { value: "academic", label: "Academic" },
  { value: "professional", label: "Professional" },
  { value: "business", label: "Business" },
  { value: "official", label: "Official" },
  { value: "legal", label: "Legal" },
];

export function categoryLabel(value: string): string {
  return TEMPLATE_CATEGORIES.find((category) => category.value === value)?.label ?? value;
}
