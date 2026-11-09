// "Back to …": returns to the page the person came from (keeping its filters), or to a parent page.
import { useNavigate } from "react-router-dom";
import { backTarget } from "../lib/backTo";

export default function BackButton({ fallback, fallbackName, className = "" }: {
  fallback: string; fallbackName: string; className?: string;
}) {
  const navigate = useNavigate();
  const { to, label } = backTarget(fallback, fallbackName);
  return (
    <button type="button" onClick={() => (to === -1 ? navigate(-1) : navigate(to))}
            className={["group inline-flex items-center gap-2 rounded-md border border-rule bg-surface-raised py-1.5 pl-2.5 pr-3.5",
              "text-sm font-semibold text-ink shadow-sm hover:border-board hover:bg-surface-sunk",
              "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-board", className].join(" ")}>
      <svg viewBox="0 0 20 20" className="h-4 w-4 transition-transform group-hover:-translate-x-0.5" aria-hidden="true">
        <path d="M12.5 4.5 7 10l5.5 5.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {label}
    </button>
  );
}
