import { visibleText } from "@/editor/hiddenText";
import type { Element, Template } from "@/types/document";

/**
 * M3.3: which look fits a document, from its structure and its own words -- SmartDoc's built-in rules,
 * not AI, and said so on screen. Every suggestion carries the evidence it rests on, so the person sees
 * why; nothing is applied until they choose it. No server call, no cost, the same answer every time.
 */

export type LookCategory = "academic" | "professional" | "official" | "business" | "legal";

/** Why a category scored: words found in the document, or something about its structure. */
export type Evidence =
  | { kind: "words"; words: string[] }
  | { kind: "tables"; count: number }
  | { kind: "pictures"; count: number }
  | { kind: "headings"; count: number };

export type LookSuggestion = { templateId: string; category: LookCategory; evidence: Evidence[] };

/** Word beginnings (lower case) that point to each kind of document, Bulgarian and English. */
const WORDS: Record<LookCategory, string[]> = {
  professional: ["cv", "curriculum vitae", "resume", "résumé", "автобиограф", "work experience", "професионален опит", "трудов стаж", "education", "образование", "skills", "умения", "компетенции", "лични данни", "references available"],
  legal: ["договор", "contract", "agreement", "споразумение", "пълномощ", "power of attorney", "чл.", "клауз", "clause", "наемодател", "наемател", "the parties", "страните"],
  official: ["молба", "заявление", "жалба", "декларация", "declaration", "complaint", "application for", "уважаеми", "dear sir", "dear madam", "с уважение", "yours sincerely", "до директора", "до г-н"],
  academic: ["курсова", "дипломна", "реферат", "дисертац", "thesis", "dissertation", "abstract", "използвана литература", "библиограф", "bibliography", "references", "методолог", "methodology", "университет", "university", "факултет", "въведение", "introduction", "заключение", "conclusion"],
  business: ["отчет", "доклад", "report", "анализ", "analysis", "бюджет", "budget", "quarterly", "тримесеч", "приход", "revenue", "продажби", "sales", "kpi", "стратеги", "strategy", "пазар", "market"],
};

const BODY_CHARS = 3000;
/** Below this the evidence is too thin to suggest anything. */
const MIN_SCORE = 2;

/** The listed words the text has, each as the text writes it ("приходите" for "приход"). A word counts
 * where it starts a word: "отчет" in "отчетът", not "cv" inside "abcv". */
function wordsFound(text: string, words: string[]): string[] {
  const lower = ` ${text.toLowerCase()} `;
  const found: string[] = [];
  for (const word of words) {
    const match = new RegExp(`(?:^|[^\\p{L}])(${word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\p{L}*)`, "u").exec(lower);
    if (match && !found.includes(match[1])) found.push(match[1]);
  }
  return found;
}

/** The best fitting category for these blocks, with its evidence; null when nothing points clearly. */
export function suggestCategory(elements: Element[], title = ""): { category: LookCategory; evidence: Evidence[] } | null {
  const headings = elements.filter((element) => element.type === "heading");
  const headingText = [title, ...headings.map(visibleText)].join(" \n ");
  let bodyText = "";
  for (const element of elements) {
    if (element.type === "heading" || bodyText.length >= BODY_CHARS) continue;
    bodyText += ` ${visibleText(element)}`;
  }
  const tables = elements.filter((element) => element.type === "table").length;
  const pictures = elements.filter((element) => element.type === "image").length;

  const scored = (Object.keys(WORDS) as LookCategory[]).map((category) => {
    const inHeadings = wordsFound(headingText, WORDS[category]);
    const inBody = wordsFound(bodyText, WORDS[category]).filter((word) => !inHeadings.includes(word));
    let score = inHeadings.length * 2 + inBody.length;
    const evidence: Evidence[] = [];
    const words = [...inHeadings, ...inBody];
    if (words.length) evidence.push({ kind: "words", words: words.slice(0, 4) });
    if (category === "business" && tables > 0) {
      score += 1;
      evidence.push({ kind: "tables", count: tables });
    }
    if (category === "business" && pictures > 0) {
      score += 1;
      evidence.push({ kind: "pictures", count: pictures });
    }
    if (category === "academic" && headings.length >= 4) {
      score += 1;
      evidence.push({ kind: "headings", count: headings.length });
    }
    return { category, score, evidence };
  });
  scored.sort((a, b) => b.score - a.score);
  const [best, next] = scored;
  // A tie is no clear answer.
  if (best.score < MIN_SCORE || (next && next.score === best.score)) return null;
  return { category: best.category, evidence: best.evidence };
}

/** The template to suggest: the built-in one of the best category (else any of that category). */
export function suggestLook(elements: Element[], title: string, templates: Template[]): LookSuggestion | null {
  const found = suggestCategory(elements, title);
  if (!found) return null;
  const ofCategory = templates.filter((template) => template.category === found.category);
  const template = ofCategory.find((each) => each.builtin) ?? ofCategory[0];
  return template ? { templateId: template.id, ...found } : null;
}
