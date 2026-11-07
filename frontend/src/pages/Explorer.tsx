// Player explorer: every scored player, filtered and sorted. Filters live in the URL.
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError, League, PlayerPage, PlayerQuery, Role, SortKey } from "../lib/api";
import { useCompare } from "../lib/compare";
import AssistantBox from "../components/AssistantBox";
import { AcrossLeaguesToggle, useAdjustment } from "../lib/adjustment";
import type { Interpretation } from "../lib/api";
import { eur, moneyText, num, parseMoney, ROLE_NAMES, signed } from "../lib/format";

const ROLES: Role[] = ["GK", "CB", "FB", "CM", "AW", "ST"];
const PAGE = 50;

const COLUMNS: { key: SortKey | null; label: string; align?: "right" }[] = [
  { key: "name", label: "Player" },
  { key: null, label: "Club 2024/25" },
  { key: "age", label: "Age", align: "right" },
  { key: "score", label: "Score", align: "right" },  // relabelled below when adjusted
  { key: "price_eur", label: "Value", align: "right" },
  { key: "value_for_money", label: "Value for money", align: "right" },
  { key: "minutes", label: "Minutes 24/25", align: "right" },
  { key: "minutes_next", label: "Minutes 25/26", align: "right" },
];

function toQuery(sp: URLSearchParams, adjustedActive: boolean): PlayerQuery {
  const int = (k: string) => (sp.get(k) ? Number(sp.get(k)) : undefined);
  return {
    score: adjustedActive && sp.get("within") !== "1" ? "adjusted" : "within",
    q: sp.get("q") ?? undefined,
    role: sp.getAll("role") as Role[],
    league_id: sp.getAll("league").map(Number),
    age_min: int("age_min"), age_max: int("age_max"),
    max_price_eur: sp.get("max_price") ? parseMoney(sp.get("max_price")!) ?? undefined : undefined,
    min_minutes: sp.get("low") === "1" ? 450 : 900,
    min_minutes_next: sp.get("recent") === "1" ? 900 : 0,
    sort: (sp.get("sort") as SortKey) ?? "score",
    order: (sp.get("order") as "asc" | "desc") ?? "desc",
    limit: PAGE, offset: int("offset") ?? 0,
  };
}

