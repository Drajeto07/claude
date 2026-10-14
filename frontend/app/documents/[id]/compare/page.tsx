import type { Metadata } from "next";

import { pageMetadata } from "@/i18n/server";

import { CompareView } from "@/components/documents/CompareView";

export const generateMetadata = (): Promise<Metadata> => pageMetadata((m) => m.compare.title);

function version(value: string | string[] | undefined): number | undefined {
  const number = Number(Array.isArray(value) ? value[0] : value);
  return Number.isInteger(number) && number > 0 ? number : undefined;
}

export default async function ComparePage({ params, searchParams }: PageProps<"/documents/[id]/compare">) {
  const { id } = await params;
  const query = await searchParams;
  const from = version(query.from) ?? 1;
  const to = version(query.to);
  return <CompareView key={`${id}:${from}:${to ?? "now"}`} documentId={id} from={from} to={to} />;
}
