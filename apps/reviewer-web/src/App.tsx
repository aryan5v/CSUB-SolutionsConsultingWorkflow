import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BookOpenCheck,
  Building2,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  CircleDotDashed,
  ClipboardCheck,
  Clock3,
  ContactRound,
  Database,
  ExternalLink,
  FileCheck2,
  FileText,
  FolderLock,
  History,
  Inbox,
  LayoutDashboard,
  LifeBuoy,
  Link2,
  ListTodo,
  LockKeyhole,
  Menu,
  MessageCircle,
  Moon,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  StickyNote,
  Sun,
  Upload,
  UserCheck,
  Workflow,
  X,
} from "lucide-react";
import { Area, AreaChart, Legend, Tooltip, XAxis, YAxis } from "@/components/dither-kit/area-chart";
import { BarChart } from "@/components/dither-kit/bar-chart";
import { Bar } from "@/components/dither-kit/bar";
import { PieChart } from "@/components/dither-kit/pie-chart";
import { Pie } from "@/components/dither-kit/pie";
import { DitherButton } from "@/components/dither-kit/button";
import { DitherGradient } from "@/components/dither-kit/gradient";
import {
  ChatPage,
  ContactsPage,
  DocumentationPage,
  NotesPage,
  RequestsPage,
  SettingsPage,
  TasksPage,
  VendorsPage,
  WorkflowsPage,
  type RestoredPage,
} from "./WorkspacePages";
import "./app.css";

type Page = "dashboard" | "queue" | "review" | "evidence" | "audit" | RestoredPage;
type QueueMode = "all" | "inbox" | "my-work";
type Theme = "light" | "dark";
type QueueStatus = "Ready for review" | "Analyzing" | "Needs evidence" | "Completed";
type RiskRoute = "Low risk" | "Medium risk" | "Safe escalation";
type Decision = "Pending" | "Changes requested" | "Rejected" | "Approved";

type ReviewCase = {
  id: string;
  product: string;
  vendor: string;
  requester: string;
  status: QueueStatus;
  route: RiskRoute;
  match: string;
  matchDetail: string;
  stage: string;
  updated: string;
  owner: string;
};

type EvidenceItem = {
  id: string;
  name: string;
  type: string;
  scope: "Campus policy" | "Case evidence" | "Vendor evidence";
  vendor: string;
  status: "Verified" | "Review needed" | "Expired";
  location: string;
  updated: string;
};

const reviewCases: ReviewCase[] = [
  {
    id: "TR-260714-014",
    product: "LabArchives",
    vendor: "LabArchives, LLC",
    requester: "College of Science",
    status: "Ready for review",
    route: "Medium risk",
    match: "Vendor + product",
    matchDetail: "Candidate requires reviewer confirmation",
    stage: "Packet ready",
    updated: "8 min ago",
    owner: "Alex Reviewer",
  },
  {
    id: "TR-260714-011",
    product: "Notion AI",
    vendor: "Notion Labs, Inc.",
    requester: "Student Success",
    status: "Needs evidence",
    route: "Safe escalation",
    match: "Semantic candidate",
    matchDetail: "No reviewer confirmation",
    stage: "Evidence hold",
    updated: "34 min ago",
    owner: "Maya Patel",
  },
  {
    id: "TR-260714-006",
    product: "Zoom AI Companion",
    vendor: "Zoom Video Communications",
    requester: "Academic Senate",
    status: "Analyzing",
    route: "Medium risk",
    match: "Alias match",
    matchDetail: "Approved software export · Row 91",
    stage: "Specialist analysis",
    updated: "52 min ago",
    owner: "Jordan Lee",
  },
  {
    id: "TR-260714-018",
    product: "Canvas AI Assist",
    vendor: "Instructure",
    requester: "College of Education",
    status: "Completed",
    route: "Low risk",
    match: "Exact match",
    matchDetail: "Approved software export · Row 238",
    stage: "Reviewer approved",
    updated: "1 hr ago",
    owner: "Jordan Lee",
  },
  {
    id: "TR-260713-034",
    product: "Qualtrics XM",
    vendor: "Qualtrics",
    requester: "Institutional Research",
    status: "Completed",
    route: "Medium risk",
    match: "Exact match",
    matchDetail: "Approved software export · Row 144",
    stage: "Mock write-back complete",
    updated: "Yesterday",
    owner: "Maya Patel",
  },
];

const evidenceItems: EvidenceItem[] = [
  {
    id: "EV-001",
    name: "Risk Review Recommendations.xlsx",
    type: "Policy workbook",
    scope: "Campus policy",
    vendor: "Institutional",
    status: "Verified",
    location: "Routing rules · Row 18",
    updated: "Jul 14, 2026",
  },
  {
    id: "EV-014",
    name: "LabArchives VPAT 2.5.docx",
    type: "VPAT / ACR",
    scope: "Vendor evidence",
    vendor: "LabArchives, LLC",
    status: "Review needed",
    location: "Section 4 · WCAG 2.2",
    updated: "May 18, 2026",
  },
  {
    id: "EV-015",
    name: "LabArchives security overview.pdf",
    type: "Security overview",
    scope: "Case evidence",
    vendor: "LabArchives, LLC",
    status: "Verified",
    location: "Page 8 · Access controls",
    updated: "Jun 2, 2026",
  },
  {
    id: "EV-022",
    name: "Notion security overview.html",
    type: "Official vendor page",
    scope: "Vendor evidence",
    vendor: "Notion Labs, Inc.",
    status: "Expired",
    location: "Captured from notion.so",
    updated: "Nov 12, 2025",
  },
  {
    id: "EV-004",
    name: "Signed TAAP example.pdf",
    type: "Approved template",
    scope: "Campus policy",
    vendor: "Institutional",
    status: "Verified",
    location: "Page 3 · Data handling",
    updated: "Apr 29, 2026",
  },
];

const activityData = [
  { day: "Wed", intake: 3, review: 1 },
  { day: "Thu", intake: 5, review: 3 },
  { day: "Fri", intake: 4, review: 3 },
  { day: "Sat", intake: 2, review: 1 },
  { day: "Sun", intake: 1, review: 1 },
  { day: "Mon", intake: 7, review: 4 },
  { day: "Tue", intake: 6, review: 5 },
];

