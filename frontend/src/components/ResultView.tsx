// Shows an optimization result: tabs for the best team and its alternatives, the board, cost bar and table.
import { useMemo, useState } from "react";
import type { OptimizeResponse, PlayerOut } from "../lib/api";
import { eur } from "../lib/format";
import TacticsBoard from "./TacticsBoard";
import TeamTable from "./TeamTable";
import PlayerDetail from "./PlayerDetail";

interface Props { result: OptimizeResponse | null; formation?: string | null; loading?: boolean; emptyText?: string; }

export default function ResultView({ result, formation, loading, emptyText }: Props) {
  const [tab, setTab] = useState(0);
  const [selected, setSelected] = useState<PlayerOut | null>(null);

  const teams = useMemo(() => (result?.team ? [result.team, ...result.alternatives] : []), [result]);
  const bestIds = useMemo(() => new Set(result?.team?.players.map((p) => p.player_id) ?? []), [result]);
  const i = Math.min(tab, Math.max(teams.length - 1, 0));
  const team = teams[i] ?? null;
  const select = (p: PlayerOut) => setSelected((s) => (s?.player_id === p.player_id ? null : p));

  // reset tab and selection when a new result arrives
  const [seen, setSeen] = useState(result);
  if (seen !== result) { setSeen(result); setTab(0); setSelected(null); }

  const used = team && result ? Math.min(100, (team.cost_eur / result.budget_eur) * 100) : 0;

  return (
    <div className="space-y-5" aria-busy={loading}>
      {teams.length > 1 && (
        <div role="tablist" aria-label="Teams" className="flex flex-wrap gap-2">
          {teams.map((t, k) => (
            <button
              key={k}
              role="tab"
              type="button"
              aria-selected={k === i}
              onClick={() => { setTab(k); setSelected(null); }}
              className={[
                "rounded-md border px-3 py-1.5 text-sm font-semibold",
                k === i ? "border-board bg-board text-chalk" : "border-rule bg-surface-raised text-ink hover:bg-surface-sunk",
              ].join(" ")}
            >
              {k === 0 ? "Best team" : `Alternative ${k}`}
              <span className="num ml-2 font-normal opacity-80">{t.total_score.toFixed(1)}</span>
            </button>
          ))}
        </div>
      )}

      {/* wide screens: board and totals on the left, details and the table on the right */}
      <div className="grid items-start gap-6 min-[1700px]:grid-cols-[minmax(0,430px)_minmax(0,1fr)]">
      <div className="space-y-4">
      <div className={loading ? "opacity-60 transition-opacity" : "transition-opacity"}>
        <TacticsBoard
          team={team}
          formation={formation}
          bestIds={i > 0 ? bestIds : undefined}
          selectedId={selected?.player_id}
          onSelect={select}
          emptyText={loading ? "Finding the best team…" : emptyText}
        />
      </div>

      {team && result && (
          <div className="mx-auto max-w-[520px]">
            <div className="flex items-baseline justify-between gap-4">
              <p>
                <span className="condensed num text-4xl font-bold">{team.total_score.toFixed(1)}</span>
                <span className="ml-2 text-sm text-ink-soft">total score of {team.players.length} players</span>
              </p>
              <p className="text-right text-sm text-ink-soft">
                <span className="num font-semibold text-ink">{eur(team.cost_eur)}</span> of {eur(result.budget_eur)}
              </p>
            </div>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-sunk" role="img"
                 aria-label={`Uses ${Math.round(used)}% of the budget`}>
              <div className="h-full rounded-full bg-board" style={{ width: `${used}%` }} />
            </div>
            <p className="mt-1 text-sm text-ink-soft">
              {eur(result.budget_eur - team.cost_eur)} left. Chosen from {result.eligible_players.toLocaleString("en")} eligible players
              in {Math.round(result.solve_time_ms)} ms
            </p>
            {i > 0 && (
              <p className="mt-2 text-sm text-ink-soft">
                Players with a yellow ring are not in the best team.
              </p>
            )}
          </div>
      )}
      </div>

      {team && result && (
        <div className="min-w-0 space-y-4">
          {selected && <PlayerDetail p={selected} onClose={() => setSelected(null)} />}
          <div className="sheet p-3 sm:p-4">
            <TeamTable players={team.players} selectedId={selected?.player_id} onSelect={select}
                       bestIds={i > 0 ? bestIds : undefined} />
          </div>
          {result.notes.length > 0 && (
            <ul className="space-y-1 text-sm text-ink-soft">
              {result.notes.map((n) => <li key={n}>{n}</li>)}
            </ul>
          )}
        </div>
      )}
      </div>
    </div>
  );
}
