import type { CSSProperties, ReactNode } from "react";
import "./landing.css";

/*
 * Public landing surface for the CSUB Technology Review Agent ("Vetted").
 * Visual language adapted from the PR #11 Paper reference: an isometric
 * automation line that carries a request in, runs evidence and policy checks,
 * pauses for human review, and sends an approved result out.
 *
 * Copy went through the repository humanizer draft/audit/final pass. It keeps
 * the precise policy and security terms (deterministic rules, citations,
 * approved-software export, mock ServiceNow) and drops em/en dashes and
 * promotional filler. No invented metrics or third-party logos appear here.
 */

function PixelLogo({ size = 30, style }: { size?: number; style?: CSSProperties }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 30 30"
      xmlns="http://www.w3.org/2000/svg"
      style={{ flexShrink: 0, ...style }}
      aria-hidden="true"
    >
      <rect x="2" y="2" width="6" height="6" fill="#333333" />
      <rect x="9" y="2" width="6" height="6" fill="#3178C6" />
      <rect x="2" y="9" width="6" height="6" fill="#AAAAAA" />
      <rect x="9" y="9" width="6" height="6" fill="#333333" />
      <rect x="16" y="9" width="6" height="6" fill="#F7DC6F" />
      <rect x="9" y="16" width="6" height="6" fill="#CCCCCC" />
      <rect x="16" y="16" width="6" height="6" fill="#3178C6" />
      <rect x="23" y="16" width="6" height="6" fill="#F7DC6F" />
      <rect x="16" y="23" width="6" height="6" fill="#AAAAAA" />
      <rect x="23" y="23" width="6" height="6" fill="#333333" />
    </svg>
  );
}

function Machine({ className, style }: { className?: string; style?: CSSProperties }) {
  return (
    <svg className={className} viewBox="0 0 320 300" xmlns="http://www.w3.org/2000/svg" style={style} aria-hidden="true">
      <path d="M57.5 240L126.7 280L126.7 175L57.5 135Z" fill="#EEEEEE" stroke="#CCCCCC" strokeLinejoin="round" />
      <path d="M126.7 280L282.5 190L282.5 85L126.7 175Z" fill="#FFFFFF" stroke="#CCCCCC" strokeLinejoin="round" />
      <path d="M57.5 135L126.7 175L282.5 85L213.3 45Z" fill="#F7F7F7" stroke="#CCCCCC" strokeLinejoin="round" />
      <path d="M152.6 265L256.6 205L256.6 133L152.6 193Z" fill="#EEEEEE" stroke="#CCCCCC" strokeLinejoin="round" />
      <g transform="translate(170,110) scale(1,0.55) rotate(45) scale(1.5) translate(-15,-15)">
        <rect x="2" y="2" width="6" height="6" fill="#333333" />
        <rect x="9" y="2" width="6" height="6" fill="#3178C6" />
        <rect x="2" y="9" width="6" height="6" fill="#AAAAAA" />
        <rect x="9" y="9" width="6" height="6" fill="#333333" />
        <rect x="16" y="9" width="6" height="6" fill="#F7DC6F" />
        <rect x="9" y="16" width="6" height="6" fill="#CCCCCC" />
        <rect x="16" y="16" width="6" height="6" fill="#3178C6" />
        <rect x="23" y="16" width="6" height="6" fill="#F7DC6F" />
        <rect x="16" y="23" width="6" height="6" fill="#AAAAAA" />
        <rect x="23" y="23" width="6" height="6" fill="#333333" />
      </g>
    </svg>
  );
}

type TileVariant = "doc" | "spark" | "mail" | "bolt" | "check";

