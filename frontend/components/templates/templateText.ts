import type { Messages } from "@/i18n/messages/en";
import type { Template } from "@/types/document";

/**
 * What a template is called and how it is described, in the interface language (S2-028). A built-in template's
 * words come from the dictionaries, by its id (the server sends them in Bulgarian); one the dictionaries don't
 * know yet keeps the server's. A template of the user's own -- made, duplicated, saved from a document or
 * imported from Word -- keeps the words it was saved with, in whatever language they are.
 */
export function templateText(template: Pick<Template, "id" | "builtin" | "name" | "description">, m: Messages): { name: string; description: string } {
  const builtins: Partial<Record<string, { name: string; description: string }>> = m.templatesPage.builtins;
  return (template.builtin && builtins[template.id]) || { name: template.name, description: template.description };
}
