import Link from "next/link";

/**
 * Primary navigation (DESIGN-BOOK.md §7).
 *
 * Navigation rail at medium and expanded, bottom bar at compact. Driven entirely
 * by CSS media queries rather than JS: the layout is known at render time, and a
 * client component here would ship JS to decide something the stylesheet already
 * knows.
 *
 * `current` is passed in rather than read from usePathname() so this stays a
 * server component.
 */

const DESTINATIONS = [
  { href: "/", label: "Overview", glyph: "◉" },
  { href: "/graph", label: "Graph", glyph: "◈" },
  { href: "/logs", label: "Logs", glyph: "≡" },
  { href: "/tokens", label: "Tokens", glyph: "∑" },
  { href: "/cache", label: "Cache", glyph: "⟳" },
  { href: "/collections", label: "Collections", glyph: "▤" },
  { href: "/settings", label: "Settings", glyph: "⚙" },
] as const;

export type NavRoute = (typeof DESTINATIONS)[number]["href"];

export function Nav({ current }: { current: NavRoute }) {
  return (
    <nav aria-label="Primary" className="bb-nav">
      <ul className="bb-nav-list">
        {DESTINATIONS.map(({ href, label, glyph }) => {
          const active = href === current;
          return (
            <li key={href}>
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className="bb-nav-link bb-interactive"
                data-active={active ? "true" : undefined}
              >
                <span aria-hidden="true" className="bb-nav-glyph">
                  {glyph}
                </span>
                <span className="bb-label-medium">{label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
