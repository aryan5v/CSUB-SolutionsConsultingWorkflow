import { useEffect, useState, type ReactNode } from "react";
import { LockKeyhole, LogOut, ShieldCheck } from "lucide-react";
import { reviewerAuth, type ReviewerAuthProvider, type ReviewerAuthSnapshot } from "./auth";

export function reviewerAuthenticationRequired(mode: "live" | "fixture"): boolean {
  return mode === "live";
}

export default function AuthGate({
  children,
  mode,
  provider = reviewerAuth,
}: {
  children: ReactNode;
  mode: "live" | "fixture";
  provider?: ReviewerAuthProvider;
}) {
  const [auth, setAuth] = useState<ReviewerAuthSnapshot>(() => provider.getSnapshot());

  useEffect(() => {
    if (!reviewerAuthenticationRequired(mode)) return;
    const unsubscribe = provider.subscribe(setAuth);
    void provider.initialize().then(setAuth);
    const expiryCheck = window.setInterval(() => provider.getAccessToken(), 15_000);
    return () => {
      unsubscribe();
      window.clearInterval(expiryCheck);
    };
  }, [mode, provider]);

  if (!reviewerAuthenticationRequired(mode)) return children;

  if (auth.status === "authenticated") {
    return <>
      <div className="reviewer-session" role="status">
        <ShieldCheck size={15} aria-hidden="true" />
        <span>Authenticated reviewer{auth.email ? ` · ${auth.email}` : ""}</span>
        <button type="button" onClick={() => provider.signOut()}><LogOut size={14} aria-hidden="true" />Sign out</button>
      </div>
      {children}
    </>;
  }

  return <main className="auth-gate" id="main-content">
    <section className="auth-card" aria-labelledby="reviewer-sign-in-title">
      <div className="auth-icon"><LockKeyhole size={24} aria-hidden="true" /></div>
      <p className="eyebrow">CSUB · SECURE REVIEWER WORKSPACE</p>
      <h1 id="reviewer-sign-in-title">Reviewer sign-in required</h1>
      {auth.status === "checking"
        ? <p role="status">Checking your session…</p>
        : <p>{auth.message ?? "Use the seeded Cognito reviewer account supplied by the demo operator."}</p>}
      {auth.status !== "checking" && <button className="button primary" type="button" onClick={() => void provider.signIn()}>
        Sign in with Cognito
      </button>}
      {auth.status === "error" && <div className="auth-error" role="alert">{auth.message}</div>}
      <small>Live mode never falls back to fixture records. Credentials are entered only on Cognito Managed Login.</small>
    </section>
  </main>;
}
