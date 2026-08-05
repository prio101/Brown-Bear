"use client";

import { useEffect, useState } from "react";

import { relativeAge } from "@/lib/api/freshness";

/**
 * An age that actually advances (BB-203).
 *
 * The bug this fixes: `relativeAge()` was evaluated once, server-side, and the
 * resulting string was baked into the HTML. An hour later a badge still read
 * "just now" about hour-old data — taking the one element whose job is to let a
 * reader detect staleness and making it assert the opposite. Worse than showing
 * no age at all, because a missing badge invites a reload while a confident one
 * suppresses it.
 *
 * `initial` is the server-rendered string and is used verbatim for the first
 * paint, so hydration matches exactly; the timer then takes over. Without it,
 * server and client would compute against different clocks and React would warn.
 */
export function RelativeTime({
  iso,
  initial,
  /** 15s: `relativeAge` is minute-granular, so this is prompt without churning. */
  tickMs = 15_000,
}: {
  iso: string;
  initial: string;
  tickMs?: number;
}) {
  const [label, setLabel] = useState(initial);

  useEffect(() => {
    const update = () => setLabel(relativeAge(new Date(iso)));
    // Correct immediately: the server string is already a little stale by the
    // time it reaches the browser.
    update();
    const timer = setInterval(update, tickMs);
    return () => clearInterval(timer);
  }, [iso, tickMs]);

  // No transition and no animation: this is text a reader may be mid-sentence
  // through, and DESIGN-BOOK.md §6 prohibits animating a value being read.
  return <>{label}</>;
}
