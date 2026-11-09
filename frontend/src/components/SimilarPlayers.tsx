// Players with the closest statistical profile in the same role, with price, age and league filters.
// Used on the player page and, as "replacements", in Improve my club.
import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, League, SimilarOut } from "../lib/api";
import { AcrossLeaguesToggle, useAdjustment } from "../lib/adjustment";
import { eur, moneyText, parseMoney } from "../lib/format";

interface Props {
  playerId: number;
  maxPriceEur?: number | null;   // starting price limit (e.g. the club's budget)
  excludeIds?: number[];         // e.g. the club's own squad
  limit?: number;
  compact?: boolean;             // fewer details, for side panels
}

export default function SimilarPlayers({ playerId, maxPriceEur = null, excludeIds = [], limit = 10, compact = false }: Props) {
  const adjustment = useAdjustment();
  const [leagues, setLeagues] = useState<League[]>([]);
  const [price, setPrice] = useState(maxPriceEur ? moneyText(maxPriceEur) : "");
  const [age, setAge] = useState("");
  const [league, setLeague] = useState("");
  const [adjusted, setAdjusted] = useState(false);
  const [applied, setApplied] = useState({ price: maxPriceEur, age: null as number | null, league: null as number | null });
  const [data, setData] = useState<SimilarOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const excludeKey = excludeIds.join(",");

  useEffect(() => { api.leagues().then(setLeagues).catch(() => setLeagues([])); }, []);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    api.similar(playerId, {
      limit, max_price_eur: applied.price, max_age: applied.age, league_id: applied.league ? [applied.league] : [],
      exclude_id: excludeKey ? excludeKey.split(",").map(Number) : [], score: adjusted && adjustment?.active ? "adjusted" : "within",
    })
      .then((d) => { if (live) setData(d); })
      .catch((e) => { if (live) { setData(null); setError(e instanceof ApiError ? e.message : "Could not find similar players."); } })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [playerId, limit, applied, excludeKey, adjusted, adjustment?.active]);

  function apply(e: FormEvent) {
    e.preventDefault();
    const p = price.trim() ? parseMoney(price) : null;
    if (price.trim() && (p == null || (p < 10_000 && !/[km]/i.test(price)))) {
      setFormError("Write the price with a unit, for example 2m or 500k.");
      return;
    }
    const a = age.trim() ? Number(age) : null;
    if (a != null && (!Number.isInteger(a) || a < 16 || a > 45)) { setFormError("The oldest age must be a whole number from 16 to 45."); return; }
    setFormError(null);
    setApplied({ price: p, age: a, league: league ? Number(league) : null });
  }

  const uid = `sim${playerId}`;
  return (
    <div className="space-y-4">
      <form onSubmit={apply} className="flex flex-wrap items-end gap-3" aria-label="Similar player filters">
        <div className="w-28">
          <label htmlFor={`${uid}-price`} className="label">Highest price</label>
          <input id={`${uid}-price`} className="field" placeholder="Any" value={price} onChange={(e) => setPrice(e.target.value)} />
        </div>
        <div className="w-24">
          <label htmlFor={`${uid}-age`} className="label">Oldest age</label>
          <input id={`${uid}-age`} className="field" inputMode="numeric" placeholder="Any" value={age} onChange={(e) => setAge(e.target.value)} />
        </div>
        <div className="min-w-[10rem] flex-1">
          <label htmlFor={`${uid}-league`} className="label">League</label>
          <select id={`${uid}-league`} className="field" value={league} onChange={(e) => setLeague(e.target.value)}>
            <option value="">Any league</option>
            {leagues.filter((l) => l.scored_players > 0).map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        </div>
        <button type="submit" className="btn-quiet">Apply</button>
      </form>
      {formError && <p role="alert" className="text-sm text-signal">{formError}</p>}
      {!compact && <AcrossLeaguesToggle checked={adjusted} onChange={setAdjusted} status={adjustment} />}

      {error ? <p role="alert" className="text-sm text-signal">{error}</p>
        : loading && !data ? <p className="text-sm text-ink-soft">Finding similar players…</p>
        : data && data.results.length === 0 ? (
          <p className="rounded-md bg-surface-sunk p-4 text-sm">
            No player in this role matches the filters. Try a higher price, an older age or any league.
          </p>
        ) : data && (
          <>
            <ol className={`divide-y divide-rule rounded-lg border border-rule bg-surface-raised ${loading ? "opacity-60" : ""}`}
                aria-label={`Players similar to ${data.player.name}`}>
              {data.results.map((r) => (
                <li key={r.player_id} className="flex flex-wrap items-center gap-x-5 gap-y-1 px-4 py-3">
                  <span className="w-14 shrink-0" title="Similarity of the statistical profile, 0 to 100">
                    <span className="num block text-lg font-bold leading-tight">{Math.round(r.similarity)}</span>
                    <span className="block h-1.5 rounded-full bg-surface-sunk">
                      <span className="block h-1.5 rounded-full bg-board" style={{ width: `${r.similarity}%` }} />
                    </span>
                  </span>
                  <span className="min-w-[12rem] flex-1">
                    <Link to={`/players/${r.player_id}`} className="font-semibold underline-offset-4 hover:underline">{r.name}</Link>
                    <span className="block text-xs text-ink-faint">{r.club}, {r.league}. Age {r.age ?? "–"}{r.reliability === "low" ? ", few minutes" : ""}</span>
                    {!compact && (r.stronger_in.length > 0 || r.weaker_in.length > 0) && (
                      <span className="mt-0.5 block text-xs text-ink-soft">
                        {r.stronger_in.length > 0 && <>Better: {r.stronger_in.map((d) => d.metric).join(", ")}. </>}
                        {r.weaker_in.length > 0 && <>Weaker: {r.weaker_in.map((d) => d.metric).join(", ")}.</>}
                      </span>
                    )}
                  </span>
                  <span className="num w-16 text-right">
                    <span className="font-semibold">{r.score?.toFixed(1) ?? "–"}</span>
                    <span className="block text-xs text-ink-faint">score</span>
                  </span>
                  <span className="num w-16 text-right">
                    <span className="font-semibold">{eur(r.price_eur)}</span>
                    <span className="block text-xs text-ink-faint">value</span>
                  </span>
                </li>
              ))}
            </ol>
            <p className="text-xs text-ink-faint">
              Compared on {data.metrics.length} statistics for the role, weighted like the score
              ({data.metrics.slice(0, 3).join(", ").toLowerCase()} count most). Similar means he plays the same way
              compared with his own league, not that he is as good: check the score
              {adjustment?.active ? " and use “Compare across leagues” for players from different leagues" : ""}.
              {data.candidates > data.results.length && ` ${data.candidates} players matched the filters.`}
            </p>
          </>
        )}
    </div>
  );
}
