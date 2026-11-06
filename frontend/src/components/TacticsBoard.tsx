// The chalk tactics board: the one bold element of the interface.
import type { PlayerOut, TeamOut } from "../lib/api";
import { eur, surname } from "../lib/format";
import { positions } from "../lib/formations";

interface Props {
  team: TeamOut | null;
  formation?: string | null;
  bestIds?: Set<number>;        // when showing an alternative: players not in the best team get a marker ring
  ownIds?: Set<number>;         // club improvement: the club's own players show "Own player" instead of a price
  selectedId?: number | null;
  onSelect?: (p: PlayerOut) => void;
  emptyText?: string;
}

export function PitchLines() {
  const c = "#EEF2EF";
  return (
    <svg viewBox="0 0 100 150" className="absolute inset-0 h-full w-full" aria-hidden="true">
      <g fill="none" stroke={c} strokeOpacity="0.55" strokeWidth="0.45" strokeLinecap="round">
        <rect x="3" y="3" width="94" height="144" rx="0.6" />
        <line x1="3" y1="75" x2="97" y2="75" />
        <circle cx="50" cy="75" r="12.6" />
        <rect x="20.4" y="3" width="59.2" height="23.6" />
        <rect x="36.5" y="3" width="27" height="7.9" />
        <rect x="20.4" y="123.4" width="59.2" height="23.6" />
        <rect x="36.5" y="139.1" width="27" height="7.9" />
        <path d="M 40.4 26.6 A 12.6 12.6 0 0 0 59.6 26.6" />
        <path d="M 40.4 123.4 A 12.6 12.6 0 0 1 59.6 123.4" />
      </g>
      <g fill={c} fillOpacity="0.55">
        <circle cx="50" cy="75" r="0.7" />
        <circle cx="50" cy="18.7" r="0.6" />
        <circle cx="50" cy="131.3" r="0.6" />
      </g>
    </svg>
  );
}

export default function TacticsBoard({ team, formation, bestIds, ownIds, selectedId, onSelect, emptyText }: Props) {
  const xy = team ? positions(team.players, formation) : new Map();
  return (
    <div className="relative mx-auto aspect-[2/3] w-full max-w-[520px] overflow-hidden rounded-lg bg-board">
      <PitchLines />
      {!team && (
        <p className="condensed absolute inset-x-8 top-1/2 -translate-y-1/2 text-center text-2xl font-semibold text-chalk/80">
          {emptyText ?? "Set a budget and a formation, then find the best team."}
        </p>
      )}
      {team?.players.map((p) => {
        const [x, y] = xy.get(p.player_id) ?? [50, 50];
        const selected = p.player_id === selectedId;
        const changed = bestIds && !bestIds.has(p.player_id);
        return (
          <button
            key={p.player_id}
            type="button"
            onClick={() => onSelect?.(p)}
            aria-pressed={selected}
            aria-label={`${p.slot}: ${p.name}, score ${p.score.toFixed(1)}, ${ownIds?.has(p.player_id) ? "own player" : `value ${eur(p.price_eur)}`}`}
            className="group absolute flex w-[22%] -translate-x-1/2 -translate-y-1/2 flex-col items-center"
            style={{ left: `${x}%`, top: `${y}%` }}
          >
            <span
              className={[
                "condensed num flex aspect-square w-[clamp(2.4rem,11vw,3.6rem)] items-center justify-center rounded-full text-[clamp(1rem,4.4vw,1.45rem)] font-bold transition-colors",
                selected ? "bg-marker text-board" : "bg-board-deep text-chalk group-hover:bg-board-line",
                changed ? "ring-[3px] ring-marker" : "ring-2 ring-chalk/70",
              ].join(" ")}
            >
              {Math.round(p.score)}
            </span>
            <span className="narrow mt-1 max-w-full truncate text-[clamp(0.7rem,2.6vw,0.85rem)] font-semibold text-chalk">
              {surname(p.name)}
            </span>
            <span className="num text-[clamp(0.62rem,2.2vw,0.72rem)] text-chalk-dim">
              {ownIds?.has(p.player_id) ? "Own player" : eur(p.price_eur)}
            </span>
          </button>
        );
      })}
    </div>
  );
}