function IsoTile({ variant, className, style }: { variant: TileVariant; className?: string; style?: CSSProperties }) {
  const face = (
    <>
      {variant === "doc" && (
        <>
          <rect x="-17" y="-17" width="34" height="34" rx="8" fill="#333333" />
          <path d="M-8 -6H8M-8 0H8M-8 6H3" fill="none" stroke="#F7DC6F" strokeWidth="2.6" strokeLinecap="round" />
        </>
      )}
      {variant === "spark" && (
        <>
          <path d="M0 -15V15M-13 -7.5L13 7.5M-13 7.5L13 -7.5" fill="none" stroke="#3178C6" strokeWidth="4" strokeLinecap="round" />
          <circle cx="0" cy="0" r="4.5" fill="#F7F7F7" />
        </>
      )}
      {variant === "mail" && (
        <>
          <rect x="-15" y="-11" width="30" height="22" rx="4" fill="#333333" />
          <path d="M-12 -7L0 2L12 -7" fill="none" stroke="#F7DC6F" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
        </>
      )}
      {variant === "bolt" && (
        <>
          <rect x="-17" y="-17" width="34" height="34" rx="8" fill="#333333" />
          <path d="M3 -11L-7 2H0L-3 11L7 -2H0L3 -11Z" fill="#F7DC6F" />
        </>
      )}
      {variant === "check" && (
        <>
          <rect x="-17" y="-17" width="34" height="34" rx="8" fill="#FFFFFF" stroke="#CCCCCC" />
          <path d="M-8 0.5L-2.5 6L9 -6" fill="none" stroke="#3178C6" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        </>
      )}
    </>
  );

  const topFill = variant === "check" ? "#FFFFFF" : "#F7F7F7";

  return (
    <svg className={className} viewBox="0 0 120 100" xmlns="http://www.w3.org/2000/svg" style={style} aria-hidden="true">
      <g transform="translate(60,56) scale(1,0.55) rotate(45)">
        <rect x="-39" y="-39" width="78" height="78" rx="18" fill="#CCCCCC" />
      </g>
      <g transform="translate(60,48) scale(1,0.55) rotate(45)">
        <rect x="-39" y="-39" width="78" height="78" rx="18" fill={topFill} stroke="#CCCCCC" />
        {face}
      </g>
    </svg>
  );
}

