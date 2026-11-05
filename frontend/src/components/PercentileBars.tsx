// A player's metrics as percentile bars (0-100 against the role's regulars in his league).
// One series, so one colour; the number sits at the bar tip and the raw value beside the label.
import type { Metric } from "../lib/api";
import { metricValue } from "../lib/format";

export default function PercentileBars({ metrics }: { metrics: Metric[] }) {
  return (
    <div>
      <ul className="space-y-3">
        {metrics.map((m) => {
          const pct = m.percentile ?? 0;
          return (
            <li key={m.key} className="grid grid-cols-1 items-center gap-x-4 gap-y-1 sm:grid-cols-[minmax(9rem,14rem)_1fr]">
              <div className="text-sm">
                <span className="font-medium">{m.label}</span>
                <span className="block text-xs text-ink-faint">
                  {metricValue(m.kind, m.value)}
                  {m.lower_is_better && ", lower is better"}
                  {m.weight != null && `, weight ${Math.round(m.weight * 100)}%`}
                </span>
              </div>
              <div className="flex items-center gap-2" title={`${m.label}: better than ${Math.round(pct)}% of regulars`}>
                <div className="relative h-3 flex-1" role="img"
                     aria-label={`${m.label}: percentile ${Math.round(pct)}`}>
                  <div className="absolute inset-y-[5px] left-0 right-0 rounded-full bg-rule" />
                  <div className="absolute inset-y-0 left-0 rounded-r bg-board" style={{ width: `${Math.max(pct, 1)}%` }} />
                </div>
                <span className="num w-8 text-right text-sm font-semibold">{Math.round(pct)}</span>
              </div>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-xs text-ink-faint">
        Percentile: the share of regular players in his role and league (900+ minutes) he did better than.
      </p>
    </div>
  );
}
