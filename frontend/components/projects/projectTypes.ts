/**
 * The project types of SmartDoc 2.0's New Project screen (S2-015, spec §5). `href` is where a
 * type starts today; types without one wait for the visual canvas (phase P5) and say so.
 * `keywords` (English and Bulgarian, lower case) let a typed description suggest a type -- a
 * word match, presented as such, never as AI.
 */
export type ProjectTypeId =
  | "document"
  | "cv"
  | "upload"
  | "template"
  | "matchLook"
  | "presentation"
  | "brochure"
  | "invitation"
  | "poster"
  | "freeDesign";

export type ProjectType = { id: ProjectTypeId; href: string | null; keywords: string[] };

export const PROJECT_TYPES: ProjectType[] = [
  { id: "document", href: "/new", keywords: ["report", "paper", "essay", "thesis", "dissertation", "letter", "contract", "article", "document", "доклад", "курсов", "есе", "дипломн", "дисертаци", "писмо", "договор", "статия", "реферат", "документ"] },
  { id: "cv", href: "/new?template=professional-cv", keywords: ["cv", "resume", "résumé", "автобиограф", "си ви"] },
  { id: "upload", href: "/new?mode=upload", keywords: ["import", "upload", "pdf", "docx", "word file", "импорт", "качи", "файл"] },
  { id: "template", href: "/templates", keywords: ["template", "шаблон"] },
  { id: "matchLook", href: "/new?reference=1", keywords: ["same look", "like this document", "match", "като документ", "същия вид"] },
  { id: "presentation", href: null, keywords: ["presentation", "slides", "slide", "deck", "презентаци", "слайд"] },
  { id: "brochure", href: null, keywords: ["brochure", "flyer", "leaflet", "брошур", "флаер", "листовк"] },
  { id: "invitation", href: null, keywords: ["invitation", "invite", "wedding", "birthday", "party", "покан", "сватб", "рожден ден", "парти"] },
  { id: "poster", href: null, keywords: ["poster", "placard", "notice board", "плакат", "афиш", "обява"] },
  { id: "freeDesign", href: null, keywords: ["design", "logo", "social", "instagram", "facebook", "post", "дизайн", "лого", "пост"] },
];

/** Most specific first: "a CV in a document" is a CV, "a poster design" a poster. */
const PRIORITY: ProjectTypeId[] = ["cv", "presentation", "brochure", "invitation", "poster", "matchLook", "template", "upload", "document", "freeDesign"];

export function suggestProjectType(description: string): ProjectTypeId | null {
  const text = ` ${description.toLowerCase()} `;
  if (!text.trim()) return null;
  for (const id of PRIORITY) {
    const type = PROJECT_TYPES.find((candidate) => candidate.id === id);
    if (type?.keywords.some((keyword) => (keyword.length <= 3 ? new RegExp(`[^\\p{L}]${keyword}[^\\p{L}]`, "u").test(text) : text.includes(keyword)))) return id;
  }
  return null;
}
