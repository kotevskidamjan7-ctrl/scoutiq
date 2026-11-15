// The players a user follows: scores, value now vs when added, private notes, and actions to
// compare them or let the optimizer pick only from them.
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError, ShortlistItem } from "../lib/api";
import { MAX_COMPARE, useCompare } from "../lib/compare";
import { eur, ROLE_NAMES, signed } from "../lib/format";
import { useShortlist } from "../lib/shortlist";
import PageHeader from "../components/PageHeader";
import StarButton from "../components/StarButton";

type Sort = "added" | "score" | "price" | "change";
const SORTS: Record<Sort, string> = { added: "Recently added", score: "Score", price: "Price", change: "Value change" };

const added = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

function NoteField({ item, onSaved }: { item: ShortlistItem; onSaved: (note: string) => void }) {
  const [text, setText] = useState(item.note);
  const [state, setState] = useState<"idle" | "saving" | "saved" | string>("idle");
  useEffect(() => { setText(item.note); }, [item.note]);
  async function save() {
    if (text === item.note) return;
    setState("saving");
    try { const r = await api.shortlistNote(item.player_id, text); onSaved(r.note); setState("saved"); }
    catch (e) { setState(e instanceof ApiError ? e.message : "Not saved"); }
  }
  const id = `note-${item.player_id}`;
  return (
    <div>
      <label htmlFor={id} className="sr-only">Note on {item.name}</label>
      <textarea id={id} rows={2} maxLength={2000} value={text} placeholder="Add a note…"
                onChange={(e) => { setText(e.target.value); setState("idle"); }} onBlur={save}
                className="field min-h-[2.75rem] resize-y py-1.5 text-sm" />
      <p className="mt-0.5 h-4 text-xs text-ink-faint" aria-live="polite">
        {state === "saving" ? "Saving…" : state === "saved" ? "Saved" : state !== "idle" ? <span className="text-signal">{state}</span> : ""}
      </p>
    </div>
  );
}

