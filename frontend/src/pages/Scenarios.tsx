import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, ScenarioSummary } from "../lib/api";
import { eur } from "../lib/format";

export default function Scenarios() {
  const [rows, setRows] = useState<ScenarioSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);

  useEffect(() => {
    api.scenarios().then(setRows).catch((e) => setError(e instanceof ApiError ? e.message : "Could not load scenarios."));
  }, []);

  async function remove(s: ScenarioSummary) {
    setDeleting(s.id);
    try {
      await api.deleteScenario(s.id);
      setRows((r) => r?.filter((x) => x.id !== s.id) ?? null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not delete the scenario.");
    } finally {
      setDeleting(null);
    }
  }

  return (
    <div className="max-w-4xl">
      <h1 className="condensed text-4xl font-bold">Saved scenarios</h1>
      {error && <p role="alert" className="mt-4 rounded-md bg-signal-soft px-3 py-2 text-signal">{error}</p>}
      {rows === null && !error && <p className="mt-6 text-ink-soft">Loading…</p>}
      {rows?.length === 0 && (
        <div className="mt-6 rounded-lg border border-dashed border-rule p-6">
          <p className="font-semibold">No saved scenarios yet.</p>
          <p className="mt-1 text-ink-soft">Find a team in the squad builder, then save it to compare it here later.</p>
          <Link to="/" className="btn-primary mt-4">Open the squad builder</Link>
        </div>
      )}
      {rows && rows.length > 0 && (
        <ul className="mt-6 divide-y divide-rule border-y border-rule">
          {rows.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center gap-x-6 gap-y-2 py-3">
              <Link to={`/scenarios/${s.id}`} className="min-w-[14rem] flex-1">
                <span className="font-semibold underline-offset-4 hover:underline">{s.name}</span>
                <span className="block text-sm text-ink-faint">
                  Saved {new Date(s.created_at).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })}
                </span>
              </Link>
              <span className="num w-24 text-right">
                {s.total_score != null ? <><span className="condensed text-2xl font-bold">{s.total_score.toFixed(1)}</span><span className="block text-xs text-ink-faint">score</span></>
                  : <span className="text-sm text-ink-faint">No team</span>}
              </span>
              <span className="num w-32 text-right text-sm">
                {eur(s.cost_eur)}<span className="block text-xs text-ink-faint">of {eur(s.budget_eur)}</span>
              </span>
              <button type="button" className="btn-quiet py-1.5 text-sm" onClick={() => remove(s)} disabled={deleting === s.id}>
                {deleting === s.id ? "Deleting…" : "Delete"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