export default function Explorer() {
  const [sp, setSp] = useSearchParams();
  const [leagues, setLeagues] = useState<League[]>([]);
  const [page, setPage] = useState<PlayerPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [text, setText] = useState(sp.get("q") ?? "");
  const [price, setPrice] = useState(sp.get("max_price") ?? "");
  const [askKey, setAskKey] = useState(0);
  const compare = useCompare();
  const adjustment = useAdjustment();
  const query = useMemo(() => toQuery(sp, !!adjustment?.active), [sp, adjustment]);

  const set = (changes: Record<string, string | string[] | null>, keepOffset = false) => {
    setSp((prev) => {
      const next = new URLSearchParams(prev);
      for (const [k, v] of Object.entries(changes)) {
        next.delete(k);
        if (Array.isArray(v)) v.forEach((x) => next.append(k, x));
        else if (v) next.set(k, v);
      }
      if (!keepOffset) next.delete("offset");
      return next;
    }, { replace: true });
  };

  useEffect(() => { api.leagues().then(setLeagues).catch(() => {}); }, []);

  // search box: wait until typing pauses
  useEffect(() => {
    const t = setTimeout(() => { if ((sp.get("q") ?? "") !== text.trim()) set({ q: text.trim() || null }); }, 300);
    return () => clearTimeout(t);
  }, [text]);

  useEffect(() => {
    if (!adjustment) return; // wait until we know which score to use, to avoid a second search
    let live = true;
    setLoading(true);
    api.players(query)
      .then((p) => { if (live) { setPage(p); setError(null); } })
      .catch((e) => { if (live) setError(e instanceof ApiError ? e.message : "Could not load players."); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [query, adjustment]);

  const toggleIn = (k: string, v: string) => {
    const cur = sp.getAll(k);
    set({ [k]: cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v] });
  };
  const sortBy = (k: SortKey) => {
    const same = query.sort === k;
    const order = same ? (query.order === "desc" ? "asc" : "desc") : k === "name" || k === "age" || k === "price_eur" ? "asc" : "desc";
    set({ sort: k, order });
  };
  function applyReading(r: Interpretation) {
    const f = r.filters;
    const next = new URLSearchParams();
    f.roles.forEach((x) => next.append("role", x));
    r.league_ids.forEach((id) => next.append("league", String(id)));
    if (f.age_min != null) next.set("age_min", String(f.age_min));
    if (f.age_max != null) next.set("age_max", String(f.age_max));
    if (f.max_price_eur) next.set("max_price", moneyText(f.max_price_eur));
    if (f.still_playing) next.set("recent", "1");
    if (f.include_low_minutes) next.set("low", "1");
    setText(""); setPrice(f.max_price_eur ? moneyText(f.max_price_eur) : "");
    setSp(next, { replace: false });
    setAskKey((k) => k + 1); // remount the age boxes so they show the new values
  }
  const ignoredHere = (r: Interpretation) =>
    r.understood.filter((u) => u.startsWith("Budget") || u.startsWith("Formation") || u.endsWith("nationality")
      || u.startsWith("Nationality"));

  const priceError = price.trim() && parseMoney(price) == null ? "Write it like 3m or 750k." : null;
  const offset = query.offset ?? 0;
  const chip = (on: boolean) => [
    "rounded-md border px-3 py-1.5 text-sm font-semibold",
    on ? "border-board bg-board text-chalk" : "border-rule bg-surface-raised hover:bg-surface-sunk",
  ].join(" ");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="condensed text-4xl font-bold leading-tight">Players</h1>
        <p className="mt-1 text-ink-soft">Every player with a 2024/25 score. Click a name for the full profile.</p>
      </div>

      <AssistantBox page="players" placeholder="Describe the player, e.g. a young left-back under €2m who still plays"
                    examples={["striker from Serie A under 25", "cheap experienced goalkeeper", "млад штопер до 3 милиони"]}
                    ignoredHere={ignoredHere} onApply={applyReading} />

      <section aria-label="Filters" className="space-y-4" key={askKey}>
        <div className="flex flex-wrap items-end gap-4">
          <div className="w-full max-w-xs">
            <label htmlFor="q" className="label">Name</label>
            <input id="q" type="search" className="field" placeholder="For example Modric" value={text}
                   onChange={(e) => setText(e.target.value)} />
          </div>
          <div className="w-24">
            <label htmlFor="age_min" className="label">Youngest</label>
            <input id="age_min" className="field num" inputMode="numeric" placeholder="Any" defaultValue={sp.get("age_min") ?? ""}
                   onBlur={(e) => set({ age_min: e.target.value.trim() || null })} />
          </div>
          <div className="w-24">
            <label htmlFor="age_max" className="label">Oldest</label>
            <input id="age_max" className="field num" inputMode="numeric" placeholder="Any" defaultValue={sp.get("age_max") ?? ""}
                   onBlur={(e) => set({ age_max: e.target.value.trim() || null })} />
          </div>
          <div className="w-36">
            <label htmlFor="max_price" className="label">Highest value</label>
            <input id="max_price" className="field num" placeholder="No limit" value={price}
                   aria-invalid={!!priceError} onChange={(e) => setPrice(e.target.value)}
                   onBlur={() => !priceError && set({ max_price: price.trim() || null })} />
          </div>
          <div className="space-y-1 pb-1 text-sm">
            <label className="flex items-center gap-2">
              <input type="checkbox" className="h-4 w-4 accent-board" checked={sp.get("recent") === "1"}
                     onChange={(e) => set({ recent: e.target.checked ? "1" : null })} />
              Still playing: 900+ minutes in 2025/26
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" className="h-4 w-4 accent-board" checked={sp.get("low") === "1"}
                     onChange={(e) => set({ low: e.target.checked ? "1" : null })} />
              Include 450–899 minutes (less reliable)
            </label>
          </div>
        </div>
        {priceError && <p className="text-xs font-medium text-signal">{priceError}</p>}
        <AcrossLeaguesToggle checked={sp.get("within") !== "1"} status={adjustment}
                             onChange={(v) => set({ within: v ? null : "1" })} />
        <fieldset>
          <legend className="label">Role</legend>
          <div className="flex flex-wrap gap-2">
            {ROLES.map((r) => (
              <button key={r} type="button" aria-pressed={sp.getAll("role").includes(r)} className={chip(sp.getAll("role").includes(r))}
                      onClick={() => toggleIn("role", r)}>{ROLE_NAMES[r]}</button>
            ))}
          </div>
        </fieldset>
        {leagues.length > 0 && (
          <fieldset>
            <legend className="label">League</legend>
            <div className="flex flex-wrap gap-2">
              {leagues.map((l) => (
                <button key={l.id} type="button" aria-pressed={sp.getAll("league").includes(String(l.id))}
                        className={chip(sp.getAll("league").includes(String(l.id)))} onClick={() => toggleIn("league", String(l.id))}>
                  {l.name} <span className="num font-normal opacity-70">{l.scored_players}</span>
                </button>
              ))}
            </div>
          </fieldset>
        )}
      </section>

      {error && <p role="alert" className="rounded-md bg-signal-soft px-3 py-2 text-signal">{error}</p>}

      {page && (
        <section aria-label="Players" className={loading ? "opacity-60" : ""}>
          <p className="mb-2 text-sm text-ink-soft" aria-live="polite">
            {page.total === 0 ? "No players match these filters." :
              `${num(page.total)} players. Showing ${offset + 1}–${Math.min(offset + PAGE, page.total)}.`}
          </p>
          {page.total > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[960px] border-collapse text-sm">
                <thead>
                  <tr className="border-b border-rule text-left text-ink-soft">
                    {COLUMNS.map((c) => (
                      <th key={c.label} scope="col" className={`py-2 pr-3 font-medium ${c.align === "right" ? "text-right" : ""}`}
                          aria-sort={c.key && query.sort === c.key ? (query.order === "asc" ? "ascending" : "descending") : undefined}>
                        {c.key ? (
                          <button type="button" onClick={() => sortBy(c.key!)} className="font-medium hover:text-ink">
                            {c.key === "score" && query.score === "adjusted" ? "Adjusted score" : c.label}
                            {query.sort === c.key && (query.order === "asc" ? " ↑" : " ↓")}
                          </button>
                        ) : c.label}
                      </th>
                    ))}
                    <th scope="col" className="py-2 text-right font-medium">Compare</th>
                  </tr>
                </thead>
                <tbody>
                  {page.items.map((p) => (
                    <tr key={p.player_id} className="border-b border-rule/70 hover:bg-surface-sunk">
                      <td className="py-2 pr-3">
                        <Link to={`/players/${p.player_id}`} className="font-semibold underline-offset-4 hover:underline">{p.name}</Link>
                        <span className="block text-xs text-ink-faint">{ROLE_NAMES[p.role]}{p.nationality && `, ${p.nationality}`}</span>
                      </td>
                      <td className="py-2 pr-3">{p.club}<span className="block text-xs text-ink-faint">{p.league}</span></td>
                      <td className="num py-2 pr-3 text-right">{p.age ?? "–"}</td>
                      <td className="num py-2 pr-3 text-right font-semibold">{p.score.toFixed(1)}</td>
                      <td className="num py-2 pr-3 text-right">{eur(p.price_eur)}</td>
                      <td className="num py-2 pr-3 text-right">{signed(p.value_for_money)}</td>
                      <td className="num py-2 pr-3 text-right">{num(p.minutes)}</td>
                      <td className="num py-2 pr-3 text-right">{num(p.minutes_next)}</td>
                      <td className="py-2 text-right">
                        <input type="checkbox" className="h-4 w-4 accent-board" aria-label={`Compare ${p.name}`}
                               checked={compare.has(p.player_id)} disabled={!compare.has(p.player_id) && compare.full}
                               onChange={() => compare.toggle({ id: p.player_id, name: p.name, role: p.role })} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {page.total > PAGE && (
            <div className="mt-4 flex gap-2">
              <button type="button" className="btn-quiet" disabled={offset === 0}
                      onClick={() => set({ offset: String(Math.max(0, offset - PAGE)) }, true)}>Previous</button>
              <button type="button" className="btn-quiet" disabled={offset + PAGE >= page.total}
                      onClick={() => set({ offset: String(offset + PAGE) }, true)}>Next</button>
            </div>
          )}
          <p className="mt-4 text-xs text-ink-faint">
            {query.score === "adjusted" && "Adjusted score: the 2024/25 score corrected for league strength, so leagues can be compared. "}
            Value for money: score points above (+) or below (−) what players of the same role and league usually score at that price.
            Blank where price explains too little of the score to say.
          </p>
        </section>
      )}
    </div>
  );
}
