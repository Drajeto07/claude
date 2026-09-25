import { cookies } from "next/headers";

import { Dashboard } from "@/components/dashboard/Dashboard";
import { Landing } from "@/components/Landing";
import { SESSION_COOKIE } from "@/services/api";

/** Signed in: the dashboard (корекции.docx §64). Otherwise: the landing page.
 * An expired session shows the dashboard for a moment, until its first request
 * answers 401 and sends the browser to /login. */
export default async function Home() {
  const signedIn = Boolean((await cookies()).get(SESSION_COOKIE)?.value);
  return signedIn ? <Dashboard /> : <Landing />;
}
