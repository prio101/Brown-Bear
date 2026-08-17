import { Text } from "@/components/Text";
import type { Savings } from "@/lib/api/schemas";
import { count } from "@/lib/format";

/**
 * What the shared memory served, and what it actually saved (spec 003 §3.5 rev 2).
 *
 * The card is built around a distinction it would be easy — and flattering — to
 * collapse: **served is not saved**.
 *
 *   served    Content Brown Bear handed back. Always real, but retrieved chunks
 *             are ADDED to a prompt and cost input tokens, so serving a lot is
 *             not, on its own, a saving at all.
 *   avoided   Output tokens a provider never generated, counted only when a hit
 *             was served in place of a model call. In `inject` mode — the default
 *             — the model still answers and the gain is grounding, not spend.
 *
 * Presenting served volume as money saved would overstate the benefit in exactly
 * the way the flat input rate overstated the cost, which is the bug this whole
 * change exists to fix. So the two are shown side by side, and when they diverge
 * the card says why rather than letting the bigger number speak for itself.
 */

function Figure({
  label,
  value,
  hint,
  emphasis,
}: {
  label: string;
  value: string;
  hint: string;
  emphasis?: boolean;
}) {
  return (
    <div className="bb-savings-figure" data-emphasis={emphasis ? "true" : undefined}>
      <span className="bb-label-medium bb-savings-label">{label}</span>
      <span className="bb-savings-value bb-tabular">{value}</span>
      <span className="bb-body-small bb-savings-hint">{hint}</span>
    </div>
  );
}

export function SavingsCard({ savings }: { savings: Savings }) {
  const { tokens_served, tokens_avoided, cost_avoided_usd, hit_rate } = savings;

  // The honest headline. Serving a great deal while avoiding nothing is the
  // normal state in inject mode, and the card has to say so rather than let the
  // served figure imply a saving that did not happen.
  const servedButNotAvoided = tokens_served > 0 && tokens_avoided === 0;

  return (
    <div className="bb-savings">
      <div className="bb-savings-grid">
        <Figure
          label="Served from memory"
          value={count(tokens_served)}
          hint={`${count(savings.chunks_served)} chunks over ${savings.lookups} lookups`}
        />
        <Figure
          label="Provider tokens avoided"
          value={count(tokens_avoided)}
          hint={
            savings.blocking_hits === 0
              ? "no hits served in place of a model call"
              : `${savings.blocking_hits} blocking hit${savings.blocking_hits === 1 ? "" : "s"}`
          }
          emphasis
        />
        <Figure
          label="Cost avoided"
          value={`$${cost_avoided_usd.toFixed(4)}`}
          hint="output rate only — input is unknowable here"
        />
        <Figure
          label="Hit rate"
          value={hit_rate === null ? "—" : `${(hit_rate * 100).toFixed(1)}%`}
          hint={hit_rate === null ? "no lookups yet" : `${savings.hits} of ${savings.lookups}`}
        />
      </div>

      {servedButNotAvoided ? (
        <Text role="body-small" className="bb-savings-note">
          The memory served {count(tokens_served)} tokens of context but avoided no
          provider calls. That is the expected result in the default{" "}
          <code>inject</code> mode: a cache hit is added as context and the model
          still answers, so you gain grounding rather than spend. Only{" "}
          <code>BB_CACHE_MODE=block</code> replaces a call outright.
        </Text>
      ) : null}

      <Text role="body-small" className="bb-savings-note">
        {savings.basis}
      </Text>
    </div>
  );
}
