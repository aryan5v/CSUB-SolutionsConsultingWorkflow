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
  ReviewApiError,
  decisionVersion,
  packetEditSection,
  packetToDraft,
  queueItemToSummary,
  reviewApi,
  type CaseActionResponse,
  type CaseIntakeInput,
  type QueueStatus,
  type ReviewState,
  type ReviewSummary,
  type WritePreview,
} from "./api";
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
type Decision = "Pending" | "Changes requested" | "Rejected" | "Approved";
type ReviewCase = ReviewSummary;

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

function DashboardPage({ cases, onNavigate, onOpenCase, onNewRequest }: { cases: ReviewCase[]; onNavigate: (page: Page) => void; onOpenCase: (review: ReviewCase) => void; onNewRequest: () => void }) {
  const primaryCase = cases[0] ?? reviewCases[0];
  const actionCases = cases.filter((review) => review.status === "Ready for review" || review.status === "Needs evidence");
  return <div className="dashboard-page">
    <DitherGradient from="blue" to="transparent" direction="up" cell={4} opacity={0.16} className="dashboard-gradient" />
    <div className="dashboard-content-layer">
    <PageIntro
      eyebrow="Reviewer workspace / Tuesday, July 14"
      title="Good afternoon, Alex."
      description="Two reviews need a human decision. Everything else is moving or safely paused."
      actions={<><Button variant="secondary" icon={<Upload size={15} />} onClick={onNewRequest}>New request</Button><DitherButton color="orange" variant="solid" bloom="low" className="dashboard-dither-button" onClick={() => onOpenCase(primaryCase)}><ClipboardCheck size={15} /> Review {primaryCase.product}</DitherButton></>}
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
          <div><p className="eyebrow">{primaryCase.id}</p><h2>{primaryCase.product} · {primaryCase.stage}</h2><p>The workflow remains at its current deterministic or human checkpoint.</p></div>
          <StatusBadge>{primaryCase.status}</StatusBadge>
        </div>
        <ol className="workflow-rail">
          {(primaryCase.stage === "Match confirmation" ? workflowSteps.map((step, index) => ({ ...step, state: index === 0 ? "complete" : index === 1 ? "current" : "upcoming" })) : workflowSteps).map((step) => <li key={step.short} className={`workflow-${step.state}`}>
            <span className="workflow-index">[{step.short}]</span>
            <span><strong>{step.label}</strong><small>{step.detail}</small></span>
          </li>)}
        </ol>
        <div className="panel-footer"><span><Sparkles size={14} />Specialists can draft and compare. They cannot approve.</span><Button variant="primary" onClick={() => onOpenCase(primaryCase)}>Open review <ArrowRight size={14} /></Button></div>
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

function QueuePage({ cases, onOpenCase, onNewRequest, query, onQueryChange, mode }: { cases: ReviewCase[]; onOpenCase: (review: ReviewCase) => void; onNewRequest: () => void; query: string; onQueryChange: (value: string) => void; mode: QueueMode }) {
  const [filter, setFilter] = useState<"Open" | "All" | QueueStatus>("Open");
  const modeCases = mode === "inbox" ? cases.filter((review) => review.status !== "Completed") : mode === "my-work" ? cases.filter((review) => review.owner === "Alex Reviewer") : cases;
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

function ReviewOverview({ state, onOpenEvidence, matchConfirmed, onConfirmMatch }: { state: ReviewState | null; onOpenEvidence: () => void; matchConfirmed: boolean; onConfirmMatch: () => void }) {
  const intake = state?.case_input;
  const candidate = state?.software_candidates[0];
  const policy = state?.policy_result;
  const routeLabel = policy?.risk_route === "medium" ? "Medium risk" : policy?.risk_route === "low" || policy?.risk_route === "approved" ? "Low risk" : policy ? "Safe escalation" : "Route pending";
  const matchMethod = candidate?.match_method === "vendor_product" ? "Vendor + product" : candidate?.match_method ? `${candidate.match_method[0].toUpperCase()}${candidate.match_method.slice(1)} candidate` : "No candidate";
  const source = candidate?.source_row_ref;
  const security = state?.specialist_results.security as undefined | { summary?: string; required_evidence?: string[] };
  const accessibility = state?.specialist_results.accessibility as undefined | { summary?: string; vpat_required?: boolean };
  return <div className="review-sections">
    <section className="review-section two-column-section">
      <article className="content-card">
        <div className="card-heading"><div><p className="eyebrow">01 / Intake</p><h2>Request context</h2></div><StatusBadge>Verified</StatusBadge></div>
        <dl className="detail-grid">
          <div><dt>Product</dt><dd>{intake?.product_name ?? "LabArchives"}</dd></div><div><dt>Vendor</dt><dd>{intake?.vendor_name ?? "LabArchives, LLC"}</dd></div>
          <div><dt>Requester</dt><dd>{intake?.requester.department ?? intake?.requester.name ?? "College of Science"}</dd></div><div><dt>Platform</dt><dd>{intake?.platform.join(", ") ?? "Web application"}</dd></div>
          <div><dt>Data classification</dt><dd>{intake?.data_classification ?? "Internal · sanitized demo"}</dd></div><div><dt>Intended users</dt><dd>{intake?.expected_users ?? "Faculty and students"}</dd></div>
        </dl>
        <div className="narrative-block"><span>Use case</span><p>{intake?.use_case ?? "Manage electronic research notebooks for classroom and department research workflows."}</p></div>
      </article>
      <article className="content-card">
        <div className="card-heading"><div><p className="eyebrow">02 / Approved software</p><h2>Candidate match</h2></div><StatusBadge>{matchConfirmed ? "Verified" : "Review needed"}</StatusBadge></div>
        <div className="match-record"><Database size={19} /><span><strong>{candidate?.canonical_name ?? "No approved-software candidate"}</strong><small>{source ? `${source.filename ?? source.source_id}${source.row ? ` · Row ${source.row}` : ""}` : "Structured lookup completed"}</small></span><b>{candidate ? `${Math.round(candidate.score * 100)}%` : "—"}</b></div>
        <dl className="compact-details"><div><dt>Method</dt><dd>{matchMethod}</dd></div><div><dt>Why review?</dt><dd>{candidate?.requires_confirmation ? "Fuzzy or semantic candidates require a person" : "No non-exact confirmation required"}</dd></div></dl>
        <div className="match-confirm-row"><div className="boundary-note"><UserCheck size={16} /><span>{matchConfirmed ? "Alex Reviewer confirmed this candidate for the current request." : "A reviewer—not a model—must confirm this candidate."}</span></div><Button variant={matchConfirmed ? "secondary" : "primary"} disabled={matchConfirmed} onClick={onConfirmMatch} icon={matchConfirmed ? <Check size={14} /> : <UserCheck size={14} />}>{matchConfirmed ? "Candidate confirmed" : "Confirm candidate"}</Button></div>
      </article>
    </section>

    <section className="content-card policy-card">
      <div className="card-heading"><div><p className="eyebrow">03 / Deterministic policy</p><h2>{routeLabel}</h2></div><StatusBadge>{policy ? routeLabel : "Paused"}</StatusBadge></div>
      <div className="policy-layout">
        <div className="policy-result"><span className="policy-icon"><ShieldCheck size={22} /></span><div><strong>{policy ? "Reviewer packet route calculated" : "Waiting for match confirmation"}</strong><p>{policy ? `The route came from versioned rules (${policy.policy_version}). Specialist output cannot change it.` : "Policy and specialist analysis remain paused until a reviewer confirms the fuzzy candidate."}</p></div></div>
        <ul className="citation-list">
          {policy?.citations.length ? policy.citations.map((citation, index) => <li key={`${citation.source.source_id}-${index}`}><Link2 size={14} /><span><strong>{citation.source.source_id}</strong>{citation.claim}{citation.source.row ? ` · Row ${citation.source.row}` : ""}</span></li>) : <li><LockKeyhole size={14} /><span><strong>HUMAN CHECKPOINT</strong>No policy result is shown before confirmation.</span></li>}
        </ul>
      </div>
    </section>

    <section>
      <div className="section-heading"><div><p className="eyebrow">04 / Parallel analysis</p><h2>Specialist findings</h2></div><span className="parallel-label">SECURITY ─┬─ ACCESSIBILITY</span></div>
      <div className="specialist-grid">
        <SpecialistCard icon={<ShieldCheck size={18} />} title="Security" status={security ? "Completed" : "Paused"} summary={security?.summary ?? "Security analysis starts only after deterministic routing."} points={security?.required_evidence?.length ? security.required_evidence.map((item) => `Required: ${item}`) : ["No model approval authority", "Policy route remains deterministic"]} />
        <SpecialistCard icon={<BookOpenCheck size={18} />} title="Accessibility" status={accessibility ? "Completed" : "Paused"} summary={accessibility?.summary ?? "Accessibility analysis starts only after deterministic routing."} points={accessibility?.vpat_required ? ["VPAT / ACR required", "Version alignment remains a reviewer check"] : ["No cross-case evidence", "Human review remains required"]} />
      </div>
    </section>

    <section className="content-card">
      <div className="card-heading"><div><p className="eyebrow">05 / Evidence & citations</p><h2>{policy ? `${policy.required_evidence.length} required evidence item${policy.required_evidence.length === 1 ? "" : "s"}` : "Analysis paused"}</h2></div><StatusBadge>{policy ? "Review needed" : "Paused"}</StatusBadge></div>
      <div className="gap-row"><span className="gap-icon">!</span><span><strong>{policy ? (policy.required_evidence.join(", ") || "No additional evidence required") : "Confirm the software candidate before evidence analysis."}</strong><small>{policy ? "Requirements come from the deterministic policy result." : "No specialist or policy result has been fabricated."}</small></span><Button variant="secondary" onClick={onOpenEvidence}>Review sources <ExternalLink size={14} /></Button></div>
      <div className="evidence-summary-row"><span><FileCheck2 size={16} />{policy?.citations.length ?? 0} policy citations</span><span><CheckCircle2 size={16} />{state?.draft_packet ? "Packet composed" : "Packet not composed"}</span><span><FolderLock size={16} />{state ? "Connected scoped state" : "Offline demo only"}</span></div>
    </section>
  </div>;
}

function PacketEditor({ draft, onDraftChange, onSave }: { draft: string; onDraftChange: (value: string) => void; onSave: () => void }) {
  return <section className="packet-layout">
    <div className="content-card packet-editor">
      <div className="card-heading"><div><p className="eyebrow">Current packet / Draft</p><h2>Reviewer recommendation</h2><p>Edit the draft before making a decision. Policy results and citations remain locked.</p></div><Button variant="primary" onClick={onSave}>Save draft</Button></div>
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

function WritebackPreview({ decision, written, preview, onWrite }: { decision: Decision; written: boolean; preview: WritePreview | null; onWrite: () => void }) {
  const unlocked = decision === "Approved";
  const before = preview?.before ?? { state: "Under review", u_review_outcome: "—", work_notes: "Review in progress", attachment: "—" };
  const after = preview?.after ?? { state: "Ready for committee", u_review_outcome: "Medium-risk packet drafted", work_notes: "Human-reviewed decision", attachment: "Pending confirmation" };
  const rows = (values: Record<string, unknown>, changed: boolean) => Object.entries(values).slice(0, 5).map(([field, value]) => <div key={field}><dt>{field.replace(/^u_/, "").replace(/_/g, " ")}</dt><dd>{changed ? <span className="diff-value">{String(value || "—")}</span> : String(value || "—")}</dd></div>);
  return <section className="writeback-layout">
    <div className="simulation-banner"><CircleDashed size={18} /><span><strong>Simulated ServiceNow</strong>This preview never connects to a live campus system.</span></div>
    <div className="before-after-grid">
      <article className="content-card"><p className="eyebrow">Before</p><h2>Mock request · {preview?.record_id ?? "Preview pending"}</h2><dl className="change-list">{rows(before, false)}</dl></article>
      <article className="content-card after-card"><p className="eyebrow">After</p><h2>Proposed configured changes</h2><dl className="change-list">{rows(after, true)}</dl></article>
    </div>
    <div className={`writeback-confirm ${unlocked ? "writeback-unlocked" : ""}`}>
      <span className="writeback-lock">{written ? <CheckCircle2 size={20} /> : unlocked ? <UserCheck size={20} /> : <LockKeyhole size={20} />}</span>
      <span><strong>{written ? "Mock record updated" : unlocked ? "Second confirmation required" : "Write-back is locked"}</strong><small>{written ? "Decision v1 and packet hash were added to the local audit trail." : unlocked ? "Confirm the preview to write once to the local mock connector." : "Record an approved human decision first. Drafts and model output cannot unlock this action."}</small></span>
      <Button variant="primary" disabled={!unlocked || written || !preview} onClick={onWrite}>{written ? "Simulation complete" : preview ? "Approve & simulate write-back" : "Preparing preview…"}</Button>
    </div>
  </section>;
}

function DecisionPanel({ decision, approvalAllowed, approvalBlockReason, onDecision, onTabChange }: { decision: Decision; approvalAllowed: boolean; approvalBlockReason: string | null; onDecision: (decision: Decision) => void; onTabChange: (tab: "overview" | "packet" | "writeback") => void }) {
  return <aside className="decision-panel">
    <div className="decision-panel-heading"><span className="decision-icon"><UserCheck size={19} /></span><div><p className="eyebrow">Human checkpoint</p><h2>Your decision</h2></div></div>
    <p className="decision-copy">Review the draft, cited findings, and open accessibility item. Your action is recorded with this packet version.</p>
    <div className="decision-state"><span>Current decision</span><StatusBadge>{decision}</StatusBadge></div>
    {!approvalAllowed && approvalBlockReason && <div className="decision-prerequisite"><LockKeyhole size={15} /><span><strong>Approval is locked.</strong> {approvalBlockReason}</span></div>}
    {decision === "Pending" ? <div className="decision-buttons">
      <Button variant="secondary" onClick={() => onDecision("Changes requested")}>Request changes</Button>
      <Button variant="danger" onClick={() => onDecision("Rejected")}>Reject</Button>
      <Button variant="primary" disabled={!approvalAllowed} onClick={() => onDecision("Approved")} icon={<Check size={15} />}>Approve draft</Button>
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

function ReviewPage({ review, state, decision, matchConfirmed, onConfirmMatch, packetDraft, onPacketDraftChange, onSavePacket, onDecision, written, onWrite, onOpenEvidence }: { review: ReviewCase; state: ReviewState | null; decision: Decision; matchConfirmed: boolean; onConfirmMatch: () => void; packetDraft: string; onPacketDraftChange: (value: string) => void; onSavePacket: () => void; onDecision: (decision: Decision) => void; written: boolean; onWrite: () => void; onOpenEvidence: () => void }) {
  const [tab, setTab] = useState<"overview" | "packet" | "writeback">("overview");
  const approvalAllowed = matchConfirmed && Boolean(state?.draft_packet) && state?.status !== "escalated";
  const approvalBlockReason = !matchConfirmed
    ? "Confirm the fuzzy or semantic candidate first."
    : state?.status === "escalated"
      ? "This case is safely escalated and cannot be fast-pathed."
      : !state?.draft_packet
        ? "A generated packet is required before approval."
        : null;
  const currentStepIndex = ({
    intake: 0,
    lookup: 1,
    awaiting_match_confirmation: 1,
    policy: 2,
    analysis: 3,
    packet: 4,
    awaiting_review: 5,
    writeback: 6,
    closed: 7,
    escalated: 2,
  } as Record<string, number>)[state?.status ?? ""] ?? 5;
  const reviewSteps = workflowSteps.map((step, index) => ({
    ...step,
    state: index < currentStepIndex ? "complete" : index === currentStepIndex ? "current" : "upcoming",
  }));
  if (!state) {
    return <section className="content-card"><p className="eyebrow">Sanitized offline fallback</p><h1>{review.product}</h1><p>The detailed review, evidence claims, packet, decision, preview, and audit actions require the local backend. Start it with the documented command; no consequential action is recorded while offline.</p></section>;
  }
  return <>
    <div className="review-page-header">
      <div className="review-title-line"><span className="record-glyph record-glyph-large">{review.product.slice(0, 2).toUpperCase()}</span><div><p className="eyebrow">{review.id} / Active review</p><h1>{review.product}</h1><p>{review.vendor} · Requested by {review.requester}</p></div></div>
      <div className="review-header-status"><StatusBadge>{decision === "Pending" ? review.status : decision}</StatusBadge><Avatar name={review.owner} /></div>
    </div>

    <ol className="review-stepper" aria-label="Review progress">
      {reviewSteps.map((step) => <li key={step.short} className={`workflow-${step.state}`}><span>{step.state === "complete" ? <Check size={12} /> : step.short}</span><strong>{step.label}</strong></li>)}
    </ol>

    <div className="review-tabs" role="tablist" aria-label="Review sections">
      {(["overview", "packet", "writeback"] as const).map((item) => <button key={item} role="tab" aria-selected={tab === item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{item === "overview" ? "Review overview" : item === "packet" ? "Packet editor" : "Write-back preview"}{item === "packet" && <span>{state?.draft_packet ? `v${state.draft_packet.packet_version}` : "pending"}</span>}{item === "writeback" && decision !== "Approved" && <LockKeyhole size={13} />}</button>)}
    </div>

    <div className="review-workspace">
      <div className="review-main">
        {tab === "overview" && <ReviewOverview state={state} onOpenEvidence={onOpenEvidence} matchConfirmed={matchConfirmed} onConfirmMatch={onConfirmMatch} />}
        {tab === "packet" && (state && !state.draft_packet ? <section className="content-card"><p className="eyebrow">Human checkpoint</p><h2>Packet generation is paused</h2><p>Confirm the fuzzy or semantic software candidate before deterministic policy, specialist analysis, and packet composition continue.</p></section> : <PacketEditor draft={packetDraft} onDraftChange={onPacketDraftChange} onSave={onSavePacket} />)}
        {tab === "writeback" && <WritebackPreview decision={decision} written={written} preview={state?.write_preview ?? null} onWrite={onWrite} />}
      </div>
      <DecisionPanel decision={decision} approvalAllowed={approvalAllowed} approvalBlockReason={approvalBlockReason} onDecision={onDecision} onTabChange={setTab} />
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

function AuditPage({ caseId, decision, written, matchConfirmed }: { caseId: string; decision: Decision; written: boolean; matchConfirmed: boolean }) {
  const events = useMemo(() => {
    const dynamic = [];
    if (written) dynamic.push({ time: "Now", actor: "Mock connector", action: "Completed simulated ServiceNow write-back", detail: "Decision v1 · Packet attached once" });
    if (decision !== "Pending") dynamic.push({ time: written ? "1 min ago" : "Now", actor: "Alex Reviewer", action: `Recorded decision: ${decision}`, detail: "Packet v3 · Human checkpoint" });
    if (matchConfirmed) dynamic.push({ time: decision !== "Pending" ? "2 min ago" : "Now", actor: "Alex Reviewer", action: "Confirmed vendor + product candidate", detail: `${caseId} · reviewer-attributed confirmation` });
    const demoEvents = caseId === "TR-260714-014" ? initialAuditEvents : [];
    return [...dynamic, ...demoEvents];
  }, [caseId, decision, written, matchConfirmed]);
  return <>
    <PageIntro eyebrow="Sanitized local event visualization" title="Audit" description="Connected reviewer actions appear here during this browser session; durable production audit storage is deferred." />
    <section className="panel audit-panel">
      <div className="audit-summary"><div><span className="audit-symbol">LOG</span><span><strong>{caseId}</strong><small>Sanitized demo events plus current-session actions · newest first</small></span></div><div><StatusBadge>Verified</StatusBadge><span className="hash-label">CHAIN / LOCAL-DEMO-014</span></div></div>
      <div className="audit-timeline">{events.map((event, index) => <article key={`${event.time}-${event.action}`}><div className="timeline-rail"><span>{index === 0 ? <Activity size={13} /> : String(events.length - index).padStart(2, "0")}</span></div><time>{event.time}</time><div><strong>{event.actor}</strong><p>{event.action}</p><small>{event.detail}</small></div></article>)}</div>
    </section>
  </>;
}

function NewRequestDialog({ onClose, onSubmit }: { onClose: () => void; onSubmit: (input: CaseIntakeInput) => void }) {
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const optional = (name: string) => String(data.get(name) || "").trim() || undefined;
    onSubmit({
      product_name: String(data.get("product_name") || "").trim(),
      vendor_name: String(data.get("vendor_name") || "").trim(),
      requester: {
        name: String(data.get("requester_name") || "").trim(),
        email: String(data.get("requester_email") || "").trim(),
        department: optional("requester_department"),
      },
      use_case: String(data.get("use_case") || "").trim(),
      expected_users: Number(data.get("expected_users")),
      platform: [String(data.get("platform") || "web")],
      data_classification: String(data.get("data_classification")) as CaseIntakeInput["data_classification"],
      estimated_cost_usd: Number(data.get("estimated_cost_usd")),
      integrations: String(data.get("integrations") || "").split(",").map((item) => item.trim()).filter(Boolean),
      uses_sso: data.get("uses_sso") === "true",
      uses_ai: data.get("uses_ai") === "true",
      accessibility_context: optional("accessibility_context"),
      official_domain: optional("official_domain"),
      classroom_or_public_use: data.get("classroom_or_public_use") === "true",
    });
  };
  return <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="dialog" role="dialog" aria-modal="true" aria-labelledby="new-request-title">
      <div className="dialog-heading"><div><p className="eyebrow">Guided intake / Sanitized local case</p><h2 id="new-request-title">Start a technology review</h2><p>Use sanitized information only. Required details are validated before deterministic analysis.</p></div><button className="icon-button" onClick={onClose} aria-label="Close dialog"><X size={18} /></button></div>
      <form onSubmit={submit}>
        <div className="form-grid">
          <label><span>Product name</span><input name="product_name" required placeholder="e.g. LabArchives" autoFocus /></label>
          <label><span>Vendor</span><input name="vendor_name" required placeholder="Legal vendor name" /></label>
          <label><span>Requester name</span><input name="requester_name" required placeholder="Sample Requester" /></label>
          <label><span>Requester email</span><input name="requester_email" required type="email" placeholder="requester@example.edu" /></label>
          <label><span>Department</span><input name="requester_department" placeholder="Department" /></label>
          <label><span>Platform</span><select name="platform" defaultValue="web"><option value="web">Web</option><option value="windows">Windows</option><option value="macos">macOS</option><option value="mobile">Mobile</option></select></label>
          <label className="full-field"><span>Intended use</span><textarea name="use_case" required placeholder="What will the product be used for?" /></label>
          <label><span>Expected users</span><input name="expected_users" required type="number" min="0" defaultValue="1" /></label>
          <label><span>Estimated cost (USD)</span><input name="estimated_cost_usd" required type="number" min="0" step="0.01" defaultValue="0" /></label>
          <label><span>Data classification</span><select name="data_classification" required defaultValue=""><option value="" disabled>Select classification</option><option value="public">Public</option><option value="internal">Internal</option><option value="confidential">Confidential</option><option value="level1">Level 1</option><option value="level2">Level 2</option><option value="unknown">Unknown — escalate</option></select></label>
          <label><span>Official vendor domain</span><input name="official_domain" placeholder="vendor.example" /></label>
          <label className="full-field"><span>Integrations (comma separated)</span><input name="integrations" placeholder="Canvas, Microsoft 365" /></label>
          <label className="full-field"><span>Accessibility context</span><textarea name="accessibility_context" placeholder="Classroom, public, assistive technology, or VPAT context" /></label>
          <label><span>Uses SSO?</span><select name="uses_sso" defaultValue="false"><option value="false">No</option><option value="true">Yes</option></select></label>
          <label><span>Uses AI?</span><select name="uses_ai" defaultValue="false"><option value="false">No</option><option value="true">Yes</option></select></label>
          <label><span>Classroom or public use?</span><select name="classroom_or_public_use" defaultValue="false"><option value="false">No</option><option value="true">Yes</option></select></label>
        </div>
        <div className="form-notice"><ShieldCheck size={17} /><span>Submitting creates the case and runs bounded local analysis. It cannot approve software or write to an external system.</span></div>
        <div className="dialog-actions"><Button variant="ghost" type="button" onClick={onClose}>Cancel</Button><Button variant="primary" type="submit">Create and analyze <ArrowRight size={14} /></Button></div>
      </form>
    </section>
  </div>;
}

export default function App() {
  const [page, setPage] = useState<Page>("dashboard");
  const [queueMode, setQueueMode] = useState<QueueMode>("inbox");
  const [theme, setTheme] = useState<Theme>(() => localStorage.getItem("review-theme") === "dark" ? "dark" : "light");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [cases, setCases] = useState<ReviewCase[]>(reviewCases);
  const [caseStates, setCaseStates] = useState<Record<string, ReviewState>>({});
  const [selectedReview, setSelectedReview] = useState(reviewCases[0]);
  const [activeState, setActiveState] = useState<ReviewState | null>(null);
  const [backendConnected, setBackendConnected] = useState(false);
  const [matchConfirmed, setMatchConfirmed] = useState(false);
  const [packetDraft, setPacketDraft] = useState(() => localStorage.getItem("review-packet-draft") ?? defaultPacketDraft);
  const [packetDirty, setPacketDirty] = useState(false);
  const [decision, setDecision] = useState<Decision>("Pending");
  const [written, setWritten] = useState(false);
  const [globalQuery, setGlobalQuery] = useState("");
  const [newRequestOpen, setNewRequestOpen] = useState(false);
  const [toast, setToast] = useState("");

  const syncActionResponse = (response: CaseActionResponse, syncDraft = false) => {
    const summary = queueItemToSummary(response.queue_item);
    setCases((current) => [summary, ...current.filter((item) => item.id !== summary.id)]);
    setCaseStates((current) => ({ ...current, [summary.id]: response.state }));
    setSelectedReview(summary);
    setActiveState(response.state);
    setPacketDirty(false);
    const candidate = response.state.software_candidates[0];
    setMatchConfirmed(Boolean(response.state.confirmed_match_id) || !candidate?.requires_confirmation);
    const action = response.state.human_decision?.action;
    setDecision(action === "approve" ? "Approved" : action === "reject" ? "Rejected" : action === "request_info" ? "Changes requested" : "Pending");
    setWritten(Boolean(response.state.write_result?.committed));
    if (syncDraft && response.state.draft_packet) setPacketDraft(packetToDraft(response.state.draft_packet));
  };

  useEffect(() => {
    let current = true;
    reviewApi.listQueue().then((items) => {
      if (!current || items.length === 0) return;
      const summaries = items.map(queueItemToSummary);
      const states = Object.fromEntries(items.map((item) => [item.case_id, item.state]));
      const active = items.find((item) => item.case_id === "TR-260714-014") ?? items[0];
      setCases(summaries);
      setCaseStates(states);
      setSelectedReview(queueItemToSummary(active));
      setActiveState(active.state);
      const candidate = active.state.software_candidates[0];
      setMatchConfirmed(Boolean(active.state.confirmed_match_id) || !candidate?.requires_confirmation);
      if (active.state.draft_packet) setPacketDraft(packetToDraft(active.state.draft_packet));
      setBackendConnected(true);
    }).catch(() => {
      if (current) setBackendConnected(false);
    });
    return () => { current = false; };
  }, []);

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
  const apiErrorMessage = (error: unknown) => error instanceof ReviewApiError ? error.message : "The local backend request failed.";
  const openCase = (review: ReviewCase) => {
    const state = caseStates[review.id];
    if (!state) {
      setToast(`${review.product} is available as a sanitized local summary while the backend is offline.`);
      setSelectedReview(review);
      setActiveState(null);
      setMatchConfirmed(false);
      setDecision("Pending");
      setWritten(false);
      setPacketDraft(defaultPacketDraft);
      setPacketDirty(false);
      navigate("review");
      return;
    }
    setSelectedReview(review);
    setActiveState(state);
    setPacketDirty(false);
    const candidate = state.software_candidates[0];
    setMatchConfirmed(Boolean(state.confirmed_match_id) || !candidate?.requires_confirmation);
    const action = state.human_decision?.action;
    setDecision(action === "approve" ? "Approved" : action === "reject" ? "Rejected" : action === "request_info" ? "Changes requested" : "Pending");
    setWritten(Boolean(state.write_result?.committed));
    if (state.draft_packet) setPacketDraft(packetToDraft(state.draft_packet));
    navigate("review");
  };
  const updatePacketDraft = (value: string) => {
    setPacketDraft(value);
    setPacketDirty(true);
    if (decision !== "Pending" || written) {
      setDecision("Pending");
      setWritten(false);
      setToast("Packet has unsaved edits. Write-back is disabled until a replacement decision is submitted.");
    }
  };
  const confirmMatch = async () => {
    const candidate = activeState?.software_candidates.find((item) => item.requires_confirmation);
    if (!backendConnected || !activeState || !candidate) {
      setToast("Connect the local backend to record an attributable match confirmation.");
      return;
    }
    try {
      const response = await reviewApi.analyzeCase(activeState.case_id, candidate.record_id);
      syncActionResponse(response, true);
      setToast(`${candidate.canonical_name ?? "Software"} confirmed by Alex Reviewer; deterministic analysis completed.`);
    } catch (error) {
      setToast(apiErrorMessage(error));
    }
  };
  const savePacket = () => { localStorage.setItem("review-packet-draft", packetDraft); setToast("Draft saved in this browser only. Submit a replacement decision to persist it and invalidate the prior preview."); };
  const recordDecision = async (nextDecision: Decision) => {
    if (nextDecision === "Pending") {
      setDecision("Pending");
      setWritten(false);
      setToast("Preparing a replacement decision locally; the prior server decision changes only when the replacement is submitted.");
      return;
    }
    if (nextDecision === "Approved" && !matchConfirmed) {
      setToast("Confirm the fuzzy or semantic approved-software candidate before approving the draft.");
      return;
    }
    if (nextDecision === "Approved" && (!activeState?.draft_packet || activeState.status === "escalated")) {
      setToast("Approval requires a generated packet and a non-escalated deterministic route.");
      return;
    }
    if (!backendConnected || !activeState) {
      setToast("Connect the local backend to persist a reviewer decision and audit event.");
      return;
    }
    const action = nextDecision === "Approved" ? "approve" : nextDecision === "Rejected" ? "reject" : "request_info";
    const originalDraft = packetToDraft(activeState.draft_packet);
    const editableSection = packetEditSection(activeState.draft_packet);
    const hasPacketEdits = packetDirty && Boolean(editableSection) && packetDraft.trim() !== originalDraft.trim();
    const edits = hasPacketEdits && editableSection
      ? [{ section_key: editableSection.key, body: packetDraft }]
      : undefined;
    try {
      const reviewed = await reviewApi.recordDecision(activeState.case_id, {
        decision_version: decisionVersion(activeState, hasPacketEdits),
        reviewer_id: "alex.reviewer@example.edu",
        action,
        decided_at: new Date().toISOString(),
        edits,
      });
      syncActionResponse(reviewed);
      if (action === "approve") {
        const previewed = await reviewApi.previewWriteback(activeState.case_id);
        syncActionResponse(previewed);
      }
      setDecision(nextDecision);
      setWritten(false);
      setToast(`${nextDecision} recorded through the local review API.`);
    } catch (error) {
      setToast(apiErrorMessage(error));
    }
  };
  const simulateWrite = async () => {
    if (packetDirty) {
      setToast("Submit a replacement decision and review its new preview before write-back.");
      return;
    }
    const preview = activeState?.write_preview;
    if (!backendConnected || !activeState || !preview) {
      setToast("A successful simulated before/after preview is required first.");
      return;
    }
    try {
      const committed = await reviewApi.commitWriteback(activeState.case_id, preview.expected_record_version);
      syncActionResponse(committed);
      setWritten(true);
      setToast(committed.state.write_result?.duplicate_suppressed ? "Duplicate simulated write suppressed." : "Simulated ServiceNow write-back completed and packet attached once.");
    } catch (error) {
      setToast(apiErrorMessage(error));
    }
  };
  const submitRequest = async (input: CaseIntakeInput) => {
    try {
      const created = await reviewApi.createCase(input);
      const analyzed = await reviewApi.analyzeCase(created.case_id);
      syncActionResponse(analyzed, true);
      setBackendConnected(true);
      setNewRequestOpen(false);
      setToast(`Created ${created.case_id}; analysis stopped at the correct human checkpoint.`);
      navigate("queue");
    } catch (error) {
      setToast(apiErrorMessage(error));
    }
  };

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
      <div className="workspace-chip"><span>CSUB</span><div><strong>Solutions Consulting</strong><small>{backendConnected ? "Local backend connected" : "Sanitized offline fallback"}</small></div></div>
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
        {page === "dashboard" && <DashboardPage cases={cases} onNavigate={navigate} onOpenCase={openCase} onNewRequest={() => setNewRequestOpen(true)} />}
        {page === "queue" && <QueuePage cases={cases} onOpenCase={openCase} onNewRequest={() => setNewRequestOpen(true)} query={globalQuery} onQueryChange={setGlobalQuery} mode={queueMode} />}
        {page === "review" && <ReviewPage review={selectedReview} state={activeState} decision={decision} matchConfirmed={matchConfirmed} onConfirmMatch={confirmMatch} packetDraft={packetDraft} onPacketDraftChange={updatePacketDraft} onSavePacket={savePacket} onDecision={recordDecision} written={written} onWrite={simulateWrite} onOpenEvidence={() => navigate("evidence")} />}
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
        {page === "audit" && <AuditPage caseId={selectedReview.id} decision={decision} written={written} matchConfirmed={matchConfirmed} />}
      </main>
    </div>

    {newRequestOpen && <NewRequestDialog onClose={() => setNewRequestOpen(false)} onSubmit={submitRequest} />}
    <div className={`toast ${toast ? "toast-visible" : ""}`} role="status" aria-live="polite"><CheckCircle2 size={16} />{toast}</div>
  </div>;
}