const activityConfig = {
  intake: { label: "Entered review", color: "blue" },
  review: { label: "Ready for a decision", color: "purple" },
} as const;

const riskData = [
  { route: "low", reviews: 24 },
  { route: "medium", reviews: 18 },
  { route: "escalated", reviews: 6 },
];

const riskConfig = {
  low: { label: "Low risk", color: "green" },
  medium: { label: "Medium risk", color: "orange" },
  escalated: { label: "Safe escalation", color: "red" },
} as const;

const evidenceChartData = [
  { scope: "Policy", verified: 12, review: 0 },
  { scope: "Case", verified: 8, review: 1 },
  { scope: "Vendor", verified: 6, review: 3 },
];

const evidenceChartConfig = {
  verified: { label: "Verified", color: "blue" },
  review: { label: "Needs review", color: "orange" },
} as const;

type NavItem = { page: Page; label: string; icon: typeof LayoutDashboard; count?: number; queueMode?: QueueMode };
const navGroups: Array<{ label: string; items: NavItem[] }> = [
  { label: "Workspace", items: [
    { page: "dashboard", label: "Dashboard", icon: LayoutDashboard },
    { page: "queue", label: "Inbox", icon: Inbox, count: 3, queueMode: "inbox" },
    { page: "queue", label: "My work", icon: ClipboardCheck, count: 1, queueMode: "my-work" },
    { page: "review", label: "Active review", icon: FileCheck2 },
    { page: "chat", label: "Chat", icon: MessageCircle },
  ] },
  { label: "Records", items: [
    { page: "vendors", label: "Vendors", icon: Building2, count: 6 },
    { page: "contacts", label: "Contacts", icon: ContactRound },
    { page: "requests", label: "Review requests", icon: FileText, count: 5 },
    { page: "tasks", label: "Tasks", icon: ListTodo, count: 4 },
    { page: "notes", label: "Notes", icon: StickyNote, count: 3 },
  ] },
  { label: "Automation", items: [
    { page: "workflows", label: "Workflows", icon: Workflow },
    { page: "workflow-runs", label: "Workflow runs", icon: CircleDotDashed },
    { page: "workflow-versions", label: "Workflow versions", icon: History },
  ] },
  { label: "Review system", items: [
    { page: "evidence", label: "Evidence", icon: FolderLock },
    { page: "audit", label: "Audit", icon: History },
  ] },
  { label: "Other", items: [
    { page: "settings", label: "Settings", icon: Settings2 },
    { page: "documentation", label: "Documentation", icon: LifeBuoy },
  ] },
];

const allNavItems = navGroups.flatMap((group) => group.items);

const workflowSteps = [
  { short: "01", label: "Intake", detail: "Required fields validated", state: "complete" },
  { short: "02", label: "Software match", detail: "Candidate found", state: "complete" },
  { short: "03", label: "Policy route", detail: "Deterministic result", state: "complete" },
  { short: "04", label: "Specialists", detail: "Parallel checks complete", state: "complete" },
  { short: "05", label: "Evidence", detail: "One gap flagged", state: "complete" },
  { short: "06", label: "Human review", detail: "Decision required", state: "current" },
  { short: "07", label: "Write-back", detail: "Locked", state: "upcoming" },
] as const;

const initialAuditEvents = [
  { time: "15:31", actor: "Packet composer", action: "Prepared packet draft v3", detail: "14 citations · 1 evidence gap" },
  { time: "15:29", actor: "Citation checker", action: "Completed the bounded repair pass", detail: "No unsupported claims remain" },
  { time: "15:24", actor: "Accessibility specialist", action: "Flagged a version-specific VPAT check", detail: "LabArchives VPAT 2.5 · Section 4" },
  { time: "15:22", actor: "Security specialist", action: "Completed scoped analysis", detail: "Case evidence only · 8 findings" },
  { time: "15:18", actor: "Policy engine", action: "Calculated a medium-risk route", detail: "Rule set v2026.07.14 · 3 citations" },
  { time: "15:12", actor: "Intake workflow", action: "Created review TR-260714-014", detail: "Sanitized local demo data" },
];


const defaultPacketDraft = "LabArchives may proceed to committee review with the mitigations and owner assignments recorded in this packet. The deterministic policy engine calculated a medium-risk route under rule set v2026.07.14. Security findings are supported by the attached case evidence. Before a final institutional decision, the reviewer must confirm that the supplied VPAT applies to the requested LabArchives product version and deployment context.\n\nThis draft does not approve the request, sign a TAAP, or authorize an external write. The reviewer remains responsible for edits, the final decision, and the separate simulated write-back confirmation.";
function statusTone(label: string) {
  if (["Completed", "Verified", "Approved", "Low risk"].includes(label)) return "positive";
  if (["Ready for review", "Medium risk", "Review needed", "Changes requested"].includes(label)) return "warning";
  if (["Needs evidence", "Expired", "Rejected", "Safe escalation"].includes(label)) return "critical";
  return "info";
}

function StatusBadge({ children }: { children: string }) {
  return <span className={`status status-${statusTone(children)}`}><span aria-hidden="true" className="status-mark" />{children}</span>;
}

function Avatar({ name, small = false }: { name: string; small?: boolean }) {
  const initials = name.split(" ").map((word) => word[0]).join("").slice(0, 2);
  return <span className={`avatar ${small ? "avatar-small" : ""}`} aria-hidden="true">{initials}</span>;
}

function PageIntro({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description: string; actions?: ReactNode }) {
  return <header className="page-intro">
    <div>
      <p className="eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      <p className="page-description">{description}</p>
    </div>
    {actions && <div className="page-actions">{actions}</div>}
  </header>;
}

