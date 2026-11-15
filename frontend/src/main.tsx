import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./lib/auth";
import { CompareProvider } from "./lib/compare";
import { ShortlistProvider } from "./lib/shortlist";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <ShortlistProvider>
          <CompareProvider>
            <App />
          </CompareProvider>
        </ShortlistProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
