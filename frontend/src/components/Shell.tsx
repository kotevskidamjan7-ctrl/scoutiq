// App frame: a slate rail (the board's colour) with navigation, and the page beside it.
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../lib/auth";

const link = ({ isActive }: { isActive: boolean }) =>
  [
    "block rounded-md px-3 py-2 font-semibold transition-colors",
    isActive ? "bg-marker text-board" : "text-chalk hover:bg-board-line",
  ].join(" ");

export default function Shell() {
  const { user, logout } = useAuth();
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[13rem_1fr]">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 bg-board px-4 py-3 lg:sticky lg:top-0 lg:h-screen lg:flex-col lg:flex-nowrap lg:items-stretch lg:gap-6 lg:px-3 lg:py-6">
        <p className="condensed px-3 text-3xl font-extrabold leading-none text-chalk">ScoutIQ</p>
        <nav aria-label="Main" className="flex gap-1 lg:flex-col">
          <NavLink to="/" end className={link}>Squad builder</NavLink>
          <NavLink to="/scenarios" className={link}>Saved scenarios</NavLink>
        </nav>
        <div className="ml-auto flex items-center gap-3 lg:ml-0 lg:mt-auto lg:flex-col lg:items-stretch lg:px-3">
          <p className="truncate text-sm text-chalk-dim" title={user?.email}>{user?.email}</p>
          <button type="button" onClick={logout} className="text-left text-sm font-semibold text-chalk underline-offset-4 hover:underline">
            Log out
          </button>
        </div>
      </header>
      <main className="min-w-0 px-4 py-6 sm:px-6 lg:px-8">
        <Outlet />
      </main>
    </div>
  );
}