function Button({ children, variant = "secondary", icon, className = "", ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger"; icon?: ReactNode }) {
  return <button className={`button button-${variant} ${className}`} {...props}>{icon}{children}</button>;
}

function MetricCard({ label, value, detail, icon, tone }: { label: string; value: string; detail: string; icon: ReactNode; tone: string }) {
  return <article className="metric-card">
    <div className={`metric-icon metric-${tone}`}>{icon}</div>
    <div className="metric-copy"><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>
  </article>;
}

function ReviewRow({ review, onOpen, compact = false }: { review: ReviewCase; onOpen: (review: ReviewCase) => void; compact?: boolean }) {
  return <button className={`review-row ${compact ? "review-row-compact" : ""}`} onClick={() => onOpen(review)}>
    <span className="review-product">
      <span className="record-glyph" aria-hidden="true">{review.product.slice(0, 2).toUpperCase()}</span>
      <span><strong>{review.product}</strong><small>{review.vendor} · {review.id}</small></span>
    </span>
    {!compact && <span className="review-requester"><strong>{review.requester}</strong><small>{review.owner}</small></span>}
    <span><StatusBadge>{review.status}</StatusBadge><small className="cell-note">{review.stage}</small></span>
    {!compact && <span><StatusBadge>{review.route}</StatusBadge><small className="cell-note">{review.match}</small></span>}
    <span className="review-updated">{review.updated}<ChevronRight size={16} aria-hidden="true" /></span>
  </button>;
}

function DashboardPage({ onNavigate, onOpenCase, onNewRequest }: { onNavigate: (page: Page) => void; onOpenCase: (review: ReviewCase) => void; onNewRequest: () => void }) {
  const actionCases = reviewCases.filter((review) => review.status === "Ready for review" || review.status === "Needs evidence");
  return <div className="dashboard-page">
    <DitherGradient from="blue" to="transparent" direction="up" cell={4} opacity={0.16} className="dashboard-gradient" />
    <div className="dashboard-content-layer">
    <PageIntro
      eyebrow="Reviewer workspace / Tuesday, July 14"
      title="Good afternoon, Alex."
      description="Two reviews need a human decision. Everything else is moving or safely paused."
      actions={<><Button variant="secondary" icon={<Upload size={15} />} onClick={onNewRequest}>New request</Button><DitherButton color="orange" variant="solid" bloom="low" className="dashboard-dither-button" onClick={() => onOpenCase(reviewCases[0])}><ClipboardCheck size={15} /> Review LabArchives</DitherButton></>}
    />

    <section className="trust-strip" aria-label="Workspace safeguards">
      <span><UserCheck size={15} />Human decision required</span>
      <span><ShieldCheck size={15} />Policy v2026.07.14</span>
      <span><LockKeyhole size={15} />Scoped evidence</span>
      <span className="simulation-label"><CircleDashed size={15} />Simulated ServiceNow</span>
    </section>

    <section className="metric-grid" aria-label="Review queue summary">
      <MetricCard label="Needs your attention" value="2" detail="1 decision · 1 evidence gap" icon={<Inbox size={18} />} tone="yellow" />
      <MetricCard label="In analysis" value="1" detail="Specialists running in parallel" icon={<Activity size={18} />} tone="blue" />
      <MetricCard label="Completed today" value="1" detail="Human-reviewed outcome" icon={<CheckCircle2 size={18} />} tone="green" />
      <MetricCard label="Safe escalations" value="1" detail="No automatic fast-path" icon={<AlertTriangle size={18} />} tone="red" />
    </section>

    <div className="dashboard-grid">
      <section className="panel attention-panel">
        <div className="panel-heading">
          <div><p className="eyebrow">Next up</p><h2>Needs attention</h2><p>Reviews remain paused until a person acts.</p></div>
          <Button variant="ghost" onClick={() => onNavigate("queue")}>View queue <ArrowRight size={14} /></Button>
        </div>
        <div className="review-list">
          {actionCases.map((review) => <ReviewRow key={review.id} review={review} compact onOpen={onOpenCase} />)}
        </div>
      </section>

      <section className="panel activity-panel">
        <div className="panel-heading">
          <div><p className="eyebrow">Last 7 days</p><h2>Review activity</h2><p>Local demo volume, not a performance score.</p></div>
          <span className="ascii-note" aria-label="Trend is increasing">TREND +</span>
        </div>
        <div className="chart-summary"><strong>23</strong><span>requests entered review</span><small>18 reached human review</small></div>
        <div className="chart-frame" aria-label="Area chart of requests entering review and reaching human review over the last seven days">
          <AreaChart data={activityData} config={activityConfig} bloom="low" animationDuration={700}>
            <XAxis dataKey="day" />
            <YAxis />
            <Legend isClickable />
            <Tooltip labelKey="day" />
            <Area dataKey="intake" variant="dotted" />
            <Area dataKey="review" variant="gradient" />
          </AreaChart>
        </div>
      </section>
    </div>

    <div className="dashboard-insight-grid">
      <section className="panel dither-insight-card">
        <div className="panel-heading"><div><p className="eyebrow">Current portfolio</p><h2>Risk routes</h2><p>Calculated routes across the sanitized local review set.</p></div><span className="ascii-note">48 CASES</span></div>
        <div className="dither-small-chart" aria-label="Pie chart showing low, medium, and safely escalated review routes">
          <PieChart data={riskData} config={riskConfig} dataKey="reviews" nameKey="route" innerRadius={0.56} bloom="low">
            <Legend isClickable align="right" />
            <Tooltip />
            <Pie variant="hatched" />
          </PieChart>
        </div>
      </section>
      <section className="panel dither-insight-card">
        <div className="panel-heading"><div><p className="eyebrow">Retrieval boundaries</p><h2>Evidence readiness</h2><p>Verified sources and items requiring reviewer attention by scope.</p></div><Button variant="ghost" onClick={() => onNavigate("evidence")}>Inspect sources</Button></div>
        <div className="dither-small-chart" aria-label="Bar chart of verified and review-needed evidence by retrieval scope">
          <BarChart data={evidenceChartData} config={evidenceChartConfig} bloom="low" animationDuration={700}>
            <XAxis dataKey="scope" />
            <YAxis />
            <Legend isClickable />
            <Tooltip labelKey="scope" />
            <Bar dataKey="verified" variant="dotted" />
            <Bar dataKey="review" variant="hatched" />
          </BarChart>
        </div>
      </section>
    </div>

    <div className="dashboard-lower-grid">
      <section className="panel workflow-panel">
        <div className="panel-heading">
          <div><p className="eyebrow">TR-260714-014</p><h2>LabArchives is ready for review</h2><p>The packet is drafted. One accessibility item still needs your judgment.</p></div>
          <StatusBadge>Ready for review</StatusBadge>
        </div>
        <ol className="workflow-rail">
          {workflowSteps.map((step) => <li key={step.short} className={`workflow-${step.state}`}>
            <span className="workflow-index">[{step.short}]</span>
            <span><strong>{step.label}</strong><small>{step.detail}</small></span>
          </li>)}
        </ol>
        <div className="panel-footer"><span><Sparkles size={14} />Specialists can draft and compare. They cannot approve.</span><Button variant="primary" onClick={() => onOpenCase(reviewCases[0])}>Open review <ArrowRight size={14} /></Button></div>
      </section>

      <section className="panel evidence-health-panel">
        <div className="panel-heading"><div><p className="eyebrow">Source boundaries</p><h2>Evidence health</h2></div><Button variant="ghost" onClick={() => onNavigate("evidence")}>Open library</Button></div>
        <div className="evidence-health-list">
          <div><span className="health-symbol health-good"><Check size={14} /></span><span><strong>Campus policy</strong><small>3 verified sources</small></span><b>Scoped</b></div>
          <div><span className="health-symbol health-good"><Check size={14} /></span><span><strong>Case evidence</strong><small>8 documents linked</small></span><b>Scoped</b></div>
          <div><span className="health-symbol health-warn">!</span><span><strong>Vendor evidence</strong><small>VPAT version needs review</small></span><b>1 gap</b></div>
        </div>
        <div className="scope-callout"><FolderLock size={17} /><span><strong>Retrieval scopes stay separate.</strong> Campus policy cannot be replaced by vendor claims, and evidence never crosses cases.</span></div>
      </section>
    </div>
    </div>
  </div>;
}

function QueuePage({ onOpenCase, onNewRequest, query, onQueryChange, mode }: { onOpenCase: (review: ReviewCase) => void; onNewRequest: () => void; query: string; onQueryChange: (value: string) => void; mode: QueueMode }) {
  const [filter, setFilter] = useState<"Open" | "All" | QueueStatus>("Open");
  const modeCases = mode === "inbox" ? reviewCases.filter((review) => review.status !== "Completed") : mode === "my-work" ? reviewCases.filter((review) => review.owner === "Alex Reviewer") : reviewCases;
  const filteredCases = modeCases.filter((review) => {
    const matchesFilter = filter === "All" || (filter === "Open" ? review.status !== "Completed" : review.status === filter);
    const haystack = `${review.product} ${review.vendor} ${review.requester} ${review.id}`.toLowerCase();
    return matchesFilter && haystack.includes(query.toLowerCase());
  });
  const title = mode === "inbox" ? "Review inbox" : mode === "my-work" ? "My work" : "Review queue";
  const description = mode === "my-work" ? "Reviews assigned to Alex Reviewer, with every evidence gap and human checkpoint visible." : "Move requests forward without hiding uncertainty, evidence gaps, or human checkpoints.";
  return <>
    <PageIntro eyebrow="Review operations" title={title} description={description} actions={<Button variant="primary" icon={<Plus size={15} />} onClick={onNewRequest}>New request</Button>} />
    <section className="panel queue-panel">
      <div className="queue-toolbar">
        <div className="filter-tabs" aria-label="Filter reviews">
          {(["Open", "Ready for review", "Needs evidence", "All"] as const).map((item) => <button key={item} className={filter === item ? "active" : ""} onClick={() => setFilter(item)} aria-pressed={filter === item}>{item}<span>{item === "All" ? modeCases.length : item === "Open" ? modeCases.filter((review) => review.status !== "Completed").length : modeCases.filter((review) => review.status === item).length}</span></button>)}
        </div>
        <label className="search-control"><Search size={15} /><span className="sr-only">Search reviews</span><input value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder="Search requests…" /></label>
      </div>
      <div className="queue-columns" aria-hidden="true"><span>Request</span><span>Requester / owner</span><span>Status</span><span>Route / match</span><span>Updated</span></div>
      <div className="review-list review-list-full">
        {filteredCases.map((review) => <ReviewRow key={review.id} review={review} onOpen={onOpenCase} />)}
        {filteredCases.length === 0 && <div className="empty-state"><Search size={18} /><strong>No reviews match this filter.</strong><span>Try another status or search term.</span></div>}
      </div>
    </section>
  </>;
}

function SpecialistCard({ icon, title, status, summary, points }: { icon: ReactNode; title: string; status: string; summary: string; points: string[] }) {
  return <article className="specialist-card">
    <div className="specialist-heading"><span>{icon}</span><div><p className="eyebrow">Bounded specialist</p><h3>{title}</h3></div><StatusBadge>{status}</StatusBadge></div>
    <p>{summary}</p>
    <ul>{points.map((point) => <li key={point}><Check size={13} />{point}</li>)}</ul>
  </article>;
}

function ReviewOverview({ onOpenEvidence, matchConfirmed, onConfirmMatch }: { onOpenEvidence: () => void; matchConfirmed: boolean; onConfirmMatch: () => void }) {
  return <div className="review-sections">
    <section className="review-section two-column-section">
      <article className="content-card">
        <div className="card-heading"><div><p className="eyebrow">01 / Intake</p><h2>Request context</h2></div><StatusBadge>Verified</StatusBadge></div>
        <dl className="detail-grid">
          <div><dt>Product</dt><dd>LabArchives</dd></div><div><dt>Vendor</dt><dd>LabArchives, LLC</dd></div>
          <div><dt>Requester</dt><dd>College of Science</dd></div><div><dt>Platform</dt><dd>Web application</dd></div>
          <div><dt>Data classification</dt><dd>Internal · sanitized demo</dd></div><div><dt>Intended users</dt><dd>Faculty and students</dd></div>
        </dl>
        <div className="narrative-block"><span>Use case</span><p>Manage electronic research notebooks for classroom and department research workflows.</p></div>
      </article>
      <article className="content-card">
        <div className="card-heading"><div><p className="eyebrow">02 / Approved software</p><h2>Candidate match</h2></div><StatusBadge>{matchConfirmed ? "Verified" : "Review needed"}</StatusBadge></div>
        <div className="match-record"><Database size={19} /><span><strong>LabArchives</strong><small>Approved software export · Row 172</small></span><b>92%</b></div>
        <dl className="compact-details"><div><dt>Method</dt><dd>Vendor + product</dd></div><div><dt>Why review?</dt><dd>Not an exact or alias match</dd></div></dl>
        <div className="match-confirm-row"><div className="boundary-note"><UserCheck size={16} /><span>{matchConfirmed ? "Alex Reviewer confirmed this candidate for the current request." : "A reviewer—not a model—must confirm this candidate."}</span></div><Button variant={matchConfirmed ? "secondary" : "primary"} disabled={matchConfirmed} onClick={onConfirmMatch} icon={matchConfirmed ? <Check size={14} /> : <UserCheck size={14} />}>{matchConfirmed ? "Candidate confirmed" : "Confirm candidate"}</Button></div>
      </article>
    </section>

    <section className="content-card policy-card">
      <div className="card-heading"><div><p className="eyebrow">03 / Deterministic policy</p><h2>Medium-risk route</h2></div><StatusBadge>Medium risk</StatusBadge></div>
      <div className="policy-layout">
        <div className="policy-result"><span className="policy-icon"><ShieldCheck size={22} /></span><div><strong>Reviewer packet required</strong><p>The route came from versioned rules. Specialist output cannot change it.</p></div></div>
        <ul className="citation-list">
          <li><Link2 size={14} /><span><strong>RR-018</strong> Risk Review Recommendations · Row 18</span></li>
          <li><Link2 size={14} /><span><strong>DT-042</strong> Decision tree · Node 42</span></li>
          <li><Link2 size={14} /><span><strong>PROC-011</strong> Risk Review Process · Page 6</span></li>
        </ul>
      </div>
    </section>

    <section>
      <div className="section-heading"><div><p className="eyebrow">04 / Parallel analysis</p><h2>Specialist findings</h2></div><span className="parallel-label">SECURITY ─┬─ ACCESSIBILITY</span></div>
      <div className="specialist-grid">
        <SpecialistCard icon={<ShieldCheck size={18} />} title="Security" status="Completed" summary="Eight findings are supported by case-scoped evidence." points={["Access controls described", "Encryption claim cited", "Retention remains a reviewer item"]} />
        <SpecialistCard icon={<BookOpenCheck size={18} />} title="Accessibility" status="Review needed" summary="The VPAT is relevant, but the product version needs confirmation." points={["WCAG 2.2 section located", "Keyboard findings cited", "Version alignment unresolved"]} />
      </div>
    </section>

    <section className="content-card">
      <div className="card-heading"><div><p className="eyebrow">05 / Evidence & citations</p><h2>One gap before decision</h2></div><StatusBadge>Review needed</StatusBadge></div>
      <div className="gap-row"><span className="gap-icon">!</span><span><strong>Confirm the VPAT applies to the requested product version.</strong><small>LabArchives VPAT 2.5.docx · Section 4</small></span><Button variant="secondary" onClick={onOpenEvidence}>Review source <ExternalLink size={14} /></Button></div>
      <div className="evidence-summary-row"><span><FileCheck2 size={16} />14 cited sources</span><span><CheckCircle2 size={16} />0 unsupported claims</span><span><FolderLock size={16} />Case and vendor scopes verified</span></div>
    </section>
  </div>;
}

function PacketEditor({ draft, onDraftChange, onSave }: { draft: string; onDraftChange: (value: string) => void; onSave: () => void }) {
  return <section className="packet-layout">
    <div className="content-card packet-editor">
      <div className="card-heading"><div><p className="eyebrow">Packet v3 / Draft</p><h2>Reviewer recommendation</h2><p>Edit the draft before making a decision. Policy results and citations remain locked.</p></div><Button variant="primary" onClick={onSave}>Save draft</Button></div>
      <label htmlFor="packet-draft">Recommendation text</label>
      <textarea id="packet-draft" value={draft} onChange={(event) => onDraftChange(event.target.value)} />
      <div className="editor-footer"><span>Edits stay in this session · Save to this browser</span><span><LockKeyhole size={13} />Policy route locked</span></div>
    </div>
    <aside className="content-card packet-outline">
      <p className="eyebrow">Packet contents</p><h2>Coverage</h2>
      <ol>{["Request summary", "Security findings", "Accessibility findings", "Evidence inventory", "Gaps and mitigations", "Source citations", "Committee routing"].map((item, index) => <li key={item}><span>{String(index + 1).padStart(2, "0")}</span>{item}<Check size={14} /></li>)}</ol>
      <div className="scope-callout"><Sparkles size={16} /><span>Drafted from approved clauses. A reviewer owns every edit and final decision.</span></div>
    </aside>
  </section>;
}

function WritebackPreview({ decision, written, onWrite }: { decision: Decision; written: boolean; onWrite: () => void }) {
  const unlocked = decision === "Approved";
  return <section className="writeback-layout">
    <div className="simulation-banner"><CircleDashed size={18} /><span><strong>Simulated ServiceNow</strong>This preview never connects to a live campus system.</span></div>
    <div className="before-after-grid">
      <article className="content-card"><p className="eyebrow">Before</p><h2>Mock request · RITM0012846</h2><dl className="change-list"><div><dt>State</dt><dd>Under review</dd></div><div><dt>Review result</dt><dd>—</dd></div><div><dt>Work note</dt><dd>Review in progress</dd></div><div><dt>Attachment</dt><dd>—</dd></div></dl></article>
      <article className="content-card after-card"><p className="eyebrow">After</p><h2>Proposed changes</h2><dl className="change-list"><div><dt>State</dt><dd><span className="diff-value">Ready for committee</span></dd></div><div><dt>Review result</dt><dd><span className="diff-value">Medium-risk packet drafted</span></dd></div><div><dt>Work note</dt><dd><span className="diff-value">Human-reviewed decision v1</span></dd></div><div><dt>Attachment</dt><dd><span className="diff-value">TR-260714-014-packet.pdf</span></dd></div></dl></article>
    </div>
    <div className={`writeback-confirm ${unlocked ? "writeback-unlocked" : ""}`}>
      <span className="writeback-lock">{written ? <CheckCircle2 size={20} /> : unlocked ? <UserCheck size={20} /> : <LockKeyhole size={20} />}</span>
      <span><strong>{written ? "Mock record updated" : unlocked ? "Second confirmation required" : "Write-back is locked"}</strong><small>{written ? "Decision v1 and packet hash were added to the local audit trail." : unlocked ? "Confirm the preview to write once to the local mock connector." : "Record an approved human decision first. Drafts and model output cannot unlock this action."}</small></span>
      <Button variant="primary" disabled={!unlocked || written} onClick={onWrite}>{written ? "Simulation complete" : "Approve & simulate write-back"}</Button>
    </div>
  </section>;
}

function DecisionPanel({ decision, matchConfirmed, onDecision, onTabChange }: { decision: Decision; matchConfirmed: boolean; onDecision: (decision: Decision) => void; onTabChange: (tab: "overview" | "packet" | "writeback") => void }) {
  return <aside className="decision-panel">
    <div className="decision-panel-heading"><span className="decision-icon"><UserCheck size={19} /></span><div><p className="eyebrow">Human checkpoint</p><h2>Your decision</h2></div></div>
    <p className="decision-copy">Review the draft, cited findings, and open accessibility item. Your action is recorded with this packet version.</p>
    <div className="decision-state"><span>Current decision</span><StatusBadge>{decision}</StatusBadge></div>
    {!matchConfirmed && <div className="decision-prerequisite"><LockKeyhole size={15} /><span><strong>Approval is locked.</strong> Confirm the vendor + product candidate in the review overview first.</span></div>}
    {decision === "Pending" ? <div className="decision-buttons">
      <Button variant="secondary" onClick={() => onDecision("Changes requested")}>Request changes</Button>
      <Button variant="danger" onClick={() => onDecision("Rejected")}>Reject</Button>
      <Button variant="primary" disabled={!matchConfirmed} onClick={() => onDecision("Approved")} icon={<Check size={15} />}>Approve draft</Button>
    </div> : <>
      <div className={`decision-message decision-${statusTone(decision)}`}><strong>{decision}</strong><span>{decision === "Approved" ? "The write-back preview is now available. A second confirmation is still required." : decision === "Rejected" ? "The case will close without write-back." : "The packet is paused for reviewer edits."}</span></div>
      <Button variant="ghost" className="full-width" onClick={() => onDecision("Pending")}>Change decision</Button>
    </>}
    <div className="decision-boundaries">
      <span><ShieldCheck size={14} />Policy result is read-only</span>
      <span><History size={14} />Every decision is audited</span>
      <span><CircleDashed size={14} />External write is simulated</span>
    </div>
    {decision === "Approved" && <Button variant="primary" className="full-width" onClick={() => onTabChange("writeback")}>Review write-back <ArrowRight size={14} /></Button>}
  </aside>;
}

function ReviewPage({ review, decision, matchConfirmed, onConfirmMatch, packetDraft, onPacketDraftChange, onSavePacket, onDecision, written, onWrite, onOpenEvidence }: { review: ReviewCase; decision: Decision; matchConfirmed: boolean; onConfirmMatch: () => void; packetDraft: string; onPacketDraftChange: (value: string) => void; onSavePacket: () => void; onDecision: (decision: Decision) => void; written: boolean; onWrite: () => void; onOpenEvidence: () => void }) {
  const [tab, setTab] = useState<"overview" | "packet" | "writeback">("overview");
  return <>
    <div className="review-page-header">
      <div className="review-title-line"><span className="record-glyph record-glyph-large">LA</span><div><p className="eyebrow">{review.id} / Active review</p><h1>{review.product}</h1><p>{review.vendor} · Requested by {review.requester}</p></div></div>
      <div className="review-header-status"><StatusBadge>{decision === "Pending" ? review.status : decision}</StatusBadge><Avatar name={review.owner} /></div>
    </div>

    <ol className="review-stepper" aria-label="Review progress">
      {workflowSteps.map((step) => <li key={step.short} className={`workflow-${step.state}`}><span>{step.state === "complete" ? <Check size={12} /> : step.short}</span><strong>{step.label}</strong></li>)}
    </ol>

    <div className="review-tabs" role="tablist" aria-label="Review sections">
      {(["overview", "packet", "writeback"] as const).map((item) => <button key={item} role="tab" aria-selected={tab === item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{item === "overview" ? "Review overview" : item === "packet" ? "Packet editor" : "Write-back preview"}{item === "packet" && <span>v3</span>}{item === "writeback" && decision !== "Approved" && <LockKeyhole size={13} />}</button>)}
    </div>

    <div className="review-workspace">
      <div className="review-main">
        {tab === "overview" && <ReviewOverview onOpenEvidence={onOpenEvidence} matchConfirmed={matchConfirmed} onConfirmMatch={onConfirmMatch} />}
        {tab === "packet" && <PacketEditor draft={packetDraft} onDraftChange={onPacketDraftChange} onSave={onSavePacket} />}
        {tab === "writeback" && <WritebackPreview decision={decision} written={written} onWrite={onWrite} />}
      </div>
      <DecisionPanel decision={decision} matchConfirmed={matchConfirmed} onDecision={onDecision} onTabChange={setTab} />
    </div>
  </>;
}

function EvidencePage() {
  const [scope, setScope] = useState<"All sources" | EvidenceItem["scope"]>("All sources");
  const [selectedId, setSelectedId] = useState(evidenceItems[1].id);
  const selected = evidenceItems.find((item) => item.id === selectedId) ?? evidenceItems[0];
  const filtered = evidenceItems.filter((item) => scope === "All sources" || item.scope === scope);
  return <>
    <PageIntro eyebrow="Grounded review material" title="Evidence" description="Inspect citations without mixing campus policy, case uploads, or official vendor material." />
    <section className="scope-strip"><FolderLock size={17} /><div><strong>Three retrieval scopes, always separate.</strong><span>Sources can support a finding; they cannot override deterministic policy or a reviewer.</span></div></section>
    <div className="evidence-layout">
      <section className="panel evidence-list-panel">
        <div className="scope-tabs" aria-label="Filter evidence by scope">{(["All sources", "Campus policy", "Case evidence", "Vendor evidence"] as const).map((item) => <button key={item} className={scope === item ? "active" : ""} onClick={() => setScope(item)}>{item}</button>)}</div>
        <div className="document-list">{filtered.map((item) => <button key={item.id} onClick={() => setSelectedId(item.id)} className={selected.id === item.id ? "selected" : ""}><span className="document-icon"><FileText size={17} /></span><span><strong>{item.name}</strong><small>{item.type} · {item.vendor}</small><em>{item.location}</em></span><StatusBadge>{item.status}</StatusBadge></button>)}</div>
      </section>
      <section className="panel evidence-preview">
        <div className="preview-toolbar"><span><FileText size={17} /><span><strong>{selected.name}</strong><small>{selected.id} · {selected.updated}</small></span></span><StatusBadge>{selected.scope}</StatusBadge></div>
        <div className="document-canvas"><article className="document-page"><header><span>[ CSUB / REVIEW SOURCE ]</span><b>{selected.scope}</b></header><div className="document-rule" /><p className="document-kicker">Referenced evidence</p><h2>{selected.name}</h2><p className="document-meta">{selected.type} · {selected.vendor} · {selected.location}</p><div className="document-highlight"><span>Cited passage</span><p>{selected.status === "Expired" ? "This captured source is outside the current evidence window. It may provide context, but it cannot support a current finding until refreshed." : selected.status === "Review needed" ? "Accessibility conformance statements must be verified against the requested product version and deployment context before reviewer approval." : "This source is linked to the current review scope and retains its source location for reviewer verification."}</p></div><div className="document-lines" aria-hidden="true"><i /><i /><i /><i /><i /></div></article></div>
        <footer className="preview-footer"><StatusBadge>{selected.status}</StatusBadge><span><Link2 size={14} />{selected.location}</span><span><FolderLock size={14} />{selected.scope}</span></footer>
      </section>
    </div>
  </>;
}

function AuditPage({ decision, written, matchConfirmed }: { decision: Decision; written: boolean; matchConfirmed: boolean }) {
  const events = useMemo(() => {
    const dynamic = [];
    if (written) dynamic.push({ time: "Now", actor: "Mock connector", action: "Completed simulated ServiceNow write-back", detail: "Decision v1 · Packet attached once" });
    if (decision !== "Pending") dynamic.push({ time: written ? "1 min ago" : "Now", actor: "Alex Reviewer", action: `Recorded decision: ${decision}`, detail: "Packet v3 · Human checkpoint" });
    if (matchConfirmed) dynamic.push({ time: decision !== "Pending" ? "2 min ago" : "Now", actor: "Alex Reviewer", action: "Confirmed vendor + product candidate", detail: "LabArchives · Approved software export row 172" });
    return [...dynamic, ...initialAuditEvents];
  }, [decision, written, matchConfirmed]);
  return <>
    <PageIntro eyebrow="Immutable local history" title="Audit" description="Trace policy versions, source checks, reviewer decisions, and every simulated connector action." />
    <section className="panel audit-panel">
      <div className="audit-summary"><div><span className="audit-symbol">LOG</span><span><strong>TR-260714-014</strong><small>Complete event history · newest first</small></span></div><div><StatusBadge>Verified</StatusBadge><span className="hash-label">CHAIN / LOCAL-DEMO-014</span></div></div>
      <div className="audit-timeline">{events.map((event, index) => <article key={`${event.time}-${event.action}`}><div className="timeline-rail"><span>{index === 0 ? <Activity size={13} /> : String(events.length - index).padStart(2, "0")}</span></div><time>{event.time}</time><div><strong>{event.actor}</strong><p>{event.action}</p><small>{event.detail}</small></div></article>)}</div>
    </section>
  </>;
}

function NewRequestDialog({ onClose, onSubmit }: { onClose: () => void; onSubmit: () => void }) {
  const submit = (event: FormEvent) => { event.preventDefault(); onSubmit(); };
  return <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="dialog" role="dialog" aria-modal="true" aria-labelledby="new-request-title">
      <div className="dialog-heading"><div><p className="eyebrow">Guided intake / Local draft</p><h2 id="new-request-title">Start a technology review</h2><p>Use sanitized information only. Required details are checked before analysis begins.</p></div><button className="icon-button" onClick={onClose} aria-label="Close dialog"><X size={18} /></button></div>
      <form onSubmit={submit}>
        <div className="form-grid"><label><span>Product name</span><input required placeholder="e.g. LabArchives" autoFocus /></label><label><span>Vendor</span><input required placeholder="Legal vendor name" /></label><label className="full-field"><span>Intended use</span><textarea required placeholder="What will the product be used for?" /></label><label><span>Data classification</span><select required defaultValue=""><option value="" disabled>Select classification</option><option>Public</option><option>Internal</option><option>Confidential</option><option>Unknown — escalate</option></select></label><label><span>Official vendor domain</span><input type="url" placeholder="https://vendor.example" /></label></div>
        <div className="form-notice"><ShieldCheck size={17} /><span>Submitting creates a local draft. It does not run analysis, approve software, or write to an external system.</span></div>
        <div className="dialog-actions"><Button variant="ghost" type="button" onClick={onClose}>Cancel</Button><Button variant="primary" type="submit">Create draft <ArrowRight size={14} /></Button></div>
      </form>
    </section>
  </div>;
}

export default function App() {
  const [page, setPage] = useState<Page>("dashboard");
  const [queueMode, setQueueMode] = useState<QueueMode>("inbox");
  const [theme, setTheme] = useState<Theme>(() => localStorage.getItem("review-theme") === "dark" ? "dark" : "light");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [selectedReview, setSelectedReview] = useState(reviewCases[0]);
  const [matchConfirmed, setMatchConfirmed] = useState(false);
  const [packetDraft, setPacketDraft] = useState(() => localStorage.getItem("review-packet-draft") ?? defaultPacketDraft);
  const [decision, setDecision] = useState<Decision>("Pending");
  const [written, setWritten] = useState(false);
  const [globalQuery, setGlobalQuery] = useState("");
  const [newRequestOpen, setNewRequestOpen] = useState(false);
  const [toast, setToast] = useState("");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem("review-theme", theme);
  }, [theme]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 3200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const navigate = (nextPage: Page, nextQueueMode?: QueueMode) => { if (nextQueueMode) setQueueMode(nextQueueMode); setPage(nextPage); setMobileNavOpen(false); window.scrollTo({ top: 0, behavior: "smooth" }); };
  const openCase = (review: ReviewCase) => {
    if (review.id !== reviewCases[0].id) {
      setToast(`${review.product} remains a queue summary. The detailed local demo workspace is scoped to LabArchives.`);
      navigate(review.status === "Needs evidence" ? "evidence" : "queue");
      return;
    }
    setSelectedReview(review);
    navigate("review");
  };
  const updatePacketDraft = (value: string) => {
    setPacketDraft(value);
    if (decision !== "Pending" || written) {
      setDecision("Pending");
      setWritten(false);
      setToast("Packet changed. The previous decision was cleared for re-review.");
    }
  };
  const confirmMatch = () => { setMatchConfirmed(true); setToast("Vendor + product candidate confirmed by Alex Reviewer."); };
  const savePacket = () => { localStorage.setItem("review-packet-draft", packetDraft); setToast("Packet draft saved in this browser."); };
  const recordDecision = (nextDecision: Decision) => {
    if (nextDecision === "Approved" && !matchConfirmed) {
      setToast("Confirm the approved-software candidate before approving the draft.");
      return;
    }
    setDecision(nextDecision);
    setWritten(false);
    setToast(nextDecision === "Pending" ? "Decision reset to pending." : `${nextDecision} recorded for packet v3.`);
  };
  const simulateWrite = () => { setWritten(true); setToast("Simulated ServiceNow write-back completed."); };
  const submitRequest = () => { setNewRequestOpen(false); setToast("Local request draft created. Add the remaining intake details before analysis."); navigate("queue"); };

  const pageLabel = page === "queue" ? (queueMode === "my-work" ? "My work" : queueMode === "inbox" ? "Inbox" : "Review queue") : allNavItems.find((item) => item.page === page)?.label ?? "Workspace";

  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Skip to content</a>
    {mobileNavOpen && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setMobileNavOpen(false)} />}
    <aside className={`sidebar ${mobileNavOpen ? "sidebar-open" : ""}`}>
      <div className="brand">
        <span className="brand-mark">[TR]</span>
        <span><strong>Technology Review</strong><small>Reviewer workspace</small></span>
        <button className="sidebar-close" onClick={() => setMobileNavOpen(false)} aria-label="Close navigation"><X size={18} /></button>
      </div>
      <div className="workspace-chip"><span>CSUB</span><div><strong>Solutions Consulting</strong><small>Sanitized local prototype</small></div></div>
      <nav className="primary-nav" aria-label="Primary navigation">
        {navGroups.map((group) => <div className="nav-group" key={group.label}><p>{group.label}</p>{group.items.map((item) => { const Icon = item.icon; const active = page === item.page && (item.page !== "queue" || !item.queueMode || queueMode === item.queueMode); return <button key={`${item.page}-${item.label}`} className={active ? "active" : ""} onClick={() => navigate(item.page, item.queueMode)} aria-current={active ? "page" : undefined}><Icon size={17} /><span>{item.label}</span>{item.count && <em>{item.count}</em>}</button>; })}</div>)}
      </nav>
      <div className="sidebar-spacer" />
      <div className="boundary-card"><ShieldCheck size={17} /><div><strong>Human-controlled</strong><span>AI can draft and compare. It cannot set policy, approve, or write externally.</span></div></div>
      <div className="profile"><Avatar name="Alex Reviewer" small /><div><strong>Alex Reviewer</strong><span>Information Security</span></div><span className="presence-dot" aria-label="Online" /></div>
    </aside>

    <div className="app-main">
      <header className="topbar">
        <div className="topbar-left"><button className="mobile-menu" onClick={() => setMobileNavOpen(true)} aria-label="Open navigation"><Menu size={19} /></button><span className="topbar-context">CSUB <i>/</i> <strong>{pageLabel}</strong></span></div>
        <div className="topbar-actions">
          <label className="global-search"><Search size={15} /><span className="sr-only">Search the review queue</span><input value={globalQuery} onChange={(event) => setGlobalQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") navigate("queue"); }} placeholder="Search reviews" /></label>
          <button className="icon-button theme-button" onClick={() => setTheme(theme === "light" ? "dark" : "light")} aria-label={`Switch to ${theme === "light" ? "dark" : "light"} mode`}>{theme === "light" ? <Moon size={17} /> : <Sun size={17} />}</button>
          <span className="topbar-divider" />
          <Avatar name="Alex Reviewer" small />
        </div>
      </header>

      <main id="main-content" className={`content ${page === "review" ? "content-wide" : ""}`}>
        {page === "dashboard" && <DashboardPage onNavigate={navigate} onOpenCase={openCase} onNewRequest={() => setNewRequestOpen(true)} />}
        {page === "queue" && <QueuePage onOpenCase={openCase} onNewRequest={() => setNewRequestOpen(true)} query={globalQuery} onQueryChange={setGlobalQuery} mode={queueMode} />}
        {page === "review" && <ReviewPage review={selectedReview} decision={decision} matchConfirmed={matchConfirmed} onConfirmMatch={confirmMatch} packetDraft={packetDraft} onPacketDraftChange={updatePacketDraft} onSavePacket={savePacket} onDecision={recordDecision} written={written} onWrite={simulateWrite} onOpenEvidence={() => navigate("evidence")} />}
        {page === "vendors" && <VendorsPage notify={setToast} />}
        {page === "contacts" && <ContactsPage notify={setToast} />}
        {page === "requests" && <RequestsPage onOpenReview={() => navigate("review")} notify={setToast} />}
        {page === "tasks" && <TasksPage notify={setToast} />}
        {page === "notes" && <NotesPage notify={setToast} />}
        {(page === "workflows" || page === "workflow-runs" || page === "workflow-versions") && <WorkflowsPage view={page} navigate={(nextPage) => navigate(nextPage)} notify={setToast} />}
        {page === "chat" && <ChatPage notify={setToast} />}
        {page === "settings" && <SettingsPage notify={setToast} />}
        {page === "documentation" && <DocumentationPage notify={setToast} />}
        {page === "evidence" && <EvidencePage />}
        {page === "audit" && <AuditPage decision={decision} written={written} matchConfirmed={matchConfirmed} />}
      </main>
    </div>

    {newRequestOpen && <NewRequestDialog onClose={() => setNewRequestOpen(false)} onSubmit={submitRequest} />}
    <div className={`toast ${toast ? "toast-visible" : ""}`} role="status" aria-live="polite"><CheckCircle2 size={16} />{toast}</div>
  </div>;
}
