// One club-improvement result: plan tabs, the gain, the signings and the XI before and after.
// Used on the Improve page and for saved improvement plans.
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { ImproveRequest, ImproveResponse } from "../lib/api";
import { eur, ROLE_NAMES, signed } from "../lib/format";
import { replacements } from "../lib/improve";
import TacticsBoard from "./TacticsBoard";

export default function ImproveResult({ result, request }: { result: ImproveResponse; request: ImproveRequest }) {
  const [tab, setTab] = useState(0);
  const plans = result.team ? [result.team, ...result.alternatives] : [];
  const plan = plans[Math.min(tab, Math.max(plans.length - 1, 0))] ?? null;
  const ownedIds = useMemo(() => new Set(request.owned_player_ids), [request]);
  const repl = useMemo(() => (plan && result.current ? replacements(result.current.players, plan.players) : new Map()), [plan, result]);
  if (!plan) return null;
  const signings = plan.players.filter((p) => p.signing);
  const gain = result.current ? Math.round((plan.total_score - result.current.total_score) * 10) / 10 : null;

  return (
    <div className="space-y-6">
      {plans.length > 1 && (
        <div role="tablist" aria-label="Plans" className="flex flex-wrap gap-2">
          {plans.map((t, k) => (
            <button key={k} role="tab" type="button" aria-selected={k === tab} onClick={() => setTab(k)}
                    className={["rounded-md border px-3 py-1.5 text-sm font-semibold",
                      k === tab ? "border-board bg-board text-chalk" : "border-rule bg-surface-raised hover:bg-surface-sunk"].join(" ")}>
              {k === 0 ? "Best plan" : `Alternative ${k}`}
              {result.current && <span className="num ml-2 font-normal opacity-80">{signed(t.total_score - result.current.total_score)}</span>}
            </button>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-end gap-x-10 gap-y-3">
        {gain != null && (
          <p>
            <span className="condensed num block text-6xl font-extrabold leading-none">{signed(gain)}</span>
            <span className="text-sm text-ink-soft">
              starting XI total score, from {result.current!.total_score.toFixed(1)} to {plan.total_score.toFixed(1)}
            </span>
          </p>
        )}
        <p className="text-sm text-ink-soft">
          <span className="num block text-2xl font-bold text-ink">{eur(plan.cost_eur)}</span>
          spent of {eur(result.budget_eur)}, {signings.length} of at most {request.max_signings ?? 2} signings
        </p>
      </div>

      {signings.length === 0 ? (
        <p className="rounded-md bg-surface-sunk p-4">
          No affordable signing is better than your current starters. This is your best XI as it is.
        </p>
      ) : (
        <ul className="divide-y divide-rule rounded-lg border border-rule bg-surface-raised" aria-label="Signings">
          {signings.map((p) => {
            const r = repl.get(p.player_id);
            return (
              <li key={p.player_id} className="flex flex-wrap items-center gap-x-6 gap-y-1 px-4 py-3">
                <span className="min-w-[14rem] flex-1">
                  <Link to={`/players/${p.player_id}`} className="font-semibold underline-offset-4 hover:underline">{p.name}</Link>
                  <span className="block text-xs text-ink-faint">
                    {ROLE_NAMES[p.role as keyof typeof ROLE_NAMES]}, age {p.age ?? "–"}. 2024/25: {p.club_2024_25} ({p.league})
                  </span>
                </span>
                <span className="text-sm text-ink-soft">
                  {r ? <>Replaces <span className="font-medium text-ink">{r.name}</span> ({r.score.toFixed(1)})</> : "Fills a gap"}
                </span>
                <span className="num w-28 text-right">
                  <span className="font-semibold">{p.score.toFixed(1)}</span>
                  {r && <span className="text-sm text-ink-soft"> ({signed(p.score - r.score)})</span>}
                  <span className="block text-xs text-ink-faint">{eur(p.price_eur)}</span>
                </span>
              </li>
            );
          })}
        </ul>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <figure>
          <figcaption className="mb-2 font-semibold">Your XI now</figcaption>
          {result.current
            ? <TacticsBoard team={result.current} formation={request.formation} ownIds={ownedIds} />
            : <p className="rounded-md bg-surface-sunk p-4 text-sm">Your squad cannot fill this formation on its own.</p>}
        </figure>
        <figure>
          <figcaption className="mb-2 font-semibold">With the signings <span className="font-normal text-ink-soft">(yellow ring = new)</span></figcaption>
          <TacticsBoard team={plan} formation={request.formation} bestIds={ownedIds} ownIds={ownedIds} />
        </figure>
      </div>

      {(result.unscored.length > 0 || result.notes.length > 0) && (
        <ul className="space-y-1 text-sm text-ink-soft">
          {result.notes.map((n) => <li key={n}>{n}</li>)}
          {result.unscored.length > 0 && <li>Left out without a score: {result.unscored.map((u) => u.name).join(", ")}.</li>}
        </ul>
      )}
    </div>
  );
}
