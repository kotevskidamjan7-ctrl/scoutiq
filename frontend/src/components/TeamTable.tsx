import { Link } from "react-router-dom";
import type { PlayerOut } from "../lib/api";
import { eur, ROLE_NAMES } from "../lib/format";

interface Props { players: PlayerOut[]; selectedId?: number | null; onSelect?: (p: PlayerOut) => void; bestIds?: Set<number>; }

export default function TeamTable({ players, selectedId, onSelect, bestIds }: Props) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] border-collapse text-sm">
        <caption className="sr-only">Selected players</caption>
        <thead>
          <tr className="border-b border-rule text-left text-ink-soft">
            <th className="py-2 pr-3 font-medium">Position</th>
            <th className="py-2 pr-3 font-medium">Player</th>
            <th className="py-2 pr-3 text-right font-medium">Score</th>
            <th className="py-2 pr-3 text-right font-medium">Value</th>
            <th className="py-2 pr-3 text-right font-medium">Age</th>
            <th className="py-2 pr-3 font-medium">Club 2024/25</th>
            <th className="py-2 pr-3 text-right font-medium">Min. 24/25</th>
            <th className="py-2 text-right font-medium">Min. 25/26</th>
          </tr>
        </thead>
        <tbody>
          {players.map((p) => (
            <tr
              key={p.player_id}
              onClick={() => onSelect?.(p)}
              className={[
                "cursor-pointer border-b border-rule/70 hover:bg-surface-sunk",
                p.player_id === selectedId ? "bg-marker/20" : "",
              ].join(" ")}
            >
              <td className="py-2 pr-3 text-ink-soft">{p.slot}</td>
              <td className="py-2 pr-3">
                <Link to={`/players/${p.player_id}`} onClick={(e) => e.stopPropagation()}
                      className="font-semibold underline-offset-4 hover:underline">
                  {p.name}
                </Link>
                <span className="block text-xs text-ink-faint">
                  {ROLE_NAMES[p.role]}
                  {bestIds && !bestIds.has(p.player_id) && ", not in the best team"}
                  {p.position_consistent === false && ", listed in a different position in 2024/25"}
                </span>
              </td>
              <td className="num py-2 pr-3 text-right font-semibold">{p.score.toFixed(1)}</td>
              <td className="num py-2 pr-3 text-right">{eur(p.price_eur)}</td>
              <td className="num py-2 pr-3 text-right">{p.age ?? "–"}</td>
              <td className="py-2 pr-3">
                {p.club_2024_25}
                <span className="block text-xs text-ink-faint">{p.league}</span>
              </td>
              <td className="num py-2 pr-3 text-right">{p.minutes_2024_25.toLocaleString("en")}</td>
              <td className="num py-2 text-right">{p.minutes_2025_26.toLocaleString("en")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
