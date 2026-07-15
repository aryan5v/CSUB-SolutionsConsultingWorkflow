import { useState } from "react";
import { authClient as defaultAuthClient, type AuthClient } from "./authClient";
import { reviewerAuth } from "./auth";
import "./landing.css";

/*
 * Dedicated reviewer sign-in and account-creation surfaces. The branded page
 * starts Cognito's authorization-code-with-PKCE flow directly. Better Auth is
 * still deployed as the session service, but this direct campus path keeps
 * reviewer access independent from CDN handling of auth POST requests.
 */

const VETTED_LOGO = "/vetted-logo.png";

type Mode = "login" | "signup";

function VettedMark() {
  return <img className="vp-brand-logo" src={VETTED_LOGO} alt="" width={30} height={30} aria-hidden="true" />;
}

function AuthShell({ mode, children }: { mode: Mode; children: React.ReactNode }) {
  return (
    <div className="vp vp-auth">
      <a className="vp-skip" href="#main-content">Skip to main content</a>
      <div className="vp-band" aria-hidden="true" />
      <div className="vp-inner">
        <header className="vp-nav">
          <a className="vp-brand" href="/"><VettedMark />Vetted</a>
          <nav className="vp-nav-actions" aria-label="Account">
            {mode === "login"
              ? <a className="vp-btn vp-btn-ink vp-btn-sm" href="/signup">Create account</a>
              : <a className="vp-btn vp-btn-ink vp-btn-sm" href="/login">Sign in</a>}
          </nav>
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
        <li>Reviewers see security and accessibility findings, evidence, and packets for this workspace only.</li>
        <li>Deterministic rules set the risk route. People make the final decision.</li>
      </ul>
    </aside>
  );
}

export function AuthPage({
  mode,
  client: _client = defaultAuthClient,
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
    try {
      await reviewerAuth.signIn();
    } catch (cause) {
      setBusy(false);
      setError(cause instanceof Error ? cause.message : "That did not work. Try again.");
    }
    // On success Cognito owns the next page; keep the button busy.
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
