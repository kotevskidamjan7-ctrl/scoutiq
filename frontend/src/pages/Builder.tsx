// Squad builder (Mode A): set a budget and either a formation or the positions to sign, then find the best team.
import { FormEvent, ReactNode, useCallback, useState } from "react";
import { useLocation } from "react-router-dom";
import { api, ApiError, OptimizeRequest, OptimizeResponse, Role } from "../lib/api";
import { DEFAULT_FORM, Form, applySuggestion, describe, formFromInterpretation, fromRequest, toRequest } from "../lib/builder";
import AssistantBox from "../components/AssistantBox";
import ScopeChips from "../components/ScopeChips";
import { AcrossLeaguesToggle, useAdjustment } from "../lib/adjustment";
import { eur, ROLE_NAMES } from "../lib/format";
import { FORMATIONS } from "../lib/formations";
import ResultView from "../components/ResultView";
import Toast from "../components/Toast";
import PageHeader from "../components/PageHeader";

const ROLES: Role[] = ["GK", "CB", "FB", "CM", "AW", "ST"];

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

// the field to put the cursor in for each kind of problem (default: the field with the same id)
const FIELD_FOR: Record<string, string> = {};
function focusFirst(errors: Record<string, string>) {
  const first = Object.keys(errors)[0];
  if (first) document.getElementById(FIELD_FOR[first] ?? first)?.focus();
}