function ArrowIcon({ dark = false }: { dark?: boolean }) {
  return (
    <svg width="17" height="16" viewBox="0 0 17 16" xmlns="http://www.w3.org/2000/svg" style={{ flexShrink: 0 }} aria-hidden="true">
      <path d="M2 8H14M14 8L9.2 3.2M14 8L9.2 12.8" fill="none" stroke={dark ? "#333333" : "#FFFFFF"} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function CheckMark() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" style={{ flexShrink: 0 }} aria-hidden="true">
      <path d="M2.5 7.5L5.5 10.5L11.5 4" fill="none" stroke="#3178C6" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const steps: Array<{ n: string; title: string; body: string; tile: TileVariant }> = [
  {
    n: "01",
    title: "AI reads the evidence",
    body:
      "After intake and the approved-software lookup, security and accessibility specialists read the vendor and institutional documents in parallel. Approved research on official vendor domains fills gaps that the evidence supports. A citation checker removes any claim the sources do not back.",
    tile: "doc",
  },
  {
    n: "02",
    title: "Deterministic rules set the route",
    body:
      "Ordinary code, not the model, applies the versioned flowchart and decision-tree rules. It returns the risk route, the required evidence, the conflicts, and the citations. A model can explain that result. It cannot change it.",
    tile: "spark",
  },
  {
    n: "03",
    title: "A person makes the decision",
    body:
      "Reviewers see the merged findings and the drafted low or medium risk packet, confirm any fuzzy match, then approve, reject, or ask for more information. Write-back needs a second explicit confirmation and goes to a mock ServiceNow connector.",
    tile: "check",
  },
];

const features: Array<{ title: string; body: string; iconBg: string; icon: ReactNode }> = [
  {
    title: "Approved-software flag",
    body:
      "If the product is already on the export, Vetted shows it as a candidate. If it is not, the case gets a flag for review rather than an automatic rejection. Fuzzy or semantic matches still need a reviewer to confirm them.",
    iconBg: "#F7DC6F",
    icon: (
      <path d="M3 10H9M9 10L13 5H17M9 10L13 15H17M15 3L17 5L15 7M15 13L17 15L15 17" fill="none" stroke="#333333" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    ),
  },
  {
    title: "Specialists draft, rules enforce",
    body:
      "Specialists extract and summarize security, accessibility, and evidence findings. The business-rules engine calculates the risk route and the required documents from the partner flowcharts and decision trees. The model drafts. The rules hold the policy.",
    iconBg: "#3178C6",
    icon: (
      <>
        <circle cx="10" cy="7" r="3.2" fill="none" stroke="#FFFFFF" strokeWidth="1.6" />
        <path d="M4 17C4.8 13.8 7.2 12.4 10 12.4C12.8 12.4 15.2 13.8 16 17" fill="none" stroke="#FFFFFF" strokeWidth="1.6" strokeLinecap="round" />
      </>
    ),
  },
  {
    title: "The reviewer decides",
    body:
      "The reviewer gets a low-risk recommendation or an editable medium-risk TAAP and security packet. High-risk, contradictory, unsupported, or incomplete cases escalate. Nothing is approved, signed, or written to ServiceNow without a recorded human decision.",
    iconBg: "#333333",
    icon: (
      <>
        <path d="M4 4H16M4 8H16M4 12H10" fill="none" stroke="#FFFFFF" strokeWidth="1.6" strokeLinecap="round" />
        <path d="M12 15L14 17L18 13" fill="none" stroke="#F7DC6F" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </>
    ),
  },
];

const stats: Array<{ value: string; label: string }> = [
  { value: "Extract", label: "specialists pull facts from policies, HECVAT, SOC 2, VPAT, and similar sources" },
  { value: "Route", label: "deterministic rules set the risk path: low, medium, or escalate" },
  { value: "Decide", label: "the reviewer approves, rejects, or asks for more information" },
];

export default function Landing() {
  return (
    <div className="vp">
      <div className="vp-band" aria-hidden="true" />

      <div className="vp-inner">
        <header className="vp-nav">
          <a className="vp-brand" href="/">
            <PixelLogo />
            Vetted
          </a>
          <div className="vp-nav-actions">
            <a className="vp-nav-login" href="/app">
              Log in
            </a>
            <a className="vp-btn vp-btn-ink vp-btn-sm" href="/app">
              Open the workspace
            </a>
          </div>
        </header>

        <section className="vp-hero" id="top">
          <svg className="vp-dots" viewBox="0 0 480 150" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <defs>
              <pattern id="dotGrid" width="22" height="22" patternUnits="userSpaceOnUse">
                <circle cx="1.5" cy="1.5" r="1.5" fill="#CCCCCC" />
              </pattern>
              <radialGradient id="dotFade" cx="35%" cy="50%" r="78%">
                <stop offset="0%" stopColor="#F7F7F7" stopOpacity="0" />
                <stop offset="100%" stopColor="#F7F7F7" stopOpacity="1" />
              </radialGradient>
            </defs>
            <rect width="480" height="150" fill="url(#dotGrid)" />
            <rect width="480" height="150" fill="url(#dotFade)" />
          </svg>

          <div className="vp-hero-copy land-fade-up">
            <h1 className="vp-hero-title">
              Vetted.
              <br />
              Evidence in.
              <br />
              Decision out.
            </h1>
            <p className="vp-hero-lead land-fade-up-delay">
              Requesters submit proposed software and vendor evidence. Vetted checks the approved-software export,
              extracts facts with bounded specialists, applies deterministic policy rules, and drafts a cited packet.
              A reviewer then makes the final call.
            </p>
            <div className="vp-cta-row land-fade-up-delay">
              <a className="vp-btn vp-btn-ink" href="/app">
                Open the workspace
                <ArrowIcon />
              </a>
              <a className="vp-btn vp-btn-primary" href="#workflow">
                See how a review runs
              </a>
            </div>
            <div className="vp-checks land-fade-up-delay-2">
              {["AI reads the evidence", "Rules set the route", "People approve"].map((label) => (
                <div key={label} className="vp-check">
                  <CheckMark />
                  {label}
                </div>
              ))}
            </div>
          </div>

          <div className="vp-scene land-fade-up-delay-2" aria-hidden="true">
            <div className="vp-scene-canvas">
              <IsoTile variant="doc" className="vp-scene-tile vp-scene-tile-1" />
              <IsoTile variant="spark" className="vp-scene-tile vp-scene-tile-2" />
              <IsoTile variant="mail" className="vp-scene-tile vp-scene-tile-3" />
              <IsoTile variant="bolt" className="vp-scene-tile vp-scene-tile-4" />
              <Machine className="vp-scene-machine" />
              <IsoTile variant="check" className="vp-scene-tile vp-scene-tile-5" />
              <IsoTile variant="check" className="vp-scene-tile vp-scene-tile-6" />
              <IsoTile variant="check" className="vp-scene-tile vp-scene-tile-7" />

              <div className="vp-chip vp-chip-a land-float">
                <svg width="14" height="14" viewBox="0 0 14 14" className="land-spin-soft" aria-hidden="true">
                  <path d="M7 1.5A5.5 5.5 0 1 1 1.5 7" fill="none" stroke="#AAAAAA" strokeWidth="1.8" strokeLinecap="round" />
                </svg>
                Processing intake
              </div>
              <div className="vp-chip vp-chip-b land-float-delayed">
                <svg width="15" height="15" viewBox="0 0 15 15" className="land-pulse-dot" aria-hidden="true">
                  <circle cx="7.5" cy="7.5" r="7" fill="#3178C6" />
                  <path d="M4.5 7.8L6.6 9.9L10.5 5.5" fill="none" stroke="#FFFFFF" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Flag only, still waiting on human review
              </div>
            </div>
          </div>
        </section>

        <section className="vp-trusted" id="product">
          <div className="vp-trusted-label">Eight moving parts, one review path</div>
          <div className="vp-trusted-row">
            {["UI", "APIs", "Storage", "LangGraph", "Rules", "Review", "ServiceNow mock", "AWS"].map((part) => (
              <div key={part} className="vp-trusted-item">
                <span className="vp-trusted-mark" />
                {part}
              </div>
            ))}
          </div>
        </section>

        <svg className="vp-waves" viewBox="0 0 1200 80" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <defs>
            <linearGradient id="waveGray" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0" stopColor="#CCCCCC" stopOpacity="0" />
              <stop offset="0.15" stopColor="#CCCCCC" stopOpacity="1" />
              <stop offset="0.85" stopColor="#CCCCCC" stopOpacity="1" />
              <stop offset="1" stopColor="#CCCCCC" stopOpacity="0" />
            </linearGradient>
            <linearGradient id="waveAccent" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0" stopColor="#F7DC6F" stopOpacity="0" />
              <stop offset="0.5" stopColor="#F7DC6F" stopOpacity="0.7" />
              <stop offset="1" stopColor="#F7DC6F" stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d="M0 40 C50 20 100 20 150 40 S250 60 300 40 S400 20 450 40 S550 60 600 40 S700 20 750 40 S850 60 900 40 S1000 20 1050 40 S1150 60 1200 40" fill="none" stroke="url(#waveGray)" strokeWidth="1.5" />
          <path d="M0 52 C50 32 100 32 150 52 S250 72 300 52 S400 32 450 52 S550 72 600 52 S700 32 750 52 S850 72 900 52 S1000 32 1050 52 S1150 72 1200 52" fill="none" stroke="url(#waveGray)" strokeWidth="1.5" opacity="0.65" />
          <path d="M0 28 C50 8 100 8 150 28 S250 48 300 28 S400 8 450 28 S550 48 600 28 S700 8 750 28 S850 48 900 28 S1000 8 1050 28 S1150 48 1200 28" fill="none" stroke="url(#waveGray)" strokeWidth="1.5" opacity="0.65" />
          <path d="M0 46 C50 26 100 26 150 46 S250 66 300 46 S400 26 450 46 S550 66 600 46 S700 26 750 46 S850 66 900 46 S1000 26 1050 46 S1150 66 1200 46" fill="none" stroke="url(#waveAccent)" strokeWidth="1.5" />
        </svg>

        <section className="vp-block" id="workflow">
          <div className="vp-header">
            <p className="vp-eyebrow">HOW A REVIEW RUNS</p>
            <h2 className="vp-h2">You hand over the documents. Three layers finish the review.</h2>
          </div>
          <div className="vp-steps">
            {steps.map((step) => (
              <article key={step.n} className="vp-step">
                <IsoTile variant={step.tile} style={{ width: 96, height: 80 }} />
                <div className="vp-step-title-row">
                  <span className="vp-step-num">{step.n}</span>
                  <h3 className="vp-step-title">{step.title}</h3>
                </div>
                <p className="vp-step-body">{step.body}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="vp-block" id="trust">
          <svg className="vp-smoke" viewBox="-170 -170 530 530" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <defs>
              <radialGradient id="smokeA">
                <stop offset="0.45" stopColor="#333333" stopOpacity="0" />
                <stop offset="0.62" stopColor="#333333" stopOpacity="0.07" />
                <stop offset="0.72" stopColor="#333333" stopOpacity="0.02" />
                <stop offset="0.82" stopColor="#333333" stopOpacity="0" />
              </radialGradient>
              <radialGradient id="smokeB">
                <stop offset="0.5" stopColor="#F7DC6F" stopOpacity="0" />
                <stop offset="0.58" stopColor="#F7DC6F" stopOpacity="0.22" />
                <stop offset="0.66" stopColor="#F7DC6F" stopOpacity="0" />
              </radialGradient>
            </defs>
            <circle cx="95" cy="95" r="265" fill="url(#smokeA)" />
            <circle cx="95" cy="95" r="265" fill="url(#smokeB)" />
          </svg>

          <div className="vp-header">
            <p className="vp-eyebrow">WHAT A FLAG MEANS</p>
            <h2 className="vp-h2">A missing list entry is not a rejection.</h2>
          </div>

          <div className="vp-features">
            {features.map((card) => (
              <article key={card.title} className="vp-feature">
                <div className="vp-feature-icon" style={{ background: card.iconBg }}>
                  <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true">
                    {card.icon}
                  </svg>
                </div>
                <h3 className="vp-feature-title">{card.title}</h3>
                <p className="vp-feature-body">{card.body}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="vp-stats" aria-label="How the review works">
          {stats.map((stat) => (
            <div key={stat.value} className="vp-stat">
              <p className="vp-stat-value">{stat.value}</p>
              <p className="vp-stat-label">{stat.label}</p>
            </div>
          ))}
        </section>

        <section className="vp-cta-wrap" id="demo">
          <div className="vp-cta">
            <svg className="vp-cta-shader" viewBox="0 0 1056 320" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <defs>
                <radialGradient id="ctaYellow" cx="12%" cy="8%" r="58%">
                  <stop offset="0%" stopColor="#F7DC6F" stopOpacity="0.35" />
                  <stop offset="100%" stopColor="#F7DC6F" stopOpacity="0" />
                </radialGradient>
                <radialGradient id="ctaBlue" cx="88%" cy="96%" r="62%">
                  <stop offset="0%" stopColor="#3178C6" stopOpacity="0.28" />
                  <stop offset="100%" stopColor="#3178C6" stopOpacity="0" />
                </radialGradient>
              </defs>
              <rect width="1056" height="320" fill="url(#ctaYellow)" />
              <rect width="1056" height="320" fill="url(#ctaBlue)" />
            </svg>
            <div className="vp-cta-copy">
              <h2 className="vp-cta-title">From request to mock ServiceNow, with a person in the middle.</h2>
              <p className="vp-cta-lead">
                The path runs frontend, APIs, storage, LangGraph specialists, business rules, the reviewer workspace,
                and the mock ServiceNow connector, on AWS.
              </p>
              <a className="vp-btn vp-btn-primary" href="/intake">
                Submit a vendor for review
                <ArrowIcon dark />
              </a>
            </div>
            <Machine className="vp-cta-art" />
          </div>
        </section>

        <footer className="vp-footer">
          <div className="vp-footer-brand">
            <PixelLogo size={24} />
            Vetted. AI reads, rules route, people decide.
          </div>
          <div className="vp-footer-links">
            <a href="/app">Log in</a>
            <a href="/intake">Submit a vendor</a>
            <span className="vp-footer-copy">CSU AI Summer Camp 2026</span>
          </div>
        </footer>
      </div>
    </div>
  );
}
