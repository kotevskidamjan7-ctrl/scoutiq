// League and nationality filters, shown as removable chips (set by the assistant).
import { useEffect, useState } from "react";
import { api, League } from "../lib/api";

let cache: League[] | null = null;

interface Props {
  leagueIds: number[];
  nationalities: string[];
  onChange: (leagueIds: number[], nationalities: string[]) => void;
}

export default function ScopeChips({ leagueIds, nationalities, onChange }: Props) {
  const [leagues, setLeagues] = useState<League[]>(cache ?? []);
  useEffect(() => {
    if (!cache) api.leagues().then((l) => { cache = l; setLeagues(l); }).catch(() => {});
  }, []);
  if (!leagueIds.length && !nationalities.length) return null;
  const name = (id: number) => leagues.find((l) => l.id === id)?.name ?? `League ${id}`;
  const chip = (label: string, remove: () => void) => (
    <li key={label} className="flex items-center gap-1 rounded-md bg-board py-1 pl-2 pr-1 text-sm font-medium text-chalk">
      {label}
      <button type="button" onClick={remove} aria-label={`Remove ${label}`}
              className="rounded px-1.5 text-chalk-dim hover:bg-board-line hover:text-chalk">×</button>
    </li>
  );
  return (
    <div>
      <p className="label">Only</p>
      <ul className="flex flex-wrap gap-1.5">
        {leagueIds.map((id) => chip(name(id), () => onChange(leagueIds.filter((x) => x !== id), nationalities)))}
        {nationalities.map((n) => chip(`${n} nationality`, () => onChange(leagueIds, nationalities.filter((x) => x !== n))))}
      </ul>
    </div>
  );
}