export default function Shortlist() {
  const navigate = useNavigate();
  const shortlist = useShortlist();
  const compare = useCompare();
  const [items, setItems] = useState<ShortlistItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<Sort>("added");
  const [picked, setPicked] = useState<Set<number>>(new Set());

  useEffect(() => {
    api.shortlist().then(setItems).catch((e) => setError(e instanceof ApiError ? e.message : "Could not load your shortlist."));
  }, []);

  // a star removed here (or elsewhere) takes the row away; stars added elsewhere appear on the next visit
  const visible = useMemo(() => (items ?? []).filter((x) => shortlist.ids.has(x.player_id) || !shortlist.ready), [items, shortlist]);
  const rows = useMemo(() => {
    const r = [...visible];
    const by = (f: (x: ShortlistItem) => number | null) => (a: ShortlistItem, b: ShortlistItem) => (f(b) ?? -Infinity) - (f(a) ?? -Infinity);
    if (sort === "score") r.sort(by((x) => x.score));
    if (sort === "price") r.sort(by((x) => x.price_eur));
    if (sort === "change") r.sort(by((x) => x.value_change_pct));
    return r;
  }, [visible, sort]);

  const togglePick = (id: number) => setPicked((cur) => {
    const n = new Set(cur);
    if (n.has(id)) n.delete(id); else if (n.size < MAX_COMPARE) n.add(id);
    return n;
  });
  function compareSelected() {
    compare.clear();
    for (const x of rows.filter((r) => picked.has(r.player_id))) compare.toggle({ id: x.player_id, name: x.name, role: x.role ?? "" });
    navigate("/compare");
  }
  const scored = visible.filter((x) => x.score != null).length;

  return (
    <div className="space-y-6">
      <PageHeader title="Shortlist"
                  subtitle="Players you are following. Add notes, watch their value, compare them, or let the optimizer pick only from them." />

      {error && <p role="alert" className="rounded-md bg-signal-soft px-3 py-2 text-signal">{error}</p>}
      {items === null && !error && <p className="text-ink-soft">Loading…</p>}

      {items !== null && visible.length === 0 && (
        <div className="sheet max-w-2xl">
          <p className="text-lg font-semibold">Your shortlist is empty</p>
          <p className="mt-1 text-ink-soft">
            Click the star next to a player, on his page, in the Players list or among similar players, to follow him here.
          </p>
          <Link to="/players" className="btn-primary mt-4">Find players</Link>
        </div>
      )}

      {visible.length > 0 && (
        <>
          <div className="sheet flex flex-wrap items-center gap-3">
            <p className="mr-auto text-sm text-ink-soft">
              <span className="font-semibold text-ink">{visible.length}</span> player{visible.length === 1 ? "" : "s"},{" "}
              {scored} with a 2024/25 score.
            </p>
            <button type="button" className="btn-quiet" disabled={picked.size < 2} onClick={compareSelected}>
              Compare selected{picked.size > 0 ? ` (${picked.size})` : ""}
            </button>
            <button type="button" className="btn-quiet" onClick={() => navigate("/builder", { state: { fromShortlist: true } })}>
              Build a team from the shortlist
            </button>
            <button type="button" className="btn-primary" onClick={() => navigate("/improve", { state: { fromShortlist: true } })}>
              Improve my club with it
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Sort">
            <span className="text-sm text-ink-soft">Sort by</span>
            {(Object.keys(SORTS) as Sort[]).map((k) => (
              <button key={k} type="button" aria-pressed={sort === k} onClick={() => setSort(k)}
                      className={["rounded-md border px-3 py-1 text-sm font-semibold",
                        sort === k ? "border-board bg-board text-chalk" : "border-rule bg-surface-raised hover:bg-surface-sunk"].join(" ")}>
                {SORTS[k]}
              </button>
            ))}
            <span className="ml-auto text-xs text-ink-faint">Tick up to {MAX_COMPARE} players to compare them.</span>
          </div>

          <ul className="divide-y divide-rule rounded-lg border border-rule bg-surface-raised" aria-label="Shortlisted players">
            {rows.map((x) => {
              const up = (x.value_change_pct ?? 0) > 0, down = (x.value_change_pct ?? 0) < 0;
              return (
                <li key={x.player_id} className="grid gap-x-5 gap-y-3 px-4 py-4 md:grid-cols-[auto_minmax(13rem,1.3fr)_repeat(3,minmax(5rem,auto))_minmax(14rem,1.4fr)_auto] md:items-start">
                  <input type="checkbox" className="mt-1.5 h-4 w-4 accent-board" aria-label={`Select ${x.name} to compare`}
                         checked={picked.has(x.player_id)} onChange={() => togglePick(x.player_id)}
                         disabled={!picked.has(x.player_id) && picked.size >= MAX_COMPARE} />
                  <div className="min-w-0">
                    <Link to={`/players/${x.player_id}`} className="font-semibold underline-offset-4 hover:underline">{x.name}</Link>
                    <p className="text-xs text-ink-faint">
                      {x.role ? ROLE_NAMES[x.role] : "Position unknown"}{x.age != null ? `, age ${x.age}` : ""}
                      {x.club ? `. ${x.club} (${x.league})` : ""}
                    </p>
                    <p className="text-xs text-ink-faint">Added {added(x.added_at)}</p>
                  </div>
                  <div className="num">
                    <span className="block text-xs text-ink-faint">Score</span>
                    <span className="font-semibold">{x.score != null ? x.score.toFixed(1) : "–"}</span>
                    {x.value_for_money != null && <span className="block text-xs text-ink-soft">VfM {signed(x.value_for_money, 0)}</span>}
                  </div>
                  <div className="num">
                    <span className="block text-xs text-ink-faint">Value now</span>
                    <span className="font-semibold">{eur(x.price_eur)}</span>
                    {x.value_change_pct != null && x.value_at_add_eur != null && (
                      <span className={`block text-xs ${up ? "text-ink" : down ? "text-signal" : "text-ink-faint"}`}
                            title={`When added: ${eur(x.value_at_add_eur)}`}>
                        {up ? "▲" : down ? "▼" : ""} {x.value_change_pct === 0 ? "unchanged" : `${signed(x.value_change_pct, 0)}%`} since added
                      </span>
                    )}
                  </div>
                  <div className="num">
                    <span className="block text-xs text-ink-faint">Min. 25/26</span>
                    <span className="font-semibold">{x.minutes_next != null ? x.minutes_next.toLocaleString("en-GB") : "–"}</span>
                  </div>
                  <NoteField item={x} onSaved={(note) => setItems((cur) => cur?.map((r) => r.player_id === x.player_id ? { ...r, note } : r) ?? null)} />
                  <StarButton playerId={x.player_id} name={x.name} className="justify-self-end" />
                </li>
              );
            })}
          </ul>
          <p className="text-xs text-ink-faint">
            Values are Transfermarkt estimates. “Since added” compares today's value with the value on the day you starred him.
          </p>
        </>
      )}
    </div>
  );
}
