import { APP_NAME } from "@/lib/config";

import pkg from "../../package.json";

/**
 * Placeholder landing route (BB-101 §101.1).
 *
 * Deliberately static: no data fetching until BB-103 lands the typed client, and
 * no styling until BB-102 lands the tokens. Its only job is to prove the
 * container serves and the build is wired correctly.
 */
export default function Home() {
  return (
    <main>
      <h1>{APP_NAME}</h1>
      <p>Frontend scaffold v{pkg.version}</p>
      <p>Dashboard pages land in BB-105 through BB-108.</p>
    </main>
  );
}
