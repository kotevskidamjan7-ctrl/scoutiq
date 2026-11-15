// Adds a player to the shortlist or removes him. "icon" for lists, "full" for page headers.
import { useShortlist } from "../lib/shortlist";

export function Star({ on, className = "h-5 w-5" }: { on: boolean; className?: string }) {
  return (
    <svg viewBox="0 0 20 20" className={className} aria-hidden="true">
      <path d="M10 1.8l2.47 5.2 5.7.68-4.2 3.92 1.1 5.64L10 14.43 4.93 17.24l1.1-5.64L1.83 7.68l5.7-.68L10 1.8z"
            fill={on ? "#F2C230" : "none"} stroke={on ? "#B88F12" : "currentColor"} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

export default function StarButton({ playerId, name, variant = "icon", className = "" }: {
  playerId: number; name: string; variant?: "icon" | "full"; className?: string;
}) {
  const { has, toggle } = useShortlist();
  const on = has(playerId);
  const label = on ? `Remove ${name} from shortlist` : `Add ${name} to shortlist`;
  if (variant === "full") {
    return (
      <button type="button" onClick={() => toggle(playerId)} aria-pressed={on}
              className={["inline-flex items-center gap-2 rounded-md border px-3.5 py-2 text-sm font-semibold",
                on ? "border-marker bg-surface-raised text-ink" : "border-rule bg-surface-raised text-ink hover:border-board",
                className].join(" ")}>
        <Star on={on} />
        {on ? "On shortlist" : "Add to shortlist"}
      </button>
    );
  }
  return (
    <button type="button" onClick={() => toggle(playerId)} aria-pressed={on} aria-label={label} title={label}
            className={["inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-ink-faint hover:bg-surface-sunk hover:text-ink",
              "focus-visible:outline focus-visible:outline-2 focus-visible:outline-board", className].join(" ")}>
      <Star on={on} />
    </button>
  );
}
