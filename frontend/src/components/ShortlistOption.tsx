// "Only players on my shortlist": lets the optimizer buy only starred players.
import { Link } from "react-router-dom";
import { useShortlist } from "../lib/shortlist";
import { Star } from "./StarButton";

export default function ShortlistOption({ checked, onChange, error }: {
  checked: boolean; onChange: (v: boolean) => void; error?: string;
}) {
  const { ids } = useShortlist();
  const n = ids.size;
  return (
    <div className={`rounded-md border px-3 py-2.5 ${checked ? "border-marker bg-surface-raised" : "border-rule bg-surface-raised"}`}>
      <label className="flex items-start gap-2.5">
        <input id="fromShortlist" type="checkbox" className="mt-0.5 h-4 w-4 accent-board" checked={checked}
               onChange={(e) => onChange(e.target.checked)} aria-invalid={!!error}
               aria-describedby={error ? "fromShortlist-error" : undefined} />
        <span className="min-w-0">
          <span className="flex items-center gap-1.5 font-semibold">
            <Star on={checked} className="h-4 w-4" /> Only players on my shortlist
            <span className="num font-normal text-ink-soft">({n})</span>
          </span>
          <span className="block text-xs text-ink-soft">
            Signings are picked only from the players you starred.{" "}
            <Link to="/shortlist" className="underline underline-offset-2">See the shortlist</Link>
          </span>
        </span>
      </label>
      {error && <p id="fromShortlist-error" className="mt-1 text-xs font-medium text-signal">{error}</p>}
    </div>
  );
}
