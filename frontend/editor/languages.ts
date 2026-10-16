/** The languages a translation can be made into (the backend's translation/language.py
 * TARGET_LANGUAGES), by their names. */
export const LANGUAGES: { tag: string; name: string }[] = [
  { tag: "bg", name: "Bulgarian" },
  { tag: "en", name: "English" },
  { tag: "de", name: "German" },
  { tag: "fr", name: "French" },
  { tag: "es", name: "Spanish" },
  { tag: "it", name: "Italian" },
  { tag: "pt", name: "Portuguese" },
  { tag: "nl", name: "Dutch" },
  { tag: "pl", name: "Polish" },
  { tag: "ro", name: "Romanian" },
  { tag: "tr", name: "Turkish" },
  { tag: "ru", name: "Russian" },
  { tag: "uk", name: "Ukrainian" },
  { tag: "sr", name: "Serbian" },
  { tag: "el", name: "Greek" },
  { tag: "he", name: "Hebrew" },
  { tag: "ar", name: "Arabic" },
  { tag: "hi", name: "Hindi" },
  { tag: "th", name: "Thai" },
  { tag: "zh", name: "Chinese" },
  { tag: "ja", name: "Japanese" },
  { tag: "ko", name: "Korean" },
];

export function languageName(tag: string | null | undefined): string {
  if (!tag) return "an unknown language";
  return LANGUAGES.find((language) => language.tag === tag.split("-")[0].toLowerCase())?.name ?? tag;
}