export default function Builder() {
  const location = useLocation();
  const reopened = (location.state as { request?: OptimizeRequest } | null)?.request;
  const [form, setForm] = useState<Form>(() => (reopened ? fromRequest(reopened) : DEFAULT_FORM));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [result, setResult] = useState<OptimizeResponse | null>(null);
  const [lastReq, setLastReq] = useState<OptimizeRequest | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [toast, setToast] = useState<string | null>(null);
  const clearToast = useCallback(() => setToast(null), []);

  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => ({ ...f, [k]: v }));
  const adjustment = useAdjustment();
  const setNeed = (r: Role, n: number) => setForm((f) => ({ ...f, needs: { ...f.needs, [r]: Math.max(0, Math.min(11, n)) } }));

  async function run(f: Form) {
    const { req: base, errors } = toRequest(f);
    setErrors(errors);
    if (!base) { focusFirst(errors); return; }
    const req = { ...base, score: adjustment?.active && f.adjusted ? "adjusted" as const : "within" as const };
    setLoading(true);
    setFailure(null);
    try {
      setResult(await api.optimize(req));
      setLastReq(req);
      setName(describe(req));
    } catch (e) {
      setFailure(e instanceof ApiError ? e.message : "Something went wrong while finding the team.");
    } finally {
      setLoading(false);
    }
  }

  const submit = (e: FormEvent) => { e.preventDefault(); run(form); };

  async function save() {
    if (!lastReq) return;
    setSaving(true);
    try {
      await api.saveScenario(name.trim() || describe(lastReq), lastReq);
      setToast("Scenario saved");
    } catch (e) {
      setToast(e instanceof ApiError ? e.message : "The scenario could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  const infeasible = result && !result.team;
  const totalNeeds = Object.values(form.needs).reduce((a, b) => a + b, 0);

  return (
    <div className="space-y-6">
    <PageHeader title="Squad builder"
                subtitle="The best team the budget can buy, from players with enough league minutes to judge." />
    <div className="grid items-start gap-6 xl:grid-cols-[24rem_1fr]">
      <form onSubmit={submit} noValidate className="sheet space-y-6" aria-label="Team requirements">

        <AssistantBox page="builder" placeholder="Describe it, e.g. two centre-backs and a striker, budget 5m"
                      examples={["4-3-3 for 30m, players under 28", "a young winger under 4m", "голман и штопер, буџет 3м"]}
                      onApply={(r) => { setForm((f) => formFromInterpretation(r, f)); setErrors({}); }} />

        <fieldset>
          <legend className="label">What are you building?</legend>
          <div className="grid grid-cols-2 gap-1 rounded-md bg-surface-sunk p-1">
            {([["xi", "Starting XI"], ["signings", "Specific signings"]] as const).map(([m, text]) => (
              <label key={m} className={[
                "cursor-pointer rounded px-3 py-2 text-center text-sm font-semibold has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-marker",
                form.mode === m ? "bg-surface-raised shadow-sm" : "text-ink-soft",
              ].join(" ")}>
                <input type="radio" name="mode" value={m} checked={form.mode === m} onChange={() => set("mode", m)} className="sr-only" />
                {text}
              </label>
            ))}
          </div>
        </fieldset>

        <Field id="budget" label="Transfer budget" error={errors.budget} hint="For example 15m, 500k or 2,500,000">
          <input id="budget" className="field num text-lg font-semibold" value={form.budget} inputMode="decimal"
                 aria-invalid={!!errors.budget} aria-describedby={errors.budget ? "budget-error" : undefined}
                 onChange={(e) => set("budget", e.target.value)} />
        </Field>

        {form.mode === "xi" ? (
          <fieldset>
            <legend className="label">Formation</legend>
            <div className="flex flex-wrap gap-2">
              {FORMATIONS.map((f) => (
                <label key={f} className={[
                  "num cursor-pointer rounded-md border px-3 py-1.5 text-sm font-semibold has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-marker",
                  form.formation === f ? "border-board bg-board text-chalk" : "border-rule bg-surface-raised hover:bg-surface-sunk",
                ].join(" ")}>
                  <input type="radio" name="formation" value={f} checked={form.formation === f}
                         onChange={() => set("formation", f)} className="sr-only" />
                  {f}
                </label>
              ))}
            </div>
          </fieldset>
        ) : (
          <fieldset aria-describedby={errors.needs ? "needs-error" : undefined}>
            <legend className="label">Positions to sign <span className="num font-normal text-ink-faint">({totalNeeds})</span></legend>
            <ul className="divide-y divide-rule rounded-md border border-rule bg-surface-raised">
              {ROLES.map((r) => (
                <li key={r} className="flex items-center justify-between px-3 py-1.5">
                  <span className={form.needs[r] ? "font-semibold" : "text-ink-soft"}>{ROLE_NAMES[r]}</span>
                  <span className="flex items-center gap-1">
                    <button type="button" className="btn-quiet h-8 w-8 p-0" aria-label={`One fewer ${ROLE_NAMES[r]}`}
                            disabled={form.needs[r] === 0} onClick={() => setNeed(r, form.needs[r] - 1)}>−</button>
                    <span className="num w-6 text-center font-semibold" aria-live="polite">{form.needs[r]}</span>
                    <button type="button" className="btn-quiet h-8 w-8 p-0" aria-label={`One more ${ROLE_NAMES[r]}`}
                            onClick={() => setNeed(r, form.needs[r] + 1)}>+</button>
                  </span>
                </li>
              ))}
            </ul>
            {errors.needs && <p id="needs-error" className="mt-1 text-xs font-medium text-signal">{errors.needs}</p>}
          </fieldset>
        )}

        <AcrossLeaguesToggle checked={form.adjusted} onChange={(v) => set("adjusted", v)} status={adjustment} />

        <details className="group rounded-md border border-rule bg-surface-raised" open={!!(form.ageMin || form.ageMax || form.maxPrice || form.maxPerClub || form.includeLowMinutes || !form.recentForm || form.leagueIds.length || form.nationalities.length)}>
          <summary className="cursor-pointer px-3 py-2 font-semibold">Filters</summary>
          <div className="space-y-4 border-t border-rule px-3 py-4">
            <ScopeChips leagueIds={form.leagueIds} nationalities={form.nationalities}
                        onChange={(l, n) => setForm((f) => ({ ...f, leagueIds: l, nationalities: n }))} />
            <div className="grid grid-cols-2 gap-3">
              <Field id="ageMin" label="Youngest age" error={errors.ageMin}>
                <input id="ageMin" className="field num" inputMode="numeric" value={form.ageMin} placeholder="Any"
                       onChange={(e) => set("ageMin", e.target.value)} />
              </Field>
              <Field id="ageMax" label="Oldest age" error={errors.ageMax}>
                <input id="ageMax" className="field num" inputMode="numeric" value={form.ageMax} placeholder="Any"
                       onChange={(e) => set("ageMax", e.target.value)} />
              </Field>
            </div>
            <Field id="maxPrice" label="Most for one player" error={errors.maxPrice}>
              <input id="maxPrice" className="field num" value={form.maxPrice} placeholder="No limit"
                     onChange={(e) => set("maxPrice", e.target.value)} />
            </Field>
            <Field id="maxPerClub" label="Most players from one club" error={errors.maxPerClub}>
              <input id="maxPerClub" className="field num" inputMode="numeric" value={form.maxPerClub} placeholder="No limit"
                     onChange={(e) => set("maxPerClub", e.target.value)} />
            </Field>
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-0.5 h-4 w-4 accent-board" checked={form.recentForm}
                     onChange={(e) => set("recentForm", e.target.checked)} />
              <span>Still playing: 900+ league minutes in 2025/26</span>
            </label>
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-0.5 h-4 w-4 accent-board" checked={form.includeLowMinutes}
                     onChange={(e) => set("includeLowMinutes", e.target.checked)} />
              <span>Include players with 450–899 minutes in 2024/25 (less reliable scores)</span>
            </label>
          </div>
        </details>

        {Object.keys(errors).length > 0 && (
          <p role="alert" className="rounded-md bg-signal-soft px-3 py-2 text-sm text-signal">
            {Object.values(errors).join(" ")}
          </p>
        )}
        <button type="submit" className="btn-primary w-full py-3 text-lg" disabled={loading}>
          {loading ? "Finding the best team…" : "Find the best team"}
        </button>
      </form>

      <section aria-label="Result" className="min-w-0 space-y-5">
        {failure && (
          <div role="alert" className="rounded-md border border-signal/40 bg-signal-soft px-4 py-3 text-signal">{failure}</div>
        )}

        {infeasible && result.diagnosis && (
          <div role="alert" className="rounded-lg border border-rule bg-surface-raised p-4">
            <h2 className="condensed text-2xl font-bold">No team fits these requirements</h2>
            <p className="mt-1 text-ink-soft first-letter:uppercase">{result.diagnosis.reason}.</p>
            {result.diagnosis.suggestions.length > 0 ? (
              <>
                <p className="mt-3 text-sm font-medium">Each of these changes would work on its own:</p>
                <ul className="mt-2 divide-y divide-rule">
                  {result.diagnosis.suggestions.map((s) => {
                    const next = applySuggestion(form, s.change, result.diagnosis);
                    return (
                      <li key={s.change} className="flex flex-wrap items-center justify-between gap-3 py-2">
                        <span>
                          <span className="block font-semibold first-letter:uppercase">{s.change}</span>
                          <span className="num block text-sm text-ink-soft">
                            Best team then scores {s.total_score.toFixed(1)} and costs {eur(s.cost_eur)}
                          </span>
                        </span>
                        {next && (
                          <button type="button" className="btn-quiet py-1.5 text-sm"
                                  onClick={() => { setForm(next); run(next); }}>
                            Try this
                          </button>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </>
            ) : (
              <p className="mt-3 text-sm">No single change makes a team possible. Try a bigger budget or fewer positions.</p>
            )}
          </div>
        )}

        {!infeasible && (
          <ResultView result={result} formation={lastReq?.formation} loading={loading}
                      emptyText={form.mode === "signings" ? "Choose the positions to sign, then find the best players." : undefined} />
        )}

        {result?.team && lastReq && (
          <div className="flex flex-wrap items-end gap-3 border-t border-rule pt-5">
            <div className="min-w-[16rem] flex-1">
              <label htmlFor="scenarioName" className="label">Scenario name</label>
              <input id="scenarioName" className="field" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
            </div>
            <button type="button" className="btn-quiet" onClick={save} disabled={saving}>
              {saving ? "Saving…" : "Save scenario"}
            </button>
          </div>
        )}
      </section>
      <Toast text={toast} onDone={clearToast} />
    </div>
    </div>
  );
}
