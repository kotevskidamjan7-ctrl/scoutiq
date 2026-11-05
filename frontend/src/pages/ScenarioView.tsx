import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, Scenario } from "../lib/api";
import { describe } from "../lib/builder";
import ResultView from "../components/ResultView";

export default function ScenarioView() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [s, setS] = useState<Scenario | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.scenario(Number(id)).then(setS).catch((e) => setError(e instanceof ApiError ? e.message : "Could not load the scenario."));
  }, [id]);

  if (error) return (
    <div><p role="alert" className="text-signal">{error}</p><Link to="/scenarios" className="mt-3 inline-block underline">Back to saved scenarios</Link></div>
  );
  if (!s) return <p className="text-ink-soft">Loading…</p>;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Link to="/scenarios" className="text-sm text-ink-soft underline-offset-4 hover:underline">Saved scenarios</Link>
          <h1 className="condensed text-4xl font-bold leading-tight">{s.name}</h1>
          <p className="text-ink-soft">
            {s.name !== describe(s.request) && `${describe(s.request)}. `}Saved {new Date(s.created_at).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })}.
          </p>
        </div>
        <button type="button" className="btn-primary" onClick={() => navigate("/", { state: { request: s.request } })}>
          Open in builder
        </button>
      </div>
      {s.result.team
        ? <div className="max-w-5xl"><ResultView result={s.result} formation={s.request.formation} /></div>
        : <p className="rounded-md bg-surface-sunk p-4">No team was possible with these requirements{s.result.diagnosis ? `: ${s.result.diagnosis.reason}` : ""}.</p>}
    </div>
  );
}
