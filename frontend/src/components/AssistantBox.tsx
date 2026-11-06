// "Ask" box: type a request, see what was understood, then apply it to the page's form.
// The assistant only fills in filters; the page and the optimizer do the rest.
import { KeyboardEvent, useState } from "react";
import { api, ApiError, Interpretation } from "../lib/api";

interface Props {
  page: "players" | "builder" | "improve";
  placeholder: string;
  examples: string[];
  ignoredHere?: (r: Interpretation) => string[];   // understood, but this page has no such filter
  onApply: (r: Interpretation) => void;
}

export default function AssistantBox({ page, placeholder, examples, ignoredHere, onApply }: Props) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Interpretation | null>(null);
  const [error, setError] = useState<string | null>(null);

  // no <form> here: the box sits inside the builder's own form, and forms cannot be nested
  async function read(value = text) {
    if (value.trim().length < 2) return;
    setBusy(true); setError(null);
    try { setResult(await api.interpret(value.trim(), page)); }
    catch (err) { setError(err instanceof ApiError ? err.message : "The request could not be read."); }
    finally { setBusy(false); }
  }

  const ignored = result && ignoredHere ? ignoredHere(result) : [];
  const nothing = result && result.understood.length === 0;

  return (
    <section aria-label="Ask" className="rounded-lg border border-rule bg-surface-raised p-3">
      <div className="flex flex-wrap gap-2">
        <label htmlFor="ask" className="sr-only">Describe what you are looking for</label>
        <input id="ask" className="field min-w-[14rem] flex-1" placeholder={placeholder} value={text}
               onChange={(e) => { setText(e.target.value); setResult(null); }} maxLength={400} autoComplete="off"
               onKeyDown={(e: KeyboardEvent) => { if (e.key === "Enter") { e.preventDefault(); read(); } }} />
        <button type="button" className="btn-quiet" disabled={busy || text.trim().length < 2} onClick={() => read()}>
          {busy ? "Reading…" : "Read request"}
        </button>
      </div>

      {!result && !error && (
        <p className="mt-2 text-xs text-ink-faint">
          For example:{" "}
          {examples.map((ex, i) => (
            <span key={ex}>
              <button type="button" className="underline underline-offset-2 hover:text-ink"
                      onClick={() => { setText(ex); read(ex); }}>{ex}</button>
              {i < examples.length - 1 ? ", " : ""}
            </span>
          ))}
          . English or Macedonian.
        </p>
      )}
      {error && <p role="alert" className="mt-2 text-sm text-signal">{error}</p>}

      {result && (
        <div className="mt-3" aria-live="polite">
          {nothing ? (
            <p className="text-sm text-ink-soft">
              Nothing in this request matches a filter. Try naming a position, an age, a price, a league or a nationality.
            </p>
          ) : (
            <>
              <p className="text-xs text-ink-faint">
                {result.engine === "ai" ? "Read by the AI model" : "Read by the built-in rules"}. Check before applying:
              </p>
              <ul className="mt-1 flex flex-wrap gap-1.5">
                {result.understood.map((u) => (
                  <li key={u} className={["rounded-md px-2 py-1 text-sm font-medium",
                    ignored.includes(u) ? "bg-surface-sunk text-ink-faint line-through" : "bg-board text-chalk"].join(" ")}>{u}</li>
                ))}
              </ul>
              {ignored.length > 0 && <p className="mt-1 text-xs text-ink-faint">Crossed out: not a filter on this page.</p>}
              {result.not_applied.length > 0 && (
                <p className="mt-1 text-xs text-ink-soft">Not applied: {result.not_applied.join(", ")}.</p>
              )}
              <div className="mt-3 flex gap-2">
                <button type="button" className="btn-primary py-1.5" onClick={() => { onApply(result); setResult(null); setText(""); }}>
                  Apply to the form
                </button>
                <button type="button" className="btn-quiet py-1.5" onClick={() => setResult(null)}>Cancel</button>
              </div>
            </>
          )}
          {result.note && <p className="mt-2 text-xs text-ink-faint">{result.note}</p>}
        </div>
      )}
    </section>
  );
}
