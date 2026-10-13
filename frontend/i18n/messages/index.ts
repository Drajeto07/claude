import type { Locale } from "../locales";
import { bg } from "./bg";
import { en, type Messages } from "./en";

const ALL: Record<Locale, Messages> = { en, bg };

export function messagesFor(locale: Locale): Messages {
  return ALL[locale];
}
