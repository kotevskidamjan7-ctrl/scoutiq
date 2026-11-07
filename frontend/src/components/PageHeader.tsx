// The slate board band that opens every page: title in chalk over faint pitch markings.
import { ReactNode } from "react";

function ChalkMarks() {
  // the right half of a pitch seen from above: halfway line, centre circle, penalty area, goal area
  return (
    <svg viewBox="0 0 400 240" preserveAspectRatio="xMaxYMid slice" aria-hidden="true"
         className="pointer-events-none absolute inset-y-0 right-0 h-full w-[min(70%,640px)] opacity-[0.16]">
      <g fill="none" stroke="#EEF2EF" strokeWidth="2" strokeLinecap="round">
        <line x1="40" y1="-10" x2="40" y2="250" />
        <circle cx="40" cy="120" r="58" />
        <circle cx="40" cy="120" r="3" fill="#EEF2EF" />
        <rect x="300" y="38" width="110" height="164" />
        <rect x="364" y="84" width="46" height="72" />
        <path d="M 300 92 A 40 40 0 0 0 300 148" />
        <circle cx="336" cy="120" r="3" fill="#EEF2EF" />
      </g>
    </svg>
  );
}

interface Props {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;     // e.g. a row of headline numbers
}

export default function PageHeader({ title, subtitle, actions, children }: Props) {
  return (
    <header className="relative overflow-hidden rounded-xl bg-board text-chalk">
      <ChalkMarks />
      <div className="relative px-5 py-6 sm:px-8 sm:py-7">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-0">
            <h1 className="condensed text-4xl font-extrabold leading-none sm:text-5xl">{title}</h1>
            {subtitle && <p className="mt-2 max-w-3xl text-chalk-dim">{subtitle}</p>}
          </div>
          {actions}
        </div>
        {children}
      </div>
    </header>
  );
}
