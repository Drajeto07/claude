import { cookies, headers } from "next/headers";

import { LOCALE_COOKIE, resolveLocale, type Locale } from "./locales";
import { messagesFor } from "./messages";
import type { Messages } from "./messages/en";

/** The interface language of this request: the stored choice, else the browser's language. */
export async function getLocale(): Promise<Locale> {
  const [cookieStore, headerStore] = await Promise.all([cookies(), headers()]);
  return resolveLocale(cookieStore.get(LOCALE_COOKIE)?.value, headerStore.get("accept-language"));
}

/** The messages for server components. */
export async function getMessages(): Promise<Messages> {
  return messagesFor(await getLocale());
}

/** A page's <title> in the interface language: "Шаблони · SmartDoc". */
export async function pageMetadata(pick: (messages: Messages) => string): Promise<import("next").Metadata> {
  return { title: `${pick(await getMessages())} · SmartDoc` };
}
