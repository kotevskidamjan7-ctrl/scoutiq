// Log in and create account share one layout: the empty tactics board beside a short form.
import { FormEvent, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { PitchLines } from "../components/TacticsBoard";

export default function AuthPage({ mode }: { mode: "login" | "register" }) {
  const { user, login, register } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const isLogin = mode === "login";

  if (user) return <Navigate to="/" replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null); setFieldErrors({});
    try {
      await (isLogin ? login(email, password) : register(email, password));
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        const byField: Record<string, string> = {};
        err.details.forEach((d) => { byField[d.field.split(".").pop() ?? d.field] = d.message; });
        setFieldErrors(byField);
        setError(Object.keys(byField).length ? null : err.message);
      } else setError("Something went wrong. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1fr_minmax(24rem,32rem)]">
      <div className="relative hidden overflow-hidden bg-board lg:block" aria-hidden="true">
        <div className="absolute inset-y-10 left-[55%] aspect-[2/3] opacity-60"><PitchLines /></div>
        <p className="condensed absolute bottom-10 left-10 max-w-[45%] text-5xl font-extrabold leading-[0.95] text-chalk">
          The best team your budget can actually buy.
        </p>
      </div>
      <div className="flex items-center px-4 py-10 sm:px-10">
        <form onSubmit={submit} noValidate className="w-full max-w-sm space-y-5">
          <div>
            <p className="condensed text-3xl font-extrabold">ScoutIQ</p>
            <h1 className="mt-6 text-2xl font-bold">{isLogin ? "Log in" : "Create an account"}</h1>
          </div>
          <div>
            <label htmlFor="email" className="label">Email</label>
            <input id="email" type="email" autoComplete="email" required className="field" value={email}
                   onChange={(e) => setEmail(e.target.value)} aria-invalid={!!fieldErrors.email} />
            {fieldErrors.email && <p className="mt-1 text-xs font-medium text-signal">{fieldErrors.email}</p>}
          </div>
          <div>
            <label htmlFor="password" className="label">Password</label>
            <input id="password" type="password" required className="field" value={password}
                   autoComplete={isLogin ? "current-password" : "new-password"}
                   onChange={(e) => setPassword(e.target.value)} aria-invalid={!!fieldErrors.password} />
            {fieldErrors.password
              ? <p className="mt-1 text-xs font-medium text-signal">{fieldErrors.password}</p>
              : !isLogin && <p className="mt-1 text-xs text-ink-faint">At least 10 characters, mixing letters and numbers or symbols.</p>}
          </div>
          {error && <p role="alert" className="rounded-md bg-signal-soft px-3 py-2 text-sm text-signal">{error}</p>}
          <button type="submit" className="btn-primary w-full py-2.5" disabled={busy}>
            {busy ? (isLogin ? "Logging in…" : "Creating account…") : isLogin ? "Log in" : "Create account"}
          </button>
          <p className="text-sm text-ink-soft">
            {isLogin ? "New to ScoutIQ? " : "Already have an account? "}
            <Link to={isLogin ? "/register" : "/login"} className="font-semibold text-ink underline underline-offset-4">
              {isLogin ? "Create an account" : "Log in"}
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}
