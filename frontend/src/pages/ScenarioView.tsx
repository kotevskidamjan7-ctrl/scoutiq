import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, Scenario } from "../lib/api";
import { describe } from "../lib/builder";
import ResultView from "../components/ResultView";
import ImproveResult from "../components/ImproveResult";

const when = (iso: string) => new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });

export default function ScenarioView() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [s, setS] = useState<Scenario | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pdf, setPdf] = useState<"idle" | "busy" | string>("idle");

  useEffect(() => {
    api.scenario(Number(id)).then(setS).catch((e) => setError(e instanceof ApiError ? e.message : "Could not load the scenario."));
  }, [id]);

  if (error) return (
    <div><p role="alert" className="text-signal">{error}</p><Link to="/scenarios" className="mt-3 inline-block underline">Back to saved scenarios</Link></div>
  );
  if (!s) return <p className="text-ink-soft">Loading…</p>;

  const improve = s.mode === "improve";
  const subtitle = improve
    ? `Club plan${s.club_name ? ` for ${s.club_name}` : ""}, ${s.request.formation}. `
    : s.name !== describe(s.request) ? `${describe(s.request)}. ` : "";
  const open = () => improve
    ? navigate("/improve", { state: { improve: s.request, clubId: s.club_id, name: s.name } })
    : navigate("/builder", { state: { request: s.request } });
  async function downloadPdf() {
    setPdf("busy");
    try { await api.downloadScenarioPdf(s!.id); setPdf("idle"); }
    catch (e) { setPdf(e instanceof ApiError ? e.message : "The PDF could not be made."); }
  }
  const noResult = improve
    ? !s.result.team && `No plan was possible with these requirements${s.result.diagnosis ? `: ${s.result.diagnosis.reason}` : ""}.`
    : !s.result.team && `No team was possible with these requirements${s.result.diagnosis ? `: ${s.result.diagnosis.reason}` : ""}.`;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Link to="/scenarios" className="text-sm text-ink-soft underline-offset-4 hover:underline">Saved scenarios</Link>
          <h1 className="condensed text-4xl font-bold leading-tight">{s.name}</h1>
          <p className="text-ink-soft">{subtitle}Saved {when(s.created_at)}.</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <div className="flex flex-wrap gap-3">
            <button type="button" className="btn-quiet" disabled={pdf === "busy"} onClick={downloadPdf}>
              {pdf === "busy" ? "Preparing PDF…" : "Download PDF"}
            </button>
            <button type="button" className="btn-primary" onClick={open}>
              {improve ? "Open in Improve my club" : "Open in builder"}
            </button>
          </div>
          {pdf !== "idle" && pdf !== "busy" && <p role="alert" className="text-sm text-signal">{pdf}</p>}
        </div>
      </div>
      {noResult
        ? <p className="rounded-md bg-surface-sunk p-4">{noResult}</p>
        : improve
          ? <div className="max-w-6xl"><ImproveResult result={s.result} request={s.request} /></div>
          : <div className="max-w-5xl"><ResultView result={s.result} formation={s.request.formation} /></div>}
      {improve && (
        <p className="text-sm text-ink-faint">
          The result is as it was when saved. Opening it in Improve my club runs it again on the squad and data as they are today.
        </p>
      )}
    </div>
  );
}
