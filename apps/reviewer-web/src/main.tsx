import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import AuthGate from "./AuthGate";
import Landing from "./Landing";
import PublicIntake from "./PublicIntake";
import { LoginPage, SignupPage } from "./AuthPages";
import { consumeInviteTokenFromFragment, reviewApi } from "./api";

/*
 * One React application owns every public and authenticated surface. Route
 * selection is a small pathname switch so we avoid a router dependency:
 *   /          public VETTED landing
 *   /login     reviewer sign-in (Cognito authorization code + PKCE)
 *   /signup    reviewer account creation through the campus-hosted UI
 *   /intake    public, file-first vendor intake
 *   /app/*     authenticated reviewer workspace
 *
 * The dev server and any production host must fall back to index.html for
 * unknown paths (Vite's default SPA fallback covers dev; configure the CDN or
 * static host the same way for deploys).
 */
function resolveRoute() {
  const path = window.location.pathname.replace(/\/+$/, "");
  if (path === "/app" || path.startsWith("/app/")) return <AuthGate mode={reviewApi.mode}><App /></AuthGate>;
  if (path === "/login") return <LoginPage />;
  if (path === "/signup") return <SignupPage />;
  if (path === "/intake") {
    const token = consumeInviteTokenFromFragment(window.location, window.history, window.sessionStorage);
    return <PublicIntake initialToken={token} />;
  }
  return <Landing />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>{resolveRoute()}</StrictMode>,
);
