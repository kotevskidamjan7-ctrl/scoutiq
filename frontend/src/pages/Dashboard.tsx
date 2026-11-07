// Dashboard: what the data covers, and the best players the money can buy, laid out on the board.
import { ReactNode, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError, Dashboard as D, PlayerOut, PlayerRow, Role, TeamOut } from "../lib/api";
import { eur, num, ROLE_NAMES, signed } from "../lib/format";
import PageHeader from "../components/PageHeader";
import TacticsBoard from "../components/TacticsBoard";

const ROLES: Role[] = ["GK", "CB", "FB", "CM", "AW", "ST"];
const CAPS = [1_000_000, 3_000_000, 10_000_000];
const CAP_KEY = "scoutiq.dashboardCap";
const AGE_KEY = "scoutiq.dashboardMaxAge";
const AGES: (number | null)[] = [null, 27, 23];
const THRESHOLD = 0.9; // a league's scores are final once 90% of its regulars have full statistics
const XI_SLOTS: Record<Role, string[]> = {
  GK: ["GK"], CB: ["LCB", "RCB"], FB: ["LB", "RB"], CM: ["LCM", "CM", "RCM"], AW: ["LW", "RW"], ST: ["ST"],
};

const dateText = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "–";
const timeText = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "–";

function Segmented<T extends string | number | null>({ legend, options, value, onChange, label }: {
  legend: string; options: T[]; value: T; onChange: (v: T) => void; label: (v: T) => string;
}) {
  return (
    <fieldset>
      <legend className="label">{legend}</legend>
      <div className="flex gap-1 rounded-md bg-surface-sunk p-1">
        {options.map((o) => (
          <label key={String(o)} className={[
            "num cursor-pointer whitespace-nowrap rounded px-2.5 py-1 text-sm font-semibold has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-marker",
            value === o ? "bg-surface-raised shadow-sm" : "text-ink-soft",
          ].join(" ")}>
            <input type="radio" name={legend} className="sr-only" checked={value === o} onChange={() => onChange(o)} />
            {label(o)}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function Sheet({ title, note, actions, children, id }: { title: string; note?: ReactNode; actions?: ReactNode; children: ReactNode; id: string }) {
  return (
    <section aria-labelledby={id} className="sheet">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id={id} className="condensed text-2xl font-bold leading-tight">{title}</h2>
          {note && <p className="mt-1 max-w-2xl text-sm text-ink-soft">{note}</p>}
        </div>
        {actions}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

/** Six small bars: how many regulars the league has per position (one hue, labels below, exact counts on hover). */
function RoleBars({ roles, max }: { roles: Record<string, number>; max: number }) {
  return (
    <div className="flex items-end gap-1.5" role="img"
         aria-label={ROLES.map((r) => `${ROLE_NAMES[r]} ${roles[r] ?? 0}`).join(", ")}>
      {ROLES.map((r) => {
        const n = roles[r] ?? 0;
        return (
          <div key={r} className="flex w-6 flex-col items-center gap-0.5" title={`${ROLE_NAMES[r]}: ${n} regulars`}>
            <div className="flex h-7 w-full items-end">
              <div className="w-full rounded-t-[3px] bg-board" style={{ height: `${max ? Math.max(6, (n / max) * 100) : 0}%` }} />
            </div>
            <span className="text-[10px] font-semibold text-ink-faint">{r}</span>
          </div>
        );
      })}
    </div>
  );
}

function Bar({ value, max, label, mark }: { value: number; max: number; label: string; mark?: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="relative h-2 w-24 rounded-full bg-surface-sunk" role="img" aria-label={label}>
        <div className="absolute inset-y-0 left-0 rounded-full bg-board" style={{ width: `${Math.min(100, (value / max) * 100)}%` }} />
        {mark != null && <div className="absolute -inset-y-1 w-px bg-ink-faint" style={{ left: `${mark * 100}%` }} aria-hidden="true" />}
      </div>
    </div>
  );
}

function PickList({ picks, metric }: { picks: PlayerRow[]; metric: "vfm" | "score" }) {
  return (
    <ol>
      {picks.map((p) => (
        <li key={p.player_id} className="flex items-center gap-3 border-b border-rule/60 py-2 last:border-0">
          <span className="condensed num flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-board text-sm font-bold text-chalk ring-2 ring-chalk/70"
                aria-hidden="true">
            {metric === "vfm" ? signed(p.value_for_money, 0) : Math.round(p.score)}
          </span>
          <span className="min-w-0 flex-1">
            <Link to={`/players/${p.player_id}`} className="block truncate font-semibold underline-offset-4 hover:underline">{p.name}</Link>
            <span className="block truncate text-xs text-ink-faint">{p.club}, {p.league}. Age {p.age ?? "–"}</span>
          </span>
          <span className="num shrink-0 text-right text-sm">
            {eur(p.price_eur)}
            <span className="block text-xs text-ink-faint">
              {metric === "vfm" ? `${signed(p.value_for_money)} vs. price` : `score ${p.score.toFixed(1)}`}
            </span>
          </span>
        </li>
      ))}
    </ol>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [d, setD] = useState<D | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cap, setCapState] = useState<number>(() => {
    try { const v = Number(localStorage.getItem(CAP_KEY)); return CAPS.includes(v) ? v : 3_000_000; } catch { return 3_000_000; }
  });
  const setCap = (v: number) => { setCapState(v); try { localStorage.setItem(CAP_KEY, String(v)); } catch { /* not stored */ } };
  const [maxAge, setMaxAgeState] = useState<number | null>(() => {
    try { const v = localStorage.getItem(AGE_KEY); return v && AGES.includes(Number(v)) ? Number(v) : null; } catch { return null; }
  });
  const setMaxAge = (v: number | null) => {
    setMaxAgeState(v);
    try { if (v == null) localStorage.removeItem(AGE_KEY); else localStorage.setItem(AGE_KEY, String(v)); } catch { /* not stored */ }
  };
  useEffect(() => {
    api.dashboard(maxAge).then(setD).catch((e) => setError(e instanceof ApiError ? e.message : "Could not load the dashboard."));
  }, [maxAge]);

  // the best XI under the price limit: highest scores per position, laid out as a 4-3-3
  const xi = useMemo<{ team: TeamOut; missing: Role[] } | null>(() => {
    const lists = d?.budget_picks?.[String(cap)];
    if (!lists) return null;
    const players: PlayerOut[] = [];
    const missing: Role[] = [];
    for (const role of ROLES) {
      const slots = XI_SLOTS[role];
      const picks = (lists[role] ?? []).slice(0, slots.length);
      if (picks.length < slots.length) missing.push(role);
      picks.forEach((p, i) => players.push({
        slot: slots[i], player_id: p.player_id, name: p.name, role: p.role, score: p.score, price_eur: p.price_eur ?? 0,
        valuation_date: p.valuation_date, age: p.age, club_2024_25: p.club, league: p.league, minutes_2024_25: p.minutes,
        minutes_2025_26: p.minutes_next, reliability: p.reliability, position_consistent: p.position_consistent,
      }));
    }
    return {
      team: { players, total_score: players.reduce((a, p) => a + p.score, 0), cost_eur: players.reduce((a, p) => a + p.price_eur, 0) },
      missing,
    };
  }, [d, cap]);

  if (error) return <p role="alert" className="rounded-md bg-signal-soft px-3 py-2 text-signal">{error}</p>;
  if (!d) return <p className="text-ink-soft">Loading…</p>;

  const t = d.totals;
  const ready = d.leagues.filter((l) => l.status !== "no_data");
  const waiting = d.leagues.filter((l) => l.status === "no_data");
  const maxStrength = Math.max(1, ...ready.map((l) => l.strength ?? 0));
  const maxRole = Math.max(1, ...ready.flatMap((l) => Object.values(l.roles)));
  const adj = d.model.league_adjustment;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        subtitle={<>Scores from 2024/25, recent form from 2025/26. Market values from Transfermarkt, latest {dateText(t.latest_valuation_date)}.</>}
        actions={<Link to="/builder" className="btn-primary">Build a squad</Link>}>
        <dl className="mt-7 grid grid-cols-2 gap-y-5 border-t border-chalk/15 pt-5 lg:grid-cols-4">
          {[
            ["Players scored", num(t.players_scored), "with a 2024/25 score"],
            ["Regulars", num(t.regulars_scored), "900+ league minutes, 2024/25"],
            ["Still playing", num(t.still_playing), "900+ league minutes, 2025/26"],
            ["Leagues complete", `${t.leagues_complete}/${t.leagues_enabled}`, "statistics for 90%+ of regulars"],
          ].map(([label, value, note], i) => (
            <div key={label} className={`pr-4 ${i % 2 === 1 ? "pl-4 sm:pl-6" : ""} ${i > 0 ? "lg:border-l lg:border-chalk/15 lg:pl-6" : ""}`}>
              <dt className="text-sm text-chalk-dim">{label}</dt>
              <dd className="condensed num text-5xl font-extrabold leading-tight text-chalk">{value}</dd>
              <dd className="text-xs text-chalk-dim">{note}</dd>
            </div>
          ))}
        </dl>
      </PageHeader>

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(380px,460px)]">
        <div className="min-w-0 xl:col-start-1 xl:row-start-1">
          <Sheet id="leagues-title" title="Leagues"
                 note={d.strength_source ? `League strength: ${d.strength_source}, 2024/25. It drives the cross-league adjustment.` : undefined}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] border-collapse text-sm">
                <thead>
                  <tr className="border-b border-rule text-left text-ink-soft">
                    <th scope="col" className="py-2 pr-3 font-medium">League</th>
                    <th scope="col" className="py-2 pr-3 font-medium">Strength</th>
                    <th scope="col" className="py-2 pr-3 font-medium">Full statistics</th>
                    <th scope="col" className="py-2 pr-3 text-right font-medium">Regulars</th>
                    <th scope="col" className="py-2 pr-3 text-right font-medium">Median value</th>
                    <th scope="col" className="py-2 font-medium">Regulars by position</th>
                  </tr>
                </thead>
                <tbody>
                  {ready.map((l) => (
                    <tr key={l.id} className="border-b border-rule/60 last:border-0">
                      <td className="py-3 pr-3">
                        <Link to={`/players?league=${l.id}`} className="font-semibold underline-offset-4 hover:underline">{l.name}</Link>
                        <span className="flex items-center gap-1.5 text-xs text-ink-faint">
                          <span className={`h-2 w-2 rounded-full ${l.status === "complete" ? "bg-board" : "bg-marker"}`} aria-hidden="true" />
                          {l.status === "complete" ? `${l.country}, complete` : `${l.country}, still being fetched`}
                        </span>
                      </td>
                      <td className="py-3 pr-3">
                        {l.strength != null ? (
                          <div className="flex items-center gap-2">
                            <Bar value={l.strength} max={maxStrength} label={`Strength ${l.strength}`} />
                            <span className="num w-10 text-right">{l.strength.toFixed(1)}</span>
                          </div>
                        ) : <span className="text-ink-faint">–</span>}
                      </td>
                      <td className="py-3 pr-3">
                        <div className="flex items-center gap-2">
                          <Bar value={l.coverage} max={1} mark={THRESHOLD} label={`${(l.coverage * 100).toFixed(1)}% of regulars have full statistics`} />
                          <span className="num w-12 text-right">{(l.coverage * 100).toFixed(1)}%</span>
                        </div>
                      </td>
                      <td className="num py-3 pr-3 text-right">{num(l.regulars)}</td>
                      <td className="num py-3 pr-3 text-right">{eur(l.median_value_eur)}</td>
                      <td className="py-3"><RoleBars roles={l.roles} max={maxRole} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {waiting.length > 0 && (
              <div className="mt-4 flex flex-wrap items-center gap-2 rounded-lg bg-surface-sunk px-3 py-2.5 text-sm">
                <span className="font-semibold">Waiting for statistics:</span>
                {waiting.map((l) => (
                  <span key={l.id} className="rounded-md bg-surface-raised px-2 py-0.5 text-ink-soft">{l.name}</span>
                ))}
              </div>
            )}
            <p className="mt-3 text-xs text-ink-faint">
              Full statistics: the share of Transfermarkt regulars (900+ minutes) that also have API-Football statistics.
              The thin line marks 90%, where a league counts as complete.
            </p>
          </Sheet>

        </div>
        <aside aria-labelledby="xi-title" className="min-w-0 xl:sticky xl:top-6 xl:col-start-2 xl:row-span-3 xl:row-start-1">
          <div className="sheet">
            <h2 id="xi-title" className="condensed text-2xl font-bold leading-tight">Best XI under {eur(cap)} each</h2>
            <p className="text-sm text-ink-soft">
              Highest scores per position{maxAge ? `, ${maxAge} or younger` : ""}, from complete leagues, still playing.
            </p>
            <div className="mt-3 flex flex-wrap gap-3">
              <Segmented legend="Price limit" options={CAPS} value={cap} onChange={setCap} label={(c) => eur(c)} />
              <Segmented legend="Age" options={AGES} value={maxAge} onChange={setMaxAge} label={(a) => (a == null ? "Any" : `≤ ${a}`)} />
            </div>
            <div className="mt-4">
              <TacticsBoard team={xi && xi.team.players.length ? xi.team : null} formation="4-3-3"
                            onSelect={(p) => navigate(`/players/${p.player_id}`)}
                            emptyText="No complete league yet: the XI appears once a league's statistics are in." />
            </div>
            {xi && xi.team.players.length > 0 && (
              <div className="mt-3 flex items-baseline justify-between text-sm">
                <span className="text-ink-soft">Click a player for his profile.</span>
                <span><span className="num font-semibold">{eur(xi.team.cost_eur)}</span> <span className="text-ink-soft">in market value</span></span>
              </div>
            )}
            {xi && xi.missing.length > 0 && xi.team.players.length > 0 && (
              <p className="mt-2 text-xs text-ink-faint">
                Not enough reliable players under {eur(cap)} for: {xi.missing.map((r) => ROLE_NAMES[r].toLowerCase()).join(", ")}.
              </p>
            )}
          </div>
        </aside>
        <div className="min-w-0 xl:col-start-1 xl:row-start-2">
          <Sheet id="value-title" title="Best value by position"
                 note={<>Where price predicts a position's score, players who score most above their price. Elsewhere, the
                   highest scores under {eur(cap)}{maxAge ? `, ${maxAge} or younger` : ""} (set next to the Best XI).</>}>
            <div className="grid gap-x-8 gap-y-5 md:grid-cols-2 2xl:grid-cols-3">
              {ROLES.map((role) => {
                const vfm = d.value_for_money_shown?.[role] ?? false;
                const picks = vfm ? d.value_picks[role] ?? [] : d.budget_picks?.[String(cap)]?.[role] ?? [];
                return (
                  <div key={role}>
                    <div className="flex items-baseline justify-between border-b border-rule pb-1">
                      <h3 className="font-semibold">{ROLE_NAMES[role]}s</h3>
                      <span className="text-xs text-ink-faint">{vfm ? "value for money" : `best under ${eur(cap)}`}</span>
                    </div>
                    {picks.length === 0
                      ? <p className="mt-2 text-sm text-ink-faint">{vfm || t.leagues_complete === 0 ? "No player meets these rules yet." : `No reliable regular under ${eur(cap)}.`}</p>
                      : <PickList picks={picks} metric={vfm ? "vfm" : "score"} />}
                  </div>
                );
              })}
            </div>
          </Sheet>

        </div>
        <div className="min-w-0 xl:col-start-1 xl:row-start-3">
          <div className="grid gap-6 lg:grid-cols-2">
            <Sheet id="model-title" title="Scoring model">
              <dl className="space-y-3 text-sm">
                <div><dt className="text-ink-soft">Version</dt><dd className="font-semibold">{d.model.version ?? "Not run yet"}</dd></div>
                <div>
                  <dt className="text-ink-soft">League-strength adjustment</dt>
                  <dd className="font-semibold">{adj == null ? "Not calibrated yet" : adj.accepted ? "Active" : "Not active"}</dd>
                  <dd className="text-ink-soft">
                    {adj == null
                      ? "Needs league strength data (ClubElo or UEFA coefficients). Until then, scores rank players within their own league only."
                      : `${adj.source ? `Based on ${adj.source}: ` : ""}${adj.reason}.`}
                  </dd>
                </div>
              </dl>
            </Sheet>
            <Sheet id="imports-title" title="Recent imports">
              {d.imports.length === 0 ? <p className="text-sm text-ink-soft">No imports yet.</p> : (
                <ul className="divide-y divide-rule/60 text-sm">
                  {d.imports.slice(0, 5).map((r, i) => (
                    <li key={i} className="flex items-baseline justify-between gap-3 py-2">
                      <span>{r.source}<span className="block text-xs text-ink-faint">{r.kind}, {timeText(r.finished_at)}</span></span>
                      <span className={`num text-right ${r.status === "failed" ? "text-signal" : ""}`}>
                        {num(r.rows_written)} rows
                        <span className="block text-xs text-ink-faint">
                          {r.status === "success" ? "succeeded" : r.status === "failed" ? "failed" : r.status === "partial" ? "partly done" : "running"}
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Sheet>
          </div>
        </div>
      </div>
    </div>
  );
}
