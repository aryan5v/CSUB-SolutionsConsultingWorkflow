import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { LockKeyhole } from "lucide-react";
import { localReviewerAuthBypassEnabled, reviewerAuth, type ReviewerAuthProvider, type ReviewerAuthSnapshot } from "./auth";
import "./app.css";

export function reviewerAuthenticationRequired(mode: "live" | "fixture", localBypass = false): boolean {
  return mode === "live" && !localBypass;
}

type ReviewerSession = {
  name: string;
  email: string;
  mode: "authenticated" | "local-bypass" | "fixture";
  signOut: () => void;
};

const ReviewerSessionContext = createContext<ReviewerSession>({
  name: "Reviewer",
  email: "reviewer@localhost",
  mode: "fixture",
  signOut: () => { window.location.assign("/"); },
});

export function useReviewerSession(): ReviewerSession {
  return useContext(ReviewerSessionContext);
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
  const localBypass = localReviewerAuthBypassEnabled();
  const session = useMemo<ReviewerSession>(() => {
    if (localBypass) return { name: "Local Reviewer", email: "reviewer@localhost", mode: "local-bypass", signOut: () => window.location.assign("/") };
    if (mode === "fixture") return { name: "Fixture Reviewer", email: "reviewer@fixture.local", mode: "fixture", signOut: () => window.location.assign("/") };
    const email = auth.email ?? "reviewer@csub.edu";
    const emailName = email.split("@")[0].split(/[._-]/).filter(Boolean).map((part) => `${part[0]?.toUpperCase() ?? ""}${part.slice(1)}`).join(" ");
    return { name: (auth.name ?? emailName) || "Reviewer", email, mode: "authenticated", signOut: () => provider.signOut() };
  }, [auth.email, auth.name, localBypass, mode, provider]);

  useEffect(() => {
    if (!reviewerAuthenticationRequired(mode, localBypass)) return;
    const unsubscribe = provider.subscribe(setAuth);
    void provider.initialize().then(setAuth);
    const expiryCheck = window.setInterval(() => provider.getAccessToken(), 15_000);
    return () => {
      unsubscribe();
      window.clearInterval(expiryCheck);
    };
  }, [localBypass, mode, provider]);

  if (!reviewerAuthenticationRequired(mode, localBypass)) return <ReviewerSessionContext.Provider value={session}>{children}</ReviewerSessionContext.Provider>;

  if (auth.status === "authenticated") {
    return <ReviewerSessionContext.Provider value={session}>{children}</ReviewerSessionContext.Provider>;
  }

  return <main className="auth-gate" id="main-content">
    <section className="auth-card" aria-labelledby="reviewer-sign-in-title">
      <img className="auth-logo" src="/vetted-logo.png" alt="" width={40} height={40} aria-hidden="true" />
      <p className="eyebrow">VETTED · CSUB REVIEWER WORKSPACE</p>
      <h1 id="reviewer-sign-in-title">Reviewer sign-in required</h1>
      {auth.status === "checking"
        ? <p role="status">Checking your session…</p>
        : <p>{auth.message ?? "Sign in with campus single sign-on to open the seeded CSUB reviewer workspace."}</p>}
      {auth.status !== "checking" && <button className="button primary" type="button" onClick={() => void provider.signIn()}>
        <LockKeyhole size={15} aria-hidden="true" />Go to sign-in
      </button>}
      {auth.status === "error" && <div className="auth-error" role="alert">{auth.message}</div>}
    </section>
  </main>;
}
