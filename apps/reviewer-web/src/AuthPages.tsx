import { useState } from "react";
import { authClient as defaultAuthClient, type AuthClient } from "./authClient";
import { reviewerAuth } from "./auth";
import "./landing.css";

/*
 * Dedicated reviewer sign-in surface. The branded page
 * starts Cognito's authorization-code-with-PKCE flow directly. Better Auth is
 * still deployed as the session service, but this direct campus path keeps
 * reviewer access independent from CDN handling of auth POST requests.
 */

const VETTED_LOGO = "/vetted-logo.png";

function VettedMark() {
  return <img className="vp-brand-logo" src={VETTED_LOGO} alt="" width={30} height={30} aria-hidden="true" />;
}

function AuthShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="vp vp-auth">
      <div className="vp-band" aria-hidden="true" />
      <div className="vp-inner">
        <header className="vp-nav">
          <a className="vp-brand" href="/"><VettedMark />Vetted</a>
          <div className="vp-nav-actions"><a className="vp-btn vp-btn-ink vp-btn-sm" href="/login">Reviewer sign in</a></div>
        </header>
        <main className="vp-auth-main" id="main-content">{children}</main>
      </div>
    </div>
  );
}

function WorkspaceNote() {
  return (
    <aside className="vp-auth-aside" aria-label="About this workspace">
      <p className="vp-eyebrow">SEEDED DEMO WORKSPACE</p>
      <h2>You are signing in to the CSUB workspace.</h2>
      <p>Reviewers use campus sign-in. Vendor contacts use a case-specific invitation link.</p>
      <ul className="vp-auth-points">
        <li>One reviewer workspace</li>
        <li>Case-scoped vendor access</li>
        <li>Human decisions</li>
      </ul>
    </aside>
  );
}

export function AuthPage({
  client: _client = defaultAuthClient,
}: {
  client?: AuthClient;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
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

  const title = "Sign in to Vetted";
  const lead = "Continue to the CSUB reviewer workspace.";
  const buttonLabel = busy ? "Opening campus sign-in…" : "Sign in with campus single sign-on";

  return (
    <AuthShell>
      <div className="vp-auth-grid">
        <section className="vp-auth-card" aria-labelledby="auth-title">
          <VettedMark />
          <p className="vp-eyebrow">REVIEWER SIGN IN</p>
          <h1 id="auth-title">{title}</h1>
          <p className="vp-auth-lead">{lead}</p>

          {error && <p className="vp-form-alert" role="alert">{error}</p>}

          <button className="vp-btn vp-btn-ink vp-auth-submit" type="button" onClick={start} disabled={busy}>
            {buttonLabel}
          </button>

          <p className="vp-auth-note">Authentication is handled by campus single sign-on.</p>

        </section>

        <WorkspaceNote />
      </div>
    </AuthShell>
  );
}

export function LoginPage(props: { client?: AuthClient } = {}) {
  return <AuthPage {...props} />;
}
