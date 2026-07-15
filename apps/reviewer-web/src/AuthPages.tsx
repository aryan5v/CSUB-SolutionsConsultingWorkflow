import { useState } from "react";
import { authClient as defaultAuthClient, type AuthClient } from "./authClient";
import "./landing.css";

/*
 * Dedicated reviewer sign-in and account-creation surfaces. The auth server is
 * OIDC only, so both pages run through Better Auth generic OAuth against the
 * campus Cognito provider. Sign-in calls `signIn.oauth2`; account creation
 * calls the same route with `requestSignUp: true` so Cognito opens its sign-up
 * screen. There is no local email/password path. Failures are shown in plain
 * language; a completed sign-in returns the reviewer to the workspace at `/app`.
 */

const VETTED_LOGO = "/vetted-logo.png";

type Mode = "login" | "signup";

function VettedMark() {
  return <img className="vp-brand-logo" src={VETTED_LOGO} alt="" width={30} height={30} aria-hidden="true" />;
}

function AuthShell({ mode, children }: { mode: Mode; children: React.ReactNode }) {
  return (
    <div className="vp vp-auth">
      <div className="vp-band" aria-hidden="true" />
      <div className="vp-inner">
        <header className="vp-nav">
          <a className="vp-brand" href="/"><VettedMark />Vetted</a>
          <div className="vp-nav-actions">
            {mode === "login"
              ? <a className="vp-btn vp-btn-ink vp-btn-sm" href="/signup">Create account</a>
              : <a className="vp-btn vp-btn-ink vp-btn-sm" href="/login">Sign in</a>}
          </div>
        </header>
        <main className="vp-auth-main" id="main-content">{children}</main>
      </div>
    </div>
  );
}

function WorkspaceNote({ mode }: { mode: Mode }) {
  return (
    <aside className="vp-auth-aside" aria-label="About this workspace">
      <p className="vp-eyebrow">SEEDED DEMO WORKSPACE</p>
      <h2>{mode === "login" ? "You are signing in to the CSUB workspace." : "You are joining the CSUB workspace."}</h2>
      <p>
        Vetted runs one seeded workspace for the CSUB reviewer demo. Reviewers sign in with
        campus single sign-on. Vendor contacts never sign in; they use a case-scoped invitation
        link instead.
      </p>
      <ul className="vp-auth-points">
        <li>Sign-in and account creation both go through campus single sign-on.</li>
        <li>Reviewers see the queue, evidence, and packets for this workspace only.</li>
        <li>Deterministic rules set the risk route. People make the final decision.</li>
      </ul>
    </aside>
  );
}

export function AuthPage({
  mode,
  client = defaultAuthClient,
}: {
  mode: Mode;
  client?: AuthClient;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const isLogin = mode === "login";

  const start = async () => {
    if (busy) return;
    setBusy(true);
    setError("");
    const result = await client.signInWithCognito({ requestSignUp: !isLogin });
    if (!result.ok) {
      setBusy(false);
      setError(result.error?.message ?? "That did not work. Try again.");
      return;
    }
    // On success the client redirects to Cognito; keep the button busy.
  };

  const title = isLogin ? "Sign in to Vetted" : "Create your Vetted account";
  const lead = isLogin
    ? "Reviewers sign in to the seeded CSUB workspace with campus single sign-on."
    : "Reviewers join the seeded CSUB workspace. Account creation opens campus single sign-on.";
  const buttonLabel = isLogin
    ? (busy ? "Opening campus sign-in…" : "Sign in with campus single sign-on")
    : (busy ? "Opening campus sign-up…" : "Create account with campus single sign-on");

  return (
    <AuthShell mode={mode}>
      <div className="vp-auth-grid">
        <section className="vp-auth-card" aria-labelledby="auth-title">
          <VettedMark />
          <p className="vp-eyebrow">{isLogin ? "REVIEWER SIGN IN" : "REVIEWER SIGN UP"}</p>
          <h1 id="auth-title">{title}</h1>
          <p className="vp-auth-lead">{lead}</p>

          {error && <p className="vp-form-alert" role="alert">{error}</p>}

          <button className="vp-btn vp-btn-ink vp-auth-submit" type="button" onClick={start} disabled={busy}>
            {buttonLabel}
          </button>

          <p className="vp-auth-note">
            Campus single sign-on is the only way in. Vetted never stores your password.
          </p>

          <p className="vp-auth-switch">
            {isLogin
              ? <>New reviewer? <a href="/signup">Create an account</a>.</>
              : <>Already have an account? <a href="/login">Sign in</a>.</>}
          </p>
        </section>

        <WorkspaceNote mode={mode} />
      </div>
    </AuthShell>
  );
}

export function LoginPage(props: { client?: AuthClient } = {}) {
  return <AuthPage mode="login" {...props} />;
}

export function SignupPage(props: { client?: AuthClient } = {}) {
  return <AuthPage mode="signup" {...props} />;
}
