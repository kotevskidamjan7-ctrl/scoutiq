// Club improvement (Mode B): start from your squad, find the signings that improve the starting XI most.
import { FormEvent, ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { api, ApiError, Club, ImproveRequest, ImproveResponse, PlayerRow, Role, SquadPlayer } from "../lib/api";
import { eur, ROLE_NAMES } from "../lib/format";
import { FORMATIONS } from "../lib/formations";
import { applyImproveSuggestion, DEFAULT_IMPROVE, describeImprove, fromImproveRequest, ImproveForm, improveFromInterpretation, ROLE_COUNTS, toImproveRequest } from "../lib/improve";
import AssistantBox from "../components/AssistantBox";
import ScopeChips from "../components/ScopeChips";
import { AcrossLeaguesToggle, useAdjustment } from "../lib/adjustment";
import ImproveResult from "../components/ImproveResult";
import Toast from "../components/Toast";
import PageHeader from "../components/PageHeader";

function Field({ id, label, error, hint, children }: { id: string; label: string; error?: string; hint?: string; children: ReactNode }) {
  return (
    <div>
      <label htmlFor={id} className="label">{label}</label>
      {children}
      {hint && !error && <p className="mt-1 text-xs text-ink-faint">{hint}</p>}
      {error && <p id={`${id}-error`} className="mt-1 text-xs font-medium text-signal">{error}</p>}
    </div>
  );
}

/** Search box with a list of matches underneath; used for clubs and for adding players. */
function Finder<T>({ id, label, placeholder, search, render, onPick }: {
  id: string; label: string; placeholder: string; search: (q: string) => Promise<T[]>;
  render: (t: T) => ReactNode; onPick: (t: T) => void;
}) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<T[]>([]);
  const searchRef = useRef(search);   // the latest search function, without re-running the effect for it
  searchRef.current = search;
  useEffect(() => {
    if (q.trim().length < 2) { setHits([]); return; }
    let live = true;
    const t = setTimeout(() => searchRef.current(q.trim()).then((h) => live && setHits(h.slice(0, 8))).catch(() => live && setHits([])), 250);
    return () => { live = false; clearTimeout(t); };
  }, [q]);
  return (
    <div>
      <label htmlFor={id} className="label">{label}</label>
      <input id={id} type="search" className="field" placeholder={placeholder} value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off" />
      {hits.length > 0 && (
        <ul className="mt-1 divide-y divide-rule overflow-hidden rounded-md border border-rule bg-surface-raised">
          {hits.map((h, i) => (
            <li key={i}>
              <button type="button" className="w-full px-3 py-2 text-left text-sm hover:bg-surface-sunk"
                      onClick={() => { onPick(h); setQ(""); setHits([]); }}>
                {render(h)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// the field to put the cursor in for each kind of problem (default: the field with the same id)
const FIELD_FOR: Record<string, string> = { squad: "club" };
function focusFirst(errors: Record<string, string>) {
  const first = Object.keys(errors)[0];
  if (first) document.getElementById(FIELD_FOR[first] ?? first)?.focus();
}

export default function Improve() {
  const [club, setClub] = useState<Club | null>(null);
  const [squad, setSquad] = useState<SquadPlayer[]>([]);
  const [inSquad, setInSquad] = useState<Set<number>>(new Set());
  const [locked, setLocked] = useState<Set<number>>(new Set());
  const [form, setForm] = useState<ImproveForm>(DEFAULT_IMPROVE);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [result, setResult] = useState<ImproveResponse | null>(null);
  const [lastReq, setLastReq] = useState<ImproveRequest | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [runs, setRuns] = useState(0);          // a new key per result, so plan tabs start at the best plan
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const clearToast = useCallback(() => setToast(null), []);
  const location = useLocation();
  const reopened = (location.state as { improve?: ImproveRequest; clubId?: number | null; name?: string } | null);
  const [reopenedName, setReopenedName] = useState<string | null>(null);

  const set = <K extends keyof ImproveForm>(k: K, v: ImproveForm[K]) => setForm((f) => ({ ...f, [k]: v }));
  const adjustment = useAdjustment();
  const toggle = (s: Set<number>, id: number) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; };

  async function pickClub(c: Club) {
    setClub(c); setResult(null); setFailure(null); setReopenedName(null);
    try {
      const s = await api.squad(c.id);
      setSquad(s.players);
      setInSquad(new Set(s.players.filter((p) => p.score != null).map((p) => p.player_id)));
      setLocked(new Set());
    } catch (e) { setFailure(e instanceof ApiError ? e.message : "Could not load the squad."); }
  }

  // reopening a saved plan: the club's squad as it is now, with the saved ticks, locks and settings
  useEffect(() => {
    const req = reopened?.improve;
    if (!req) return;
    let live = true;
    (async () => {
      try {
        const base = reopened?.clubId != null ? await api.squad(reopened.clubId) : null;
        const known = new Set(base?.players.map((p) => p.player_id) ?? []);
        const extra = [...req.owned_player_ids, ...(req.left_player_ids ?? [])].filter((id) => !known.has(id));
        const added = extra.length ? await api.squadPlayers(extra) : [];
        if (!live) return;
        const squadNow = [...(base?.players ?? []), ...added];
        // saved ticks; players who joined since then (in neither list) start ticked
        const left = new Set(req.left_player_ids ?? []);
        const saved = new Set(req.owned_player_ids);
        const inNow = new Set(squadNow.filter((p) => saved.has(p.player_id) || (!left.has(p.player_id) && p.score != null))
          .map((p) => p.player_id));
        const lockedNow = new Set((req.locked_player_ids ?? []).filter((id) => inNow.has(id)));
        const f = fromImproveRequest(req);
        setClub(base?.club ?? null);
        setSquad(squadNow);
        setInSquad(inNow);
        setLocked(lockedNow);
        setForm(f);
        setReopenedName(reopened?.name ?? null);
        run(f, lockedNow, { squad: squadNow, inSquad: inNow, club: base?.club ?? null, score: req.score ?? "within" });
      } catch (e) { if (live) setFailure(e instanceof ApiError ? e.message : "Could not reopen the saved plan."); }
    })();
    return () => { live = false; };
  }, [reopened]);

  async function addPlayer(p: PlayerRow) {
    if (squad.some((s) => s.player_id === p.player_id)) { setInSquad((s) => new Set(s).add(p.player_id)); return; }
    const [row] = await api.squadPlayers([p.player_id]);
    if (row) { setSquad((s) => [...s, row]); setInSquad((s) => new Set(s).add(row.player_id)); }
  }

  // ctx: values just loaded but not yet in state (reopening a saved plan)
  async function run(f: ImproveForm, lockedNow: Set<number> = locked,
                     ctx?: { squad: SquadPlayer[]; inSquad: Set<number>; club: Club | null; score: "within" | "adjusted" }) {
    const { req: base, errors } = toImproveRequest(f, ctx?.squad ?? squad, ctx?.inSquad ?? inSquad, lockedNow);
    setErrors(errors);
    if (!base) { focusFirst(errors); return; }
    const score = ctx?.score ?? (adjustment?.active && f.adjusted ? "adjusted" as const : "within" as const);
    const req = { ...base, score };
    const clubNow = ctx ? ctx.club : club;
    setLoading(true); setFailure(null);
    try {
      const r = await api.improve(req);
      setResult(r); setLastReq(req); setRuns((n) => n + 1);
      setName(describeImprove(clubNow?.name ?? null, req, r.team?.players.filter((p) => p.signing).length ?? 0));
    }
    catch (e) { setFailure(e instanceof ApiError ? e.message : "Something went wrong while finding signings."); }
    finally { setLoading(false); }
  }
  const submit = (e: FormEvent) => { e.preventDefault(); run(form); };

  async function save() {
    if (!lastReq) return;
    setSaving(true);
    try {
      await api.saveImproveScenario(name.trim() || describeImprove(club?.name ?? null, lastReq, 0), club?.id ?? null, lastReq);
      setToast("Plan saved to Saved scenarios");
    } catch (e) {
      setToast(e instanceof ApiError ? e.message : "The plan could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  const scoredInSquad = squad.filter((p) => inSquad.has(p.player_id) && p.score != null).length;
  const lockedPerRole = squad.reduce<Record<string, number>>((acc, p) => {
    if (locked.has(p.player_id) && p.role) acc[p.role] = (acc[p.role] ?? 0) + 1;
    return acc;
  }, {});
  const roleFull = (role: string | null) => !!role && (lockedPerRole[role] ?? 0) >= (ROLE_COUNTS[form.formation]?.[role] ?? 0);

  return (
    <div className="space-y-6">
    <PageHeader title="Improve my club"
                subtitle="Start from your squad. Find the signings that improve your starting XI the most." />
    <div className="grid items-start gap-6 xl:grid-cols-[26rem_1fr]">
      <form onSubmit={submit} noValidate className="sheet space-y-6" aria-label="Club and requirements">

        <Finder<Club> id="club" label={club ? "Change club" : "Your club"} placeholder="For example Brentford"
                      search={api.clubs} onPick={pickClub}
                      render={(c) => <><span className="font-semibold">{c.name}</span> <span className="text-ink-faint">{c.league}</span></>} />

        {club && (
          <section aria-label="Squad" className="rounded-md border border-rule bg-surface-raised">
            <div className="border-b border-rule px-3 py-2">
              <p className="font-semibold">{club.name}</p>
              <p className="text-xs text-ink-faint">
                {scoredInSquad} players with a score in the squad. Untick players who have left (they are not suggested as
                signings); lock players who must start.
              </p>
            </div>
            <ul className="max-h-[22rem] divide-y divide-rule overflow-y-auto">
              {squad.map((p) => {
                const on = inSquad.has(p.player_id);
                const unscored = p.score == null;
                return (
                  <li key={p.player_id} className={`flex items-center gap-2 px-3 py-1.5 text-sm ${on ? "" : "opacity-50"}`}>
                    <input type="checkbox" className="h-4 w-4 accent-board" checked={on} aria-label={`${p.name} is in the squad`}
                           onChange={() => { setInSquad((s) => toggle(s, p.player_id)); setLocked((s) => { const n = new Set(s); n.delete(p.player_id); return n; }); }} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{p.name}</span>
                      <span className="block text-xs text-ink-faint">
                        {unscored ? "No 2024/25 score, left out" : `${ROLE_NAMES[p.role!]}, age ${p.age ?? "–"}`}
                      </span>
                    </span>
                    <span className="num w-10 text-right font-semibold">{unscored ? "–" : p.score!.toFixed(0)}</span>
                    <button type="button" aria-pressed={locked.has(p.player_id)}
                            disabled={!on || unscored || (!locked.has(p.player_id) && roleFull(p.role))}
                            title={!locked.has(p.player_id) && roleFull(p.role) ? `${form.formation} has no more room for this position` : undefined}
                            onClick={() => setLocked((s) => toggle(s, p.player_id))}
                            className={["w-20 rounded px-2 py-1 text-xs font-semibold disabled:opacity-30",
                              locked.has(p.player_id) ? "bg-board text-chalk" : "border border-rule text-ink-soft hover:bg-surface-sunk"].join(" ")}>
                      {locked.has(p.player_id) ? "Must start" : "Lock"}
                    </button>
                  </li>
                );
              })}
            </ul>
            <div className="border-t border-rule p-3">
              <Finder<PlayerRow> id="add" label="Add a player" placeholder="A signing the data does not know yet"
                                 search={(q) => api.players({ q, min_minutes: 450, limit: 8 }).then((r) => r.items)}
                                 onPick={addPlayer}
                                 render={(p) => <><span className="font-semibold">{p.name}</span> <span className="text-ink-faint">{ROLE_NAMES[p.role]}, {p.club}</span></>} />
            </div>
          </section>
        )}
        {errors.squad && <p className="text-xs font-medium text-signal">{errors.squad}</p>}
        {Object.entries(lockedPerRole).some(([r, n]) => n > (ROLE_COUNTS[form.formation]?.[r] ?? 0)) && (
          <p className="text-xs font-medium text-signal">
            You locked more players in one position than {form.formation} has room for. Unlock some or pick another formation.
          </p>
        )}

        <AssistantBox page="improve" placeholder="What do you need? e.g. a striker and a centre-back, 5m"
                      examples={["a young full-back under 2m", "two midfielders, budget 8m, still playing", "искусен нападач до 3 милиони"]}
                      onApply={(r) => { setForm((f) => improveFromInterpretation(r, f)); setErrors({}); }} />

        <fieldset>
          <legend className="label">Formation</legend>
          <div className="flex flex-wrap gap-2">
            {FORMATIONS.map((f) => (
              <label key={f} className={["num cursor-pointer rounded-md border px-3 py-1.5 text-sm font-semibold has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-marker",
                form.formation === f ? "border-board bg-board text-chalk" : "border-rule bg-surface-raised hover:bg-surface-sunk"].join(" ")}>
                <input type="radio" name="formation" className="sr-only" checked={form.formation === f} onChange={() => set("formation", f)} />{f}
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset>
          <legend className="label">Positions to sign</legend>
          <div className="flex flex-wrap gap-2">
            {(["GK", "CB", "FB", "CM", "AW", "ST"] as Role[]).map((r) => {
              const on = form.signingRoles.includes(r);
              return (
                <button key={r} type="button" aria-pressed={on}
                        onClick={() => set("signingRoles", on ? form.signingRoles.filter((x) => x !== r) : [...form.signingRoles, r])}
                        className={["rounded-md border px-3 py-1.5 text-sm font-semibold",
                          on ? "border-board bg-board text-chalk" : "border-rule bg-surface-raised hover:bg-surface-sunk"].join(" ")}>
                  {ROLE_NAMES[r]}
                </button>
              );
            })}
          </div>
          <p className="mt-1 text-xs text-ink-faint">
            {form.signingRoles.length === 0
              ? "None chosen: signings can be in any position."
              : `Signings only as ${form.signingRoles.map((r) => ROLE_NAMES[r].toLowerCase()).join(" or ")}. Your own players still cover every position.`}
          </p>
        </fieldset>

        <div className="grid grid-cols-2 gap-3">
          <Field id="budget" label="Transfer budget" error={errors.budget} hint="For example 5m, 500k or 0">
            <input id="budget" className="field num text-lg font-semibold" value={form.budget} inputMode="decimal"
                   aria-invalid={!!errors.budget} onChange={(e) => set("budget", e.target.value)} />
          </Field>
          <div>
            <span className="label" id="signings-label">Most signings</span>
            <div className="flex items-center gap-1" role="group" aria-labelledby="signings-label">
              <button type="button" className="btn-quiet h-11 w-11 p-0" aria-label="One signing fewer"
                      disabled={form.maxSignings === 0} onClick={() => set("maxSignings", form.maxSignings - 1)}>−</button>
              <span className="num w-10 text-center text-lg font-semibold" aria-live="polite">{form.maxSignings}</span>
              <button type="button" className="btn-quiet h-11 w-11 p-0" aria-label="One signing more"
                      disabled={form.maxSignings >= 11} onClick={() => set("maxSignings", form.maxSignings + 1)}>+</button>
            </div>
          </div>
        </div>

        <AcrossLeaguesToggle checked={form.adjusted} onChange={(v) => set("adjusted", v)} status={adjustment} />

        <details className="rounded-md border border-rule bg-surface-raised" open={!!(form.ageMin || form.ageMax || form.maxPrice || form.includeLowMinutes || !form.recentForm || form.leagueIds.length || form.nationalities.length)}>
          <summary className="cursor-pointer px-3 py-2 font-semibold">Filters for signings</summary>
          <div className="space-y-4 border-t border-rule px-3 py-4">
            <ScopeChips leagueIds={form.leagueIds} nationalities={form.nationalities}
                        onChange={(l, n) => setForm((f) => ({ ...f, leagueIds: l, nationalities: n }))} />
            <div className="grid grid-cols-2 gap-3">
              <Field id="ageMin" label="Youngest age" error={errors.ageMin}>
                <input id="ageMin" className="field num" inputMode="numeric" placeholder="Any" value={form.ageMin} onChange={(e) => set("ageMin", e.target.value)} />
              </Field>
              <Field id="ageMax" label="Oldest age" error={errors.ageMax}>
                <input id="ageMax" className="field num" inputMode="numeric" placeholder="Any" value={form.ageMax} onChange={(e) => set("ageMax", e.target.value)} />
              </Field>
            </div>
            <Field id="maxPrice" label="Most for one player" error={errors.maxPrice}>
              <input id="maxPrice" className="field num" placeholder="No limit" value={form.maxPrice} onChange={(e) => set("maxPrice", e.target.value)} />
            </Field>
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-0.5 h-4 w-4 accent-board" checked={form.recentForm} onChange={(e) => set("recentForm", e.target.checked)} />
              <span>Still playing: 900+ league minutes in 2025/26</span>
            </label>
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-0.5 h-4 w-4 accent-board" checked={form.includeLowMinutes} onChange={(e) => set("includeLowMinutes", e.target.checked)} />
              <span>Include players with 450–899 minutes in 2024/25 (less reliable scores)</span>
            </label>
            <p className="text-xs text-ink-faint">Filters apply to signings only. Your own players are always available.</p>
          </div>
        </details>

        {Object.keys(errors).length > 0 && (
          <p role="alert" className="rounded-md bg-signal-soft px-3 py-2 text-sm text-signal">
            {Object.values(errors).join(" ")}
          </p>
        )}
        <button type="submit" className="btn-primary w-full py-3 text-lg" disabled={loading}>
          {loading ? "Finding signings…" : "Find the best signings"}
        </button>
      </form>

      <section aria-label="Result" className="min-w-0 space-y-6">
        {reopenedName && (
          <p className="rounded-md border border-rule bg-surface-raised px-4 py-3 text-sm">
            Reopened <span className="font-semibold">{reopenedName}</span>. The squad and players are today's data, so the
            result can differ from the saved one.
          </p>
        )}
        {failure && <div role="alert" className="rounded-md border border-signal/40 bg-signal-soft px-4 py-3 text-signal">{failure}</div>}

        {loading && !result && <p className="text-ink-soft">Finding signings…</p>}
        {!result && !failure && !loading && (
          <div className="rounded-lg border border-dashed border-rule p-6 text-ink-soft">
            <p className="font-semibold text-ink">How it works</p>
            <p className="mt-1">Your players count as free. A signing only starts if he is better than the player he replaces,
              so the result shows exactly how much each purchase adds. Set the budget to 0 to see your best XI as it is.</p>
          </div>
        )}

        {result && !result.team && result.diagnosis && (
          <div role="alert" className="rounded-lg border border-rule bg-surface-raised p-4">
            <h2 className="condensed text-2xl font-bold">No plan fits these requirements</h2>
            <p className="mt-1 text-ink-soft first-letter:uppercase">{result.diagnosis.reason}.</p>
            {Object.keys(result.current_missing).length > 0 && !result.diagnosis.reason.includes("more starters") && !result.diagnosis.reason.includes("positions to sign") && (
              <p className="mt-1 text-ink-soft">
                Your squad is short of: {Object.entries(result.current_missing).map(([r, n]) => `${n} ${ROLE_NAMES[r as keyof typeof ROLE_NAMES].toLowerCase()}${n! > 1 ? "s" : ""}`).join(", ")}.
              </p>
            )}
            {result.diagnosis.suggestions.length > 0 && (
              <ul className="mt-3 divide-y divide-rule">
                {result.diagnosis.suggestions.map((s) => {
                  const unlock = s.unlock_ids ?? [];
                  const add = s.add_roles ?? [];
                  const next = unlock.length ? form
                    : add.length ? { ...form, signingRoles: [...new Set([...form.signingRoles, ...add])] }
                    : applyImproveSuggestion(form, s.change, result.diagnosis);
                  const apply = () => {
                    if (unlock.length) {
                      const fewer = new Set([...locked].filter((id) => !unlock.includes(id)));
                      setLocked(fewer); run(form, fewer);
                    } else if (next) { setForm(next); run(next); }
                  };
                  return (
                    <li key={s.change} className="flex flex-wrap items-center justify-between gap-3 py-2">
                      <span>
                        <span className="block font-semibold first-letter:uppercase">{s.change}</span>
                        <span className="num block text-sm text-ink-soft">Best XI then scores {s.total_score.toFixed(1)}, signings cost {eur(s.cost_eur)}</span>
                      </span>
                      {next && <button type="button" className="btn-quiet py-1.5 text-sm" onClick={apply}>Try this</button>}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        )}

        {result?.team && lastReq && (
          <>
            <ImproveResult key={runs} result={result} request={lastReq} />
            <div className="flex flex-wrap items-end gap-3 border-t border-rule pt-5">
              <div className="min-w-[16rem] flex-1">
                <label htmlFor="planName" className="label">Plan name</label>
                <input id="planName" className="field" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
              </div>
              <button type="button" className="btn-quiet" onClick={save} disabled={saving}>
                {saving ? "Saving…" : "Save plan"}
              </button>
            </div>
          </>
        )}
      </section>
    </div>
    <Toast text={toast} onDone={clearToast} />
    </div>
  );
}
