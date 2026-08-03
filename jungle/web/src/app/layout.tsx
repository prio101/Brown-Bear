import type { Metadata } from "next";
import type { ReactNode } from "react";

import { APP_NAME } from "@/lib/config";

export const metadata: Metadata = {
  title: APP_NAME,
  description: "Local AI/ML infrastructure — inference, vector storage, metering.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    // `color-scheme` on the root element is what makes form controls,
    // scrollbars and the canvas follow the theme. BB-102 replaces the inline
    // style with the token layer and adds the explicit light/dark toggle.
    <html lang="en" style={{ colorScheme: "light dark" }}>
      <body>{children}</body>
    </html>
  );
}
