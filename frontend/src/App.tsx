import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ReactNode } from "react";
import { useAuth } from "./lib/auth";
import Shell from "./components/Shell";
import AuthPage from "./pages/AuthPage";
import Builder from "./pages/Builder";
import Scenarios from "./pages/Scenarios";
import ScenarioView from "./pages/ScenarioView";

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, ready } = useAuth();
  const location = useLocation();
  if (!ready) return <p className="p-8 text-ink-soft">Loading…</p>;
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<AuthPage mode="login" />} />
      <Route path="/register" element={<AuthPage mode="register" />} />
      <Route element={<RequireAuth><Shell /></RequireAuth>}>
        <Route index element={<Builder />} />
        <Route path="scenarios" element={<Scenarios />} />
        <Route path="scenarios/:id" element={<ScenarioView />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
