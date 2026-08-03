import type { Metadata } from "next";
import type { ReactNode } from "react";

import { THEME_INIT_SCRIPT } from "@/components/ThemeToggle";
import { APP_NAME } from "@/lib/config";

import "@/styles/global.css";

export const metadata: Metadata = {
  title: APP_NAME,
  description: "Local AI/ML infrastructure — inference, vector storage, metering.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/*
          Stamps data-theme before first paint so an explicit light/dark choice
          never flashes the wrong theme. It must be inline and synchronous —
          anything deferred paints first and corrects afterwards, which is the
          flash. suppressHydrationWarning on <html> is required because this
          script mutates the element the server just rendered.
        */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
