"use client";

import { useEffect, useState } from "react";

/**
 * Light / dark / system toggle (BB-102 §102.5).
 *
 * "system" means: remove the stamp and let `prefers-color-scheme` decide. An
 * explicit choice stamps `data-theme` on the root element, which every token
 * file declares a scope for, so the choice wins over the OS in both directions.
 *
 * The flash-of-wrong-theme problem is solved in the layout, not here — see
 * THEME_INIT_SCRIPT. By the time this component hydrates, the correct theme is
 * already painted; it only needs to read back what the script decided.
 */

export const THEME_STORAGE_KEY = "bb-theme";

export type ThemeChoice = "light" | "dark" | "system";

/**
 * Runs before first paint, inlined in <head>. Kept deliberately tiny and
 * dependency-free: it executes synchronously and blocks rendering.
 */
export const THEME_INIT_SCRIPT = `(function(){try{var c=localStorage.getItem("${THEME_STORAGE_KEY}");if(c==="light"||c==="dark"){document.documentElement.setAttribute("data-theme",c);}}catch(e){}})();`;

function apply(choice: ThemeChoice) {
  const root = document.documentElement;
  if (choice === "system") {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", choice);
  }
  try {
    if (choice === "system") localStorage.removeItem(THEME_STORAGE_KEY);
    else localStorage.setItem(THEME_STORAGE_KEY, choice);
  } catch {
    // Private mode or storage disabled: the toggle still works for this page.
  }
}

const OPTIONS: ReadonlyArray<{ value: ThemeChoice; label: string }> = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "System" },
];

export function ThemeToggle() {
  const [choice, setChoice] = useState<ThemeChoice>("system");

  // Read back what the init script already applied, so the control reflects
  // reality rather than resetting it.
  useEffect(() => {
    const stamped = document.documentElement.getAttribute("data-theme");
    setChoice(stamped === "light" || stamped === "dark" ? stamped : "system");
  }, []);

  return (
    <fieldset
      style={{
        border: "1px solid var(--bb-outline-variant)",
        borderRadius: "var(--bb-radius-sm)",
        padding: "var(--bb-space-2) var(--bb-space-3)",
        display: "flex",
        gap: "var(--bb-space-3)",
        alignItems: "center",
      }}
    >
      <legend className="bb-label-medium" style={{ color: "var(--bb-on-surface-variant)" }}>
        Theme
      </legend>
      {OPTIONS.map((option) => (
        <label
          key={option.value}
          className="bb-label-large"
          style={{ display: "flex", alignItems: "center", gap: "var(--bb-space-1)" }}
        >
          <input
            type="radio"
            name="bb-theme"
            value={option.value}
            checked={choice === option.value}
            onChange={() => {
              setChoice(option.value);
              apply(option.value);
            }}
          />
          {option.label}
        </label>
      ))}
    </fieldset>
  );
}
