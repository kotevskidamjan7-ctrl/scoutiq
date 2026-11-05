// Login state. The token is kept in localStorage so a page refresh keeps you logged in;
// every read and write is guarded because storage can be unavailable (private windows).
import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api, setToken, setUnauthorizedHandler, User } from "./api";

const KEY = "scoutiq.token";
const read = () => { try { return localStorage.getItem(KEY); } catch { return null; } };
const write = (t: string | null) => {
  try { if (t) localStorage.setItem(KEY, t); else localStorage.removeItem(KEY); } catch { /* storage unavailable */ }
};

interface AuthState {
  user: User | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  const logout = useCallback(() => { write(null); setToken(null); setUser(null); }, []);

  useEffect(() => {
    setUnauthorizedHandler(logout);
    const saved = read();
    if (!saved) { setReady(true); return; }
    setToken(saved);
    api.me().then(setUser).catch(logout).finally(() => setReady(true));
  }, [logout]);

  const login = async (email: string, password: string) => {
    const { access_token } = await api.login(email, password);
    setToken(access_token);
    write(access_token);
    setUser(await api.me());
  };
  const register = async (email: string, password: string) => {
    await api.register(email, password);
    await login(email, password);
  };

  return <Ctx.Provider value={{ user, ready, login, register, logout }}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
