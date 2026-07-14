import { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  Bell,
  BookOpen,
  Building2,
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CircleDot,
  CircleDotDashed,
  ClipboardCheck,
  Clock3,
  ContactRound,
  Download,
  ExternalLink,
  FileCheck2,
  FileText,
  Filter,
  FolderOpen,
  GitBranch,
  Gauge,
  History,
  Inbox,
  LayoutDashboard,
  LifeBuoy,
  Link2,
  ListFilter,
  Mail,
  MessageCircle,
  MoreHorizontal,
  PanelLeftClose,
  Paperclip,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  SquareArrowOutUpRight,
  Tag,
  Upload,
  UserPlus,
  UserRound,
  Users,
  Workflow,
  X,
} from "lucide-react";
import { RecordSurface } from "./components/twenty/RecordSurface";
import { WorkflowCanvas, type WorkflowCanvasNode } from "./components/twenty/workflow/WorkflowCanvas";
import "./styles.css";

type ViewKey = "overview" | "runs" | "vendors" | "contacts" | "requests" | "tasks" | "notes" | "evidence" | "audit" | "dashboard" | "workflows" | "workflow-runs" | "workflow-versions" | "chat" | "settings" | "documentation";
type QueueMode = "all" | "inbox" | "my-work";
type RunStatus = "Complete" | "In progress" | "Escalated";
type RiskRoute = "Low risk" | "Medium risk" | "Safe escalation";
type VendorStatus = "Active" | "Needs review" | "Archived";

type ReviewRun = {
  id: string;
  request: string;
  vendorId: string;
  vendor: string;
  requester: string;
  status: RunStatus;
  route: RiskRoute;
  result: string;
  owner: string;
  progress: number;
  updated: string;
  evidence: number;
  started: string;
};

type Vendor = {
  id: string;
  name: string;
  domain: string;
  owner: string;
  ownerRole: string;
  contacts: number;
  activeRuns: number;
  lastReview: string;
  status: VendorStatus;
  risk: RiskRoute;
  note: string;
};

type Contact = {
  id: string;
  name: string;
  role: string;
  type: "Internal" | "Vendor";
  vendor: string;
  vendorId?: string;
  email: string;
  linkedStaff: string;
  status: "Primary" | "Supporting" | "Inactive";
};

type EvidenceDocument = {
  id: string;
  name: string;
  kind: string;
  vendor: string;
  scope: string;
  status: "Verified" | "Needs review" | "Expired";
  updated: string;
  pages: number;
  reference: string;
  excerpt: string;
};

const reviewRuns: ReviewRun[] = [
  { id: "TR-260714-018", request: "Canvas AI Assist", vendorId: "instructure", vendor: "Instructure", requester: "College of Education", status: "Complete", route: "Low risk", result: "Approved software match", owner: "Jordan Lee", progress: 100, updated: "12 min ago", evidence: 8, started: "Jul 14, 09:18" },
  { id: "TR-260714-014", request: "LabArchives", vendorId: "labarchives", vendor: "LabArchives, LLC", requester: "College of Science", status: "In progress", route: "Medium risk", result: "Packet draft ready", owner: "Alex Reviewer", progress: 82, updated: "41 min ago", evidence: 14, started: "Jul 14, 08:42" },
  { id: "TR-260714-011", request: "Notion AI", vendorId: "notion", vendor: "Notion Labs, Inc.", requester: "Student Success", status: "Escalated", route: "Safe escalation", result: "Missing vendor evidence", owner: "Maya Patel", progress: 58, updated: "1 hr ago", evidence: 3, started: "Jul 14, 08:04" },
  { id: "TR-260714-006", request: "Zoom AI Companion", vendorId: "zoom", vendor: "Zoom Video Communications", requester: "Academic Senate", status: "In progress", route: "Medium risk", result: "Accessibility analysis", owner: "Jordan Lee", progress: 64, updated: "2 hrs ago", evidence: 11, started: "Jul 14, 07:25" },
  { id: "TR-260713-041", request: "Turnitin Draft Coach", vendorId: "turnitin", vendor: "Turnitin, LLC", requester: "Graduate Studies", status: "Complete", route: "Low risk", result: "Reviewer approved", owner: "Alex Reviewer", progress: 100, updated: "Yesterday", evidence: 12, started: "Jul 13, 16:10" },
  { id: "TR-260713-034", request: "Qualtrics XM", vendorId: "qualtrics", vendor: "Qualtrics", requester: "Institutional Research", status: "Complete", route: "Medium risk", result: "Mock write-back complete", owner: "Maya Patel", progress: 100, updated: "Yesterday", evidence: 17, started: "Jul 13, 14:24" },
];

const vendors: Vendor[] = [
  { id: "instructure", name: "Instructure", domain: "instructure.com", owner: "Jordan Lee", ownerRole: "Academic Technology", contacts: 3, activeRuns: 1, lastReview: "Today, 09:30", status: "Active", risk: "Low risk", note: "Approved-software match confirmed for Canvas AI Assist." },
  { id: "labarchives", name: "LabArchives, LLC", domain: "labarchives.com", owner: "Maya Patel", ownerRole: "Research Technology", contacts: 4, activeRuns: 1, lastReview: "Today, 08:42", status: "Needs review", risk: "Medium risk", note: "Medium-risk packet is ready for reviewer edits and citations." },
  { id: "notion", name: "Notion Labs, Inc.", domain: "notion.so", owner: "Alex Reviewer", ownerRole: "Information Security", contacts: 2, activeRuns: 1, lastReview: "Today, 08:04", status: "Needs review", risk: "Safe escalation", note: "Official-domain evidence is incomplete for the requested use case." },
  { id: "zoom", name: "Zoom Video Communications", domain: "zoom.us", owner: "Jordan Lee", ownerRole: "Academic Technology", contacts: 5, activeRuns: 1, lastReview: "Today, 07:25", status: "Active", risk: "Medium risk", note: "Accessibility and AI-data handling findings are still running." },
  { id: "turnitin", name: "Turnitin, LLC", domain: "turnitin.com", owner: "Maya Patel", ownerRole: "Research Technology", contacts: 3, activeRuns: 0, lastReview: "Jul 13, 16:10", status: "Active", risk: "Low risk", note: "Last review completed with a source-linked approval." },
  { id: "qualtrics", name: "Qualtrics", domain: "qualtrics.com", owner: "Alex Reviewer", ownerRole: "Information Security", contacts: 2, activeRuns: 0, lastReview: "Jul 13, 14:24", status: "Active", risk: "Medium risk", note: "Mock ServiceNow write-back recorded against the approved decision." },
];

const contacts: Contact[] = [
  { id: "jordan", name: "Jordan Lee", role: "Academic Technology lead", type: "Internal", vendor: "Portfolio owner", email: "jordan.lee@csub.edu", linkedStaff: "6 vendor relationships", status: "Primary" },
  { id: "maya", name: "Maya Patel", role: "Research Technology lead", type: "Internal", vendor: "Portfolio owner", email: "maya.patel@csub.edu", linkedStaff: "4 vendor relationships", status: "Primary" },
  { id: "alex", name: "Alex Reviewer", role: "Information Security reviewer", type: "Internal", vendor: "Portfolio owner", email: "alex.reviewer@csub.edu", linkedStaff: "3 vendor relationships", status: "Primary" },
  { id: "instructure-c", name: "Sam Rivera", role: "Education Partnerships", type: "Vendor", vendor: "Instructure", vendorId: "instructure", email: "sam.rivera@instructure.com", linkedStaff: "Jordan Lee", status: "Primary" },
  { id: "labarchives-c", name: "Priya Nair", role: "Higher Ed Solutions", type: "Vendor", vendor: "LabArchives, LLC", vendorId: "labarchives", email: "priya.nair@labarchives.com", linkedStaff: "Maya Patel", status: "Primary" },
  { id: "notion-c", name: "Taylor Chen", role: "Public Sector Partnerships", type: "Vendor", vendor: "Notion Labs, Inc.", vendorId: "notion", email: "taylor.chen@notion.so", linkedStaff: "Alex Reviewer", status: "Supporting" },
  { id: "zoom-c", name: "Chris Morgan", role: "Education Account Executive", type: "Vendor", vendor: "Zoom Video Communications", vendorId: "zoom", email: "chris.morgan@zoom.us", linkedStaff: "Jordan Lee", status: "Primary" },
];

const documents: EvidenceDocument[] = [
  { id: "doc-1", name: "Risk Review Recommendations.xlsx", kind: "Policy workbook", vendor: "Institutional", scope: "Campus policy", status: "Verified", updated: "Jul 14, 2026", pages: 8, reference: "Sheet: Routing rules · Row 18", excerpt: "Medium-risk software with student data or external integrations requires a reviewer-edited TAAP/security packet before approval." },
  { id: "doc-2", name: "Instructure SOC 2 Type II.pdf", kind: "SOC 2 report", vendor: "Instructure", scope: "Vendor evidence", status: "Verified", updated: "Jun 02, 2026", pages: 46, reference: "Page 12 · Control CC6.1", excerpt: "The service organization maintains logical access controls for production systems and reviews access at least quarterly." },
  { id: "doc-3", name: "LabArchives VPAT 2.5.docx", kind: "VPAT / ACR", vendor: "LabArchives, LLC", scope: "Vendor evidence", status: "Needs review", updated: "May 18, 2026", pages: 12, reference: "Section 4 · WCAG 2.2", excerpt: "Accessibility conformance statements require reviewer verification against the requested product version and deployment context." },
  { id: "doc-4", name: "Notion security overview.html", kind: "Official vendor page", vendor: "Notion Labs, Inc.", scope: "Vendor research", status: "Expired", updated: "Nov 12, 2025", pages: 1, reference: "Captured official domain · notion.so", excerpt: "Captured source is outside the current evidence freshness window and cannot establish a current policy result." },
  { id: "doc-5", name: "Signed TAAP example.pdf", kind: "TAAP example", vendor: "Institutional", scope: "Approved template", status: "Verified", updated: "Apr 29, 2026", pages: 7, reference: "Page 3 · Data handling", excerpt: "Approved clauses and reviewer edits remain separate from calculated policy routing and are retained in the decision audit." },
];

const auditEvents = [
  { time: "09:42", actor: "Alex Reviewer", event: "opened the LabArchives packet", detail: "Review run TR-260714-014 · Human review", tone: "blue" },
  { time: "09:31", actor: "Policy engine", event: "calculated a medium-risk route", detail: "3 citations · Rule set v2026.07.14", tone: "yellow" },
  { time: "09:18", actor: "Jordan Lee", event: "confirmed the Canvas AI Assist match", detail: "Exact match · Approved software export row 238", tone: "green" },
  { time: "08:57", actor: "Evidence specialist", event: "flagged a product-version mismatch", detail: "Notion AI · Official-domain evidence", tone: "red" },
  { time: "08:42", actor: "Intake workflow", event: "created a new review run", detail: "LabArchives · College of Science", tone: "purple" },
];

const workflowRecords = [
  { id: "wf-review-intake", name: "Technology review intake", description: "Validate request fields, find approved-software matches, and start the review graph.", trigger: "New review request", status: "Active", runs: "24 this month", updated: "2 min ago", owner: "Review operations", steps: ["Validate intake", "Find software match", "Route by policy", "Create review run"] },
  { id: "wf-medium-packet", name: "Medium-risk packet", description: "Collect scoped evidence, run specialist checks, and prepare an editable reviewer packet.", trigger: "Medium-risk route", status: "Active", runs: "11 this month", updated: "41 min ago", owner: "Information Security", steps: ["Request evidence", "Run security review", "Run accessibility review", "Draft packet"] },
  { id: "wf-safe-escalation", name: "Safe escalation", description: "Pause incomplete or contradictory cases and surface the missing decision inputs to a human.", trigger: "Unsupported or high-risk result", status: "Active", runs: "5 this month", updated: "1 hr ago", owner: "Review operations", steps: ["Flag boundary", "Create task", "Notify reviewer", "Hold write-back"] },
  { id: "wf-evidence-refresh", name: "Evidence freshness check", description: "Find stale, mismatched, or expired vendor evidence before it is reused in a decision.", trigger: "Daily at 06:00", status: "Draft", runs: "0 this month", updated: "Yesterday", owner: "Data & policy", steps: ["Check source age", "Compare product version", "Create evidence task"] },
];

type BuilderNode = WorkflowCanvasNode;

const builderNodeTemplates: BuilderNode[] = [
  { id: "validate-intake", title: "Validate intake", detail: "Required fields and evidence metadata", kind: "action", group: "Review operations", icon: FileCheck2, tone: "blue" },
  { id: "policy-route", title: "Calculate policy route", detail: "Versioned deterministic policy rules", kind: "condition", group: "Review operations", icon: ShieldCheck, tone: "teal" },
  { id: "human-review", title: "Human review", detail: "Pause for reviewer decision", kind: "human", group: "Human input", icon: ClipboardCheck, tone: "yellow" },
  { id: "evidence-specialist", title: "Evidence specialist", detail: "Find scoped vendor evidence", kind: "action", group: "AI and evidence", icon: BookOpen, tone: "purple" },
  { id: "accessibility-check", title: "Accessibility analysis", detail: "Compare VPAT / ACR evidence", kind: "action", group: "AI and evidence", icon: CircleCheck, tone: "teal" },
  { id: "citation-check", title: "Citation checker", detail: "Reject unsupported findings", kind: "action", group: "AI and evidence", icon: BookOpen, tone: "purple" },
  { id: "route-case", title: "If / else route", detail: "Branch on the deterministic result", kind: "condition", group: "Flow", icon: GitBranch, tone: "teal" },
  { id: "pause-evidence", title: "Wait for evidence", detail: "Hold until a reviewer responds", kind: "human", group: "Flow", icon: Clock3, tone: "yellow" },
  { id: "create-task", title: "Create reviewer task", detail: "Assign a human follow-up", kind: "action", group: "Human input", icon: ClipboardCheck, tone: "yellow" },
  { id: "mock-preview", title: "Mock ServiceNow preview", detail: "Prepare a deterministic write preview", kind: "action", group: "Connector", icon: ExternalLink, tone: "red" },
];

function createBuilderNodes(workflowId: string): BuilderNode[] {
  const trigger: BuilderNode = { id: `${workflowId}-trigger`, title: workflowId === "wf-evidence-refresh" ? "Evidence refresh schedule" : "New review request", detail: workflowId === "wf-evidence-refresh" ? "Runs daily at 06:00" : "A requester submits a technology review", kind: "trigger", group: "Trigger", icon: Workflow, tone: "blue" };
  const findTemplate = (id: string) => builderNodeTemplates.find((template) => template.id === id) ?? builderNodeTemplates[0];
  const nodeIds = workflowId === "wf-safe-escalation" ? ["validate-intake", "route-case", "create-task", "human-review"] : workflowId === "wf-evidence-refresh" ? ["evidence-specialist", "citation-check", "create-task"] : ["validate-intake", "policy-route", "evidence-specialist", "human-review"];
  return [trigger, ...nodeIds.map((id, index) => ({ ...findTemplate(id), id: `${workflowId}-${id}-${index}` }))];
}

const reviewTasks = [
  { id: "TASK-104", title: "Confirm LabArchives VPAT version", assignee: "Alex Reviewer", due: "Today", priority: "High", status: "In progress", related: "TR-260714-014" },
  { id: "TASK-103", title: "Request current Notion security overview", assignee: "Maya Patel", due: "Today", priority: "High", status: "Open", related: "TR-260714-011" },
  { id: "TASK-102", title: "Review Zoom AI accessibility findings", assignee: "Jordan Lee", due: "Tomorrow", priority: "Medium", status: "Open", related: "TR-260714-006" },
  { id: "TASK-099", title: "Attach approved Canvas match citation", assignee: "Alex Reviewer", due: "Complete", priority: "Low", status: "Complete", related: "TR-260714-018" },
];

const reviewNotes = [
  { id: "NOTE-21", title: "Canvas AI Assist approval context", preview: "Exact approved-software match confirmed against the July export. Keep the source row attached to the decision.", author: "Jordan Lee", updated: "12 min ago", tag: "Decision" },
  { id: "NOTE-18", title: "LabArchives reviewer handoff", preview: "Packet draft is ready. Accessibility claims need a version-specific check before the reviewer approves.", author: "Alex Reviewer", updated: "41 min ago", tag: "Handoff" },
  { id: "NOTE-13", title: "Evidence boundary reminder", preview: "Campus policy sources and vendor evidence must remain in separate retrieval scopes for every case.", author: "Review operations", updated: "Yesterday", tag: "Policy" },
];

const mainNavItems: Array<{ key: ViewKey; label: string; icon: typeof LayoutDashboard; count?: string; queueMode?: QueueMode }> = [
  { key: "overview", label: "Home", icon: LayoutDashboard },
  { key: "runs", label: "Inbox", icon: Inbox, count: "4", queueMode: "inbox" },
  { key: "runs", label: "My work", icon: ClipboardCheck, count: "2", queueMode: "my-work" },
];

const workspaceNavItems: Array<{ key: ViewKey; label: string; icon: typeof LayoutDashboard; count?: string }> = [
  { key: "vendors", label: "Vendors", icon: Building2, count: "6" },
  { key: "contacts", label: "Contacts", icon: ContactRound },
  { key: "requests", label: "Review requests", icon: FileCheck2, count: "6" },
  { key: "tasks", label: "Tasks", icon: ClipboardCheck, count: "4" },
  { key: "notes", label: "Notes", icon: FileText, count: "3" },
  { key: "dashboard", label: "Dashboards", icon: BarChart3 },
];

const reviewNavItems: Array<{ key: ViewKey; label: string; icon: typeof LayoutDashboard; count?: string }> = [
  { key: "runs", label: "Review runs", icon: Workflow, count: "6" },
  { key: "evidence", label: "Evidence", icon: FolderOpen, count: "5" },
  { key: "audit", label: "Audit trail", icon: History },
];

const pageCopy: Record<ViewKey, { eyebrow: string; title: string; description: string }> = {
  overview: { eyebrow: "Review operations", title: "Technology review workspace", description: "A single operating view for requests, vendor relationships, evidence, and human decisions." },
  runs: { eyebrow: "Workflow records", title: "Review runs", description: "Track every analysis from intake through source-linked result and reviewer decision." },
  vendors: { eyebrow: "Company records", title: "Vendor directory", description: "Maintain vendor ownership, contacts, evidence scope, and active review relationships." },
  contacts: { eyebrow: "People records", title: "Contacts", description: "Connect internal reporting staff with vendor contacts and active review responsibilities." },
  requests: { eyebrow: "Intake records", title: "Review requests", description: "Capture proposed software, requester context, and the inputs needed to start a technology review." },
  tasks: { eyebrow: "Work records", title: "Reviewer tasks", description: "Keep human follow-ups visible across evidence requests, packet edits, and approval decisions." },
  notes: { eyebrow: "Shared context", title: "Review notes", description: "Capture durable context for vendor relationships and handoffs without changing policy outcomes." },
  evidence: { eyebrow: "Supporting records", title: "Evidence library", description: "Keep campus policy, vendor evidence, and captured official sources in clear retrieval scopes." },
  audit: { eyebrow: "Decision history", title: "Audit trail", description: "Trace policy results, reviewer actions, document changes, and simulated write-back events." },
  dashboard: { eyebrow: "Reporting workspace", title: "Review dashboard", description: "See throughput, risk routing, evidence coverage, and reviewer workload at a glance." },
  workflows: { eyebrow: "Automation workspace", title: "Workflows", description: "Configure the bounded review automations that move a request from intake to human decision." },
  "workflow-runs": { eyebrow: "Automation workspace", title: "Workflow runs", description: "Inspect each workflow execution, its current step, and any human pause or escalation." },
  "workflow-versions": { eyebrow: "Automation workspace", title: "Workflow versions", description: "Keep workflow definitions versioned and visible without allowing them to change policy rules." },
  chat: { eyebrow: "Reviewer assistant", title: "Review chat", description: "Ask grounded questions about the current review workspace while keeping policy and approval boundaries explicit." },
  settings: { eyebrow: "Workspace administration", title: "Settings", description: "Configure workspace preferences, reviewer access, integrations, and protected review controls." },
  documentation: { eyebrow: "Workspace help", title: "Documentation", description: "Find the operating guide for review intake, evidence boundaries, human decisions, and simulated write-back." },
};

function toneForLabel(label: string) {
  if (["Complete", "Verified", "Active", "Low risk", "Primary"].includes(label)) return "green";
  if (["In progress", "Needs review", "Medium risk", "Supporting"].includes(label)) return "yellow";
  if (["Escalated", "Expired", "Safe escalation", "Inactive"].includes(label)) return "red";
  if (label === "Archived") return "gray";
  return "blue";
}

function StatusBadge({ label, dot = true }: { label: string; dot?: boolean }) {
  return <span className={`status-badge status-${toneForLabel(label)}`}>{dot && <span className="status-dot" />}{label}</span>;
}

function Avatar({ label, tone = "blue", small = false }: { label: string; tone?: string; small?: boolean }) {
  return <span className={`avatar avatar-${tone} ${small ? "avatar-small" : ""}`}>{label}</span>;
}

function Panel({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <RecordSurface className={className}>{children}</RecordSurface>;
}

function StatCard({ label, value, detail, icon: Icon, tone }: { label: string; value: string; detail: string; icon: typeof Gauge; tone: string }) {
  return <article className="stat-card"><div className={`stat-icon stat-icon-${tone}`}><Icon size={17} /></div><div className="stat-copy"><span>{label}</span><strong>{value}</strong><small>{detail}</small></div></article>;
}

function PageHeader({ view, onAction }: { view: ViewKey; onAction: () => void }) {
  const copy = pageCopy[view];
  const actionLabel = view === "chat" ? "New conversation" : view === "workflows" ? "New workflow" : view === "settings" ? "Save changes" : view === "documentation" ? "Open guide" : "New review";
  return <div className="page-header"><div><div className="breadcrumb-line"><span>CSUB technology review</span><ChevronRight size={13} /><strong>{copy.title}</strong></div><p className="section-eyebrow">{copy.eyebrow}</p><h1>{copy.title}</h1><p className="page-description">{copy.description}</p></div><div className="header-actions"><button className="button button-secondary" onClick={onAction}><Plus size={15} /> {actionLabel}</button><button className="icon-button bordered" aria-label="More actions"><MoreHorizontal size={17} /></button></div></div>;
}

function SearchField({ value, onChange, placeholder = "Search" }: { value: string; onChange: (value: string) => void; placeholder?: string }) {
  return <label className="search-field"><Search size={15} /><input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} aria-label={placeholder} />{value && <button type="button" aria-label="Clear search" onClick={() => onChange("")}><X size={14} /></button>}</label>;
}

function FilterButton({ active, onClick = () => {} }: { active?: boolean; onClick?: () => void }) {
  return <button className={`button button-ghost ${active ? "button-active" : ""}`} onClick={onClick}><ListFilter size={15} /> Filter</button>;
}

function RunTable({ rows, onSelect, selectedId, compact = false }: { rows: ReviewRun[]; onSelect: (run: ReviewRun) => void; selectedId?: string; compact?: boolean }) {
  return <div className="table-scroll"><table className={`data-table ${compact ? "data-table-compact" : ""}`}><thead><tr><th>Review run</th><th>Vendor</th><th>Route</th><th>Result</th><th>Owner</th><th>Updated</th><th /></tr></thead><tbody>{rows.map((run) => <tr key={run.id} className={run.id === selectedId ? "row-active" : ""} onClick={() => onSelect(run)}><td><div className="record-cell"><Avatar label={run.request.slice(0, 2).toUpperCase()} tone={run.route === "Low risk" ? "yellow" : run.route === "Medium risk" ? "blue" : "red"} small /><div><strong>{run.request}</strong><span>{run.id} · {run.requester}</span></div></div></td><td><span className="table-muted">{run.vendor}</span></td><td><div className="stacked-cell"><StatusBadge label={run.route} /><small className="progress-label">{run.progress}% complete</small></div></td><td><div className="stacked-cell"><span>{run.result}</span><small>{run.evidence} evidence items</small></div></td><td><div className="owner-cell"><Avatar label={run.owner.split(" ").map((part) => part[0]).join("")} tone="gray" small /><span>{run.owner}</span></div></td><td><span className="table-muted">{run.updated}</span></td><td><button className="row-action" aria-label={`Open ${run.request}`} onClick={(event) => { event.stopPropagation(); onSelect(run); }}><ArrowUpRight size={15} /></button></td></tr>)}</tbody></table></div>;
}

function DocumentViewer({ document }: { document: EvidenceDocument }) {
  return <Panel className="document-viewer"><div className="viewer-toolbar"><div className="viewer-file"><FileText size={16} /><div><strong>{document.name}</strong><span>{document.kind} · {document.pages} {document.pages === 1 ? "page" : "pages"}</span></div></div><div className="viewer-actions"><button className="icon-button" aria-label="Download document"><Download size={15} /></button><button className="icon-button" aria-label="Open document"><SquareArrowOutUpRight size={15} /></button></div></div><div className="document-canvas"><div className="document-page"><div className="doc-brand"><div className="doc-brand-mark">CSUB</div><span>Technology review evidence</span></div><div className="doc-heading-line" /><p className="doc-title">{document.name.replace(/\.[^.]+$/, "")}</p><p className="doc-meta">Captured source · {document.updated} · {document.scope}</p><div className="doc-highlight"><span className="doc-highlight-label">Referenced finding</span><p>{document.excerpt}</p></div><div className="doc-lines"><span /><span /><span className="short" /><span /><span /><span className="short" /></div><div className="doc-section"><strong>Source location</strong><span>{document.reference}</span></div><div className="doc-footer"><span>Evidence ID: {document.id}</span><span>Page 1 / {document.pages}</span></div></div></div><div className="viewer-footer"><div><StatusBadge label={document.status} /><span>Scoped to {document.scope.toLowerCase()}</span></div><button className="button button-ghost"><Link2 size={14} /> Link to case</button></div></Panel>;
}

function OverviewPage({ onViewChange, onSelectRun, selectedRunId, onOpenDocument }: { onViewChange: (view: ViewKey) => void; onSelectRun: (run: ReviewRun) => void; selectedRunId?: string; onOpenDocument: () => void }) {
  const activeRuns = reviewRuns.filter((run) => run.status !== "Complete");
  return <>
    <div className="stat-grid"><StatCard label="Open review runs" value="4" detail="2 need human action" icon={Workflow} tone="blue" /><StatCard label="Vendor relationships" value="6" detail="3 with active reviews" icon={Building2} tone="yellow" /><StatCard label="Evidence coverage" value="94%" detail="2 source warnings" icon={BookOpen} tone="teal" /><StatCard label="Approved this week" value="18" detail="+14% vs last week" icon={CircleCheck} tone="purple" /></div>
    <div className="overview-grid">
      <Panel className="run-board"><div className="panel-heading"><div><div className="panel-kicker">Workflow records</div><h2>Review runs</h2><p>What is done, in progress, and waiting for a reviewer.</p></div><button className="button button-ghost" onClick={() => onViewChange("runs")}>View all <ArrowRight size={14} /></button></div><div className="run-tabs"><button className="run-tab active">All <span>6</span></button><button className="run-tab">In progress <span>2</span></button><button className="run-tab">Complete <span>2</span></button><button className="run-tab">Escalated <span>1</span></button></div><RunTable rows={reviewRuns.slice(0, 5)} onSelect={onSelectRun} selectedId={selectedRunId} compact /><div className="panel-footer"><span>Last updated a few seconds ago</span><button className="text-button" onClick={() => onViewChange("audit")}>Open audit trail <ArrowRight size={14} /></button></div></Panel>
      <div className="overview-side"><Panel className="health-panel"><div className="panel-heading compact"><div><div className="panel-kicker">Operations pulse</div><h2>Review health</h2></div><Gauge size={17} /></div><div className="health-score"><strong>82</strong><span>/ 100</span><StatusBadge label="On track" /></div><div className="health-bars"><ProgressRow label="Deterministic policy" value={100} color="yellow" /><ProgressRow label="Evidence coverage" value={94} color="teal" /><ProgressRow label="Human decisions" value={67} color="blue" /></div><div className="health-foot"><span><CircleDot size={12} /> {activeRuns.length} active runs</span><span><Clock3 size={12} /> 24h median</span></div></Panel><Panel className="relationship-panel"><div className="panel-heading compact"><div><div className="panel-kicker">Relationship ownership</div><h2>Vendor owners</h2></div><button className="icon-button" onClick={() => onViewChange("vendors")} aria-label="View vendors"><ArrowUpRight size={15} /></button></div><div className="owner-list">{vendors.slice(0, 3).map((vendor) => <div className="owner-row" key={vendor.id}><Avatar label={vendor.name.slice(0, 2).toUpperCase()} tone={vendor.risk === "Low risk" ? "yellow" : vendor.risk === "Medium risk" ? "blue" : "red"} small /><div><strong>{vendor.name}</strong><span>{vendor.owner} · {vendor.activeRuns ? `${vendor.activeRuns} active review` : "No active review"}</span></div><StatusBadge label={vendor.status} dot={false} /></div>)}</div></Panel></div>
    </div>
    <div className="lower-grid"><Panel className="evidence-snapshot"><div className="panel-heading"><div><div className="panel-kicker">Supporting material</div><h2>Evidence viewer</h2><p>Review the source behind the selected result.</p></div><button className="button button-ghost" onClick={onOpenDocument}><FolderOpen size={14} /> Open library</button></div><DocumentViewer document={documents[1]} /></Panel><Panel className="activity-snapshot"><div className="panel-heading"><div><div className="panel-kicker">Decision history</div><h2>Latest activity</h2></div><button className="icon-button" onClick={() => onViewChange("audit")} aria-label="View audit trail"><ArrowUpRight size={15} /></button></div><AuditList compact /></Panel></div>
  </>;
}

function ProgressRow({ label, value, color }: { label: string; value: number; color: string }) {
  return <div className="progress-row"><div><span>{label}</span><strong>{value}%</strong></div><div className="progress-track"><span className={`progress-${color}`} style={{ width: `${value}%` }} /></div></div>;
}

function ReviewRunDetail({ run }: { run: ReviewRun }) {
  const steps = [
    { label: "Guided intake", detail: "Required fields validated", state: "done" },
    { label: "Software match", detail: run.route === "Low risk" ? "Exact approved-software match" : "Candidate confirmed by reviewer", state: "done" },
    { label: "Policy evaluation", detail: `${run.route} · source-linked rule set`, state: "done" },
    { label: "Specialist analysis", detail: run.status === "Escalated" ? "Waiting for evidence" : "Security + accessibility findings", state: run.status === "Escalated" ? "blocked" : "done" },
    { label: "Human review", detail: run.status === "Complete" ? "Decision recorded" : "Reviewer action required", state: run.status === "Complete" ? "done" : "current" },
  ];
  return <Panel className="record-detail-panel run-detail-panel"><div className="detail-heading"><div className="detail-heading-title"><Avatar label={run.request.slice(0, 2).toUpperCase()} tone={run.route === "Low risk" ? "yellow" : run.route === "Medium risk" ? "blue" : "red"} /><div><div className="panel-kicker">Review run</div><h2>{run.request}</h2><span>{run.id} · {run.vendor}</span></div></div><button className="icon-button"><MoreHorizontal size={17} /></button></div><div className="detail-actions"><button className="button button-secondary"><ClipboardCheck size={14} /> {run.status === "Complete" ? "View decision" : "Open review"}</button><button className="button button-ghost"><Paperclip size={14} /> {run.evidence} evidence</button></div><div className="run-result-banner"><div><div className="detail-label">Current result</div><strong>{run.result}</strong><span>{run.requester} · started {run.started}</span></div><StatusBadge label={run.status} /></div><div className="detail-section"><div className="detail-label">Workflow path <span>{run.progress}% complete</span></div><div className="run-step-list">{steps.map((step) => <div className={`run-step run-step-${step.state}`} key={step.label}><div className="run-step-marker">{step.state === "done" ? <Check size={11} /> : step.state === "blocked" ? <AlertTriangle size={11} /> : <CircleDot size={9} />}</div><div><strong>{step.label}</strong><span>{step.detail}</span></div>{step.state === "current" && <ArrowRight size={14} />}</div>)}</div></div><div className="detail-section"><div className="detail-label">Decision controls</div><div className="decision-controls"><button className="button button-ghost"><CircleAlert size={14} /> Request information</button><button className="button button-secondary"><CheckCircle2 size={14} /> Approve decision</button></div><p className="detail-note">Approval remains a human action. The next step is a deterministic ServiceNow preview, followed by a second confirmation before simulated write-back.</p></div><div className="detail-callout"><ShieldCheck size={16} /><div><strong>Policy route is immutable</strong><span>Model findings can explain this result, but cannot alter the calculated route or choose connector fields.</span></div></div></Panel>;
}

function RunsPage({ onSelectRun, selectedRunId, mode = "all" }: { onSelectRun: (run: ReviewRun) => void; selectedRunId?: string; mode?: QueueMode }) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"All" | RunStatus>("All");
  const selectedRun = reviewRuns.find((run) => run.id === selectedRunId) ?? reviewRuns[0];
  const modeRuns = mode === "inbox" ? reviewRuns.filter((run) => run.status !== "Complete") : mode === "my-work" ? reviewRuns.filter((run) => run.owner === "Alex Reviewer") : reviewRuns;
  const filteredRuns = modeRuns.filter((run) => (filter === "All" || run.status === filter) && `${run.request} ${run.vendor} ${run.id} ${run.owner}`.toLowerCase().includes(query.toLowerCase()));
  const title = mode === "inbox" ? "Review inbox" : mode === "my-work" ? "My review work" : "All review runs";
  return <div className="record-layout"><Panel className="record-list-panel"><div className="panel-heading"><div><div className="panel-kicker">Workflow records</div><h2>{title}</h2><p>Deterministic route, specialist progress, result, and owner in one view.</p></div><div className="panel-heading-actions"><SearchField value={query} onChange={setQuery} placeholder="Search review runs" /><FilterButton active={filter !== "All"} onClick={() => setFilter(filter === "All" ? "In progress" : "All")} /></div></div><div className="filter-strip"><button className={filter === "All" ? "selected-filter" : ""} onClick={() => setFilter("All")}>All <span>{modeRuns.length}</span></button><button className={filter === "In progress" ? "selected-filter" : ""} onClick={() => setFilter("In progress")}>In progress <span>{modeRuns.filter((run) => run.status === "In progress").length}</span></button><button className={filter === "Complete" ? "selected-filter" : ""} onClick={() => setFilter("Complete")}>Complete <span>{modeRuns.filter((run) => run.status === "Complete").length}</span></button><button className={filter === "Escalated" ? "selected-filter" : ""} onClick={() => setFilter("Escalated")}>Escalated <span>{modeRuns.filter((run) => run.status === "Escalated").length}</span></button></div><RunTable rows={filteredRuns} onSelect={onSelectRun} selectedId={selectedRun.id} /><div className="panel-footer"><span>{filteredRuns.length} of {modeRuns.length} review runs</span><button className="text-button"><Download size={14} /> Export view</button></div></Panel><ReviewRunDetail run={selectedRun} /></div>;
}

function VendorsPage({ selectedVendorId, onSelectVendor }: { selectedVendorId: string; onSelectVendor: (id: string) => void }) {
  const selectedVendor = vendors.find((vendor) => vendor.id === selectedVendorId) ?? vendors[0];
  const vendorContacts = contacts.filter((contact) => contact.vendorId === selectedVendor.id);
  const vendorRuns = reviewRuns.filter((run) => run.vendorId === selectedVendor.id);
  const [query, setQuery] = useState("");
  const filteredVendors = vendors.filter((vendor) => `${vendor.name} ${vendor.domain} ${vendor.owner}`.toLowerCase().includes(query.toLowerCase()));
  return <div className="record-layout"><Panel className="record-list-panel"><div className="panel-heading"><div><div className="panel-kicker">Companies</div><h2>Vendor list</h2><p>Every vendor has an internal reporting person and scoped evidence.</p></div><button className="button button-secondary"><Plus size={14} /> Add vendor</button></div><div className="list-toolbar"><SearchField value={query} onChange={setQuery} placeholder="Search vendors" /><FilterButton /></div><div className="table-scroll"><table className="data-table"><thead><tr><th>Vendor</th><th>Internal reporting person</th><th>Reviews</th><th>Last review</th><th>Status</th><th /></tr></thead><tbody>{filteredVendors.map((vendor) => <tr key={vendor.id} className={vendor.id === selectedVendor.id ? "row-active" : ""} onClick={() => onSelectVendor(vendor.id)}><td><div className="record-cell"><Avatar label={vendor.name.slice(0, 2).toUpperCase()} tone={vendor.risk === "Low risk" ? "yellow" : vendor.risk === "Medium risk" ? "blue" : "red"} /><div><strong>{vendor.name}</strong><span>{vendor.domain}</span></div></div></td><td><div className="owner-cell"><Avatar label={vendor.owner.split(" ").map((part) => part[0]).join("")} tone="gray" small /><div><span>{vendor.owner}</span><small>{vendor.ownerRole}</small></div></div></td><td><span>{vendor.activeRuns} active</span><small className="table-muted">{vendor.contacts} contacts</small></td><td><span className="table-muted">{vendor.lastReview}</span></td><td><div className="stacked-cell"><StatusBadge label={vendor.status} /><StatusBadge label={vendor.risk} dot={false} /></div></td><td><button className="row-action" aria-label={`Open ${vendor.name}`}><ArrowUpRight size={15} /></button></td></tr>)}</tbody></table></div><div className="panel-footer"><span>{filteredVendors.length} vendor records</span><button className="text-button"><Download size={14} /> Export list</button></div></Panel><Panel className="record-detail-panel"><div className="detail-heading"><div className="detail-heading-title"><Avatar label={selectedVendor.name.slice(0, 2).toUpperCase()} tone="yellow" /><div><div className="panel-kicker">Vendor record</div><h2>{selectedVendor.name}</h2><span>{selectedVendor.domain}</span></div></div><button className="icon-button"><MoreHorizontal size={17} /></button></div><div className="detail-actions"><button className="button button-secondary"><Mail size={14} /> Email owner</button><button className="button button-ghost"><SquareArrowOutUpRight size={14} /> Open record</button></div><div className="detail-section"><div className="detail-label">Internal reporting person</div><div className="linked-person"><Avatar label={selectedVendor.owner.split(" ").map((part) => part[0]).join("")} tone="gray" /><div><strong>{selectedVendor.owner}</strong><span>{selectedVendor.ownerRole}</span></div><button className="icon-button"><Link2 size={14} /></button></div><p className="detail-note">This staff member owns the institutional relationship and is the first reviewer contact for {selectedVendor.name}.</p></div><div className="detail-section"><div className="detail-label">Vendor contacts <button className="mini-action"><UserPlus size={12} /> Attach</button></div>{vendorContacts.length ? <div className="contact-stack">{vendorContacts.map((contact) => <div className="linked-person" key={contact.id}><Avatar label={contact.name.split(" ").map((part) => part[0]).join("")} tone="blue" small /><div><strong>{contact.name}</strong><span>{contact.role}</span></div><StatusBadge label={contact.status} dot={false} /></div>)}</div> : <div className="empty-state"><Users size={17} /><span>No vendor contacts attached.</span></div>}</div><div className="detail-section"><div className="detail-label">Active review runs</div>{vendorRuns.length ? vendorRuns.map((run) => <div className="linked-run" key={run.id}><div><strong>{run.request}</strong><span>{run.id} · {run.result}</span></div><StatusBadge label={run.status} /></div>) : <div className="empty-state"><ClipboardCheck size={17} /><span>No active review runs.</span></div>}</div><div className="detail-callout"><ShieldCheck size={16} /><div><strong>Evidence boundary</strong><span>Vendor evidence stays scoped to {selectedVendor.name} and cannot alter campus policy routing.</span></div></div></Panel></div>;
}

function ContactsPage({ selectedContactId, onSelectContact }: { selectedContactId: string; onSelectContact: (id: string) => void }) {
  const selected = contacts.find((contact) => contact.id === selectedContactId) ?? contacts[0];
  const [query, setQuery] = useState("");
  const filtered = contacts.filter((contact) => `${contact.name} ${contact.role} ${contact.vendor} ${contact.email}`.toLowerCase().includes(query.toLowerCase()));
  return <div className="record-layout"><Panel className="record-list-panel"><div className="panel-heading"><div><div className="panel-kicker">People records</div><h2>Contacts & owners</h2><p>Link vendor contacts to the internal staff member responsible for the relationship.</p></div><button className="button button-secondary"><UserPlus size={14} /> Add contact</button></div><div className="list-toolbar"><SearchField value={query} onChange={setQuery} placeholder="Search contacts" /><FilterButton /></div><div className="table-scroll"><table className="data-table"><thead><tr><th>Contact</th><th>Type</th><th>Vendor / portfolio</th><th>Linked staff member</th><th>Status</th><th /></tr></thead><tbody>{filtered.map((contact) => <tr key={contact.id} className={contact.id === selected.id ? "row-active" : ""} onClick={() => onSelectContact(contact.id)}><td><div className="record-cell"><Avatar label={contact.name.split(" ").map((part) => part[0]).join("")} tone={contact.type === "Internal" ? "yellow" : "blue"} /><div><strong>{contact.name}</strong><span>{contact.role}</span></div></div></td><td><StatusBadge label={contact.type} /></td><td><span>{contact.vendor}</span><small className="table-muted">{contact.email}</small></td><td><span>{contact.linkedStaff}</span></td><td><StatusBadge label={contact.status} /></td><td><button className="row-action" aria-label={`Open ${contact.name}`}><ArrowUpRight size={15} /></button></td></tr>)}</tbody></table></div><div className="panel-footer"><span>{filtered.length} people records</span><button className="text-button"><Download size={14} /> Export contacts</button></div></Panel><Panel className="record-detail-panel"><div className="detail-heading"><div className="detail-heading-title"><Avatar label={selected.name.split(" ").map((part) => part[0]).join("")} tone={selected.type === "Internal" ? "yellow" : "blue"} /><div><div className="panel-kicker">Contact record</div><h2>{selected.name}</h2><span>{selected.role}</span></div></div><button className="icon-button"><MoreHorizontal size={17} /></button></div><div className="detail-actions"><button className="button button-secondary"><Mail size={14} /> Email contact</button><button className="button button-ghost"><Link2 size={14} /> Attach to vendor</button></div><div className="detail-section"><div className="detail-label">Contact details</div><div className="contact-detail-line"><Mail size={14} /><span>{selected.email}</span></div><div className="contact-detail-line"><Users size={14} /><span>{selected.type} contact · {selected.status.toLowerCase()}</span></div></div><div className="detail-section"><div className="detail-label">Relationship mapping</div><div className="relationship-map"><div className="map-node"><Avatar label={selected.name.split(" ").map((part) => part[0]).join("")} tone={selected.type === "Internal" ? "yellow" : "blue"} small /><span>{selected.name}</span></div><ArrowRight size={14} /><div className="map-node"><Building2 size={15} /><span>{selected.vendor}</span></div></div><p className="detail-note">{selected.type === "Vendor" ? `${selected.name} is attached to ${selected.linkedStaff}, the internal reporting person for this relationship.` : `${selected.name} is linked to ${selected.linkedStaff} and can be assigned as the internal reporting person on vendor records.`}</p></div><div className="detail-section"><div className="detail-label">Linked review activity</div><div className="contact-activity"><div><strong>{selected.type === "Internal" ? "6 vendor relationships" : "1 vendor relationship"}</strong><span>Ownership mapping</span></div><div><strong>{selected.type === "Internal" ? "2 active" : "1 active"}</strong><span>Review runs</span></div></div></div></Panel></div>;
}

function EvidencePage({ selectedDocumentId, onSelectDocument }: { selectedDocumentId: string; onSelectDocument: (id: string) => void }) {
  const selected = documents.find((document) => document.id === selectedDocumentId) ?? documents[0];
  const [query, setQuery] = useState("");
  const filtered = documents.filter((document) => `${document.name} ${document.vendor} ${document.kind} ${document.scope}`.toLowerCase().includes(query.toLowerCase()));
  return <div className="evidence-layout"><Panel className="document-list-panel"><div className="panel-heading"><div><div className="panel-kicker">Source records</div><h2>Evidence library</h2><p>Policy and vendor evidence remain in separate retrieval scopes.</p></div><button className="button button-secondary"><Upload size={14} /> Add evidence</button></div><div className="list-toolbar"><SearchField value={query} onChange={setQuery} placeholder="Search evidence" /><FilterButton /></div><div className="document-list">{filtered.map((document) => <button className={`document-list-item ${document.id === selected.id ? "document-selected" : ""}`} key={document.id} onClick={() => onSelectDocument(document.id)}><div className="document-list-icon"><FileText size={16} /></div><div><strong>{document.name}</strong><span>{document.kind} · {document.vendor}</span><small>{document.updated} · {document.pages} {document.pages === 1 ? "page" : "pages"}</small></div><StatusBadge label={document.status} dot={false} /></button>)}</div><div className="panel-footer"><span>{filtered.length} evidence records</span><button className="text-button"><SlidersHorizontal size={14} /> Manage scopes</button></div></Panel><div className="evidence-detail"><DocumentViewer document={selected} /><Panel className="evidence-metadata"><div className="panel-heading compact"><div><div className="panel-kicker">Source metadata</div><h2>Evidence record</h2></div><button className="icon-button"><MoreHorizontal size={17} /></button></div><div className="metadata-grid"><div><span>Source scope</span><strong>{selected.scope}</strong></div><div><span>Vendor / owner</span><strong>{selected.vendor}</strong></div><div><span>Source location</span><strong>{selected.reference}</strong></div><div><span>Freshness</span><strong>{selected.updated}</strong></div></div><div className="citation-callout"><BookOpen size={15} /><div><strong>Used by 2 review runs</strong><span>Citations are preserved with the policy result and packet draft.</span></div></div></Panel></div></div>;
}

function AuditList({ compact = false }: { compact?: boolean }) {
  return <div className={`audit-list ${compact ? "audit-list-compact" : ""}`}>{auditEvents.map((event) => <div className="audit-item" key={`${event.time}-${event.event}`}><div className={`audit-marker audit-${event.tone}`}><CircleDot size={13} /></div><div className="audit-event"><div><strong>{event.actor}</strong> <span>{event.event}</span></div><small>{event.detail}</small></div><time>{event.time}</time></div>)}</div>;
}

function AuditPage() {
  return <div className="audit-page-grid"><Panel className="audit-history"><div className="panel-heading"><div><div className="panel-kicker">Immutable record</div><h2>Recent audit events</h2><p>Decisions, citations, reviewer actions, and simulated connector activity.</p></div><button className="button button-ghost"><Download size={14} /> Export audit</button></div><AuditList /></Panel><div className="audit-side"><Panel className="audit-summary"><div className="panel-heading compact"><div><div className="panel-kicker">Audit coverage</div><h2>Traceability</h2></div><ShieldCheck size={17} /></div><div className="audit-summary-stat"><strong>100%</strong><span>of current decisions have source references</span></div><ProgressRow label="Workflow events" value={100} color="yellow" /><ProgressRow label="Reviewer actions" value={100} color="blue" /><ProgressRow label="Write-back records" value={67} color="teal" /></Panel><Panel className="audit-summary"><div className="panel-kicker">Protected actions</div><div className="protected-action"><CheckCircle2 size={15} /><span>Human approval recorded</span></div><div className="protected-action"><CheckCircle2 size={15} /><span>Policy route immutable</span></div><div className="protected-action"><CheckCircle2 size={15} /><span>Connector write simulated</span></div><button className="button button-secondary full-width"><Settings2 size={14} /> Audit configuration</button></Panel></div></div>;
}

function RequestsPage({ onSelectRun }: { onSelectRun: (run: ReviewRun) => void }) {
  return <Panel className="full-panel"><div className="panel-heading"><div><div className="panel-kicker">Intake records</div><h2>Review requests</h2><p>Requests are the starting point for a review run. They retain requester context before analysis begins.</p></div><button className="button button-secondary"><Plus size={14} /> New request</button></div><div className="list-toolbar"><SearchField value="" onChange={() => {}} placeholder="Search requests" /><FilterButton /></div><div className="request-card-grid">{reviewRuns.map((run) => <button className="request-card" key={run.id} onClick={() => onSelectRun(run)}><div className="request-card-top"><Avatar label={run.request.slice(0, 2).toUpperCase()} tone={run.route === "Low risk" ? "yellow" : run.route === "Medium risk" ? "blue" : "red"} small /><StatusBadge label={run.status} /></div><strong>{run.request}</strong><span>{run.requester} · {run.vendor}</span><div className="request-card-meta"><span>{run.id}</span><span>{run.updated}</span></div></button>)}</div><div className="panel-footer"><span>{reviewRuns.length} intake records</span><button className="text-button"><Download size={14} /> Export requests</button></div></Panel>;
}

function TasksPage() {
  const [selectedTaskId, setSelectedTaskId] = useState(reviewTasks[0].id);
  const [query, setQuery] = useState("");
  const selected = reviewTasks.find((task) => task.id === selectedTaskId) ?? reviewTasks[0];
  const filtered = reviewTasks.filter((task) => `${task.title} ${task.assignee} ${task.related}`.toLowerCase().includes(query.toLowerCase()));
  return <div className="record-layout"><Panel className="record-list-panel"><div className="panel-heading"><div><div className="panel-kicker">Human work queue</div><h2>Reviewer tasks</h2><p>Follow-ups stay visible and separate from deterministic policy results.</p></div><button className="button button-secondary"><Plus size={14} /> New task</button></div><div className="list-toolbar"><SearchField value={query} onChange={setQuery} placeholder="Search tasks" /><FilterButton /></div><div className="table-scroll"><table className="data-table task-table"><thead><tr><th>Task</th><th>Assignee</th><th>Due</th><th>Priority</th><th>Status</th></tr></thead><tbody>{filtered.map((task) => <tr key={task.id} className={task.id === selected.id ? "row-active" : ""} onClick={() => setSelectedTaskId(task.id)}><td><div className="record-cell"><div className="task-check"><Check size={12} /></div><div><strong>{task.title}</strong><span>{task.id} · {task.related}</span></div></div></td><td><span className="table-muted">{task.assignee}</span></td><td><span className="table-muted">{task.due}</span></td><td><StatusBadge label={task.priority} /></td><td><StatusBadge label={task.status} /></td></tr>)}</tbody></table></div><div className="panel-footer"><span>{filtered.length} of {reviewTasks.length} tasks</span><span>Human actions only</span></div></Panel><Panel className="record-detail-panel"><div className="detail-heading"><div><div className="panel-kicker">Task record</div><h2>{selected.title}</h2><span>{selected.id} · linked to {selected.related}</span></div><button className="icon-button"><MoreHorizontal size={17} /></button></div><div className="detail-actions"><button className="button button-secondary"><CheckCircle2 size={14} /> Mark complete</button><button className="button button-ghost"><Link2 size={14} /> Open review</button></div><div className="detail-section"><div className="detail-label">Assigned reviewer</div><div className="linked-person"><Avatar label={selected.assignee.split(" ").map((part) => part[0]).join("")} tone="gray" /><div><strong>{selected.assignee}</strong><span>{selected.priority} priority · due {selected.due.toLowerCase()}</span></div></div></div><div className="detail-section"><div className="detail-label">Task guidance</div><p className="detail-note">Complete this follow-up with source-linked evidence or a reviewer note. Tasks cannot change the calculated policy route or approve a request.</p></div><div className="detail-callout"><ShieldCheck size={16} /><div><strong>Human-owned work</strong><span>Reviewer tasks document the decision process and remain visible in the audit trail.</span></div></div></Panel></div>;
}

function NotesPage() {
  const [selectedNoteId, setSelectedNoteId] = useState(reviewNotes[0].id);
  const selected = reviewNotes.find((note) => note.id === selectedNoteId) ?? reviewNotes[0];
  return <div className="notes-layout"><Panel className="notes-list"><div className="panel-heading"><div><div className="panel-kicker">Shared context</div><h2>Review notes</h2><p>Short, durable context for handoffs and vendor relationships.</p></div><button className="button button-secondary"><Plus size={14} /> New note</button></div><div className="notes-list-items">{reviewNotes.map((note) => <button className={`note-list-item ${note.id === selected.id ? "note-selected" : ""}`} key={note.id} onClick={() => setSelectedNoteId(note.id)}><div className="note-list-top"><StatusBadge label={note.tag} dot={false} /><span>{note.updated}</span></div><strong>{note.title}</strong><p>{note.preview}</p><small>{note.author}</small></button>)}</div></Panel><Panel className="note-detail"><div className="detail-heading"><div><div className="panel-kicker">Note record</div><h2>{selected.title}</h2><span>{selected.id} · updated {selected.updated}</span></div><button className="icon-button"><MoreHorizontal size={17} /></button></div><div className="detail-actions"><button className="button button-secondary"><Check size={14} /> Save note</button><button className="button button-ghost"><Link2 size={14} /> Link to review</button></div><div className="note-editor"><div className="note-editor-toolbar"><strong>{selected.tag}</strong><span>{selected.author}</span></div><p>{selected.preview}</p><p>Keep reviewer context here without copying unsupported claims into the policy result. Source citations belong in the evidence record and packet.</p></div><div className="detail-callout"><BookOpen size={16} /><div><strong>Notes are context, not policy</strong><span>Notes can inform a handoff, but only approved clauses and deterministic rules can establish a review outcome.</span></div></div></Panel></div>;
}

function DashboardPage() {
  const weekly = [6, 9, 8, 13, 11, 18, 15];
  const maxWeekly = Math.max(...weekly);
  return <>
    <div className="stat-grid dashboard-stat-grid"><StatCard label="Reviews this month" value="48" detail="+18% vs last month" icon={BarChart3} tone="blue" /><StatCard label="Median time to decision" value="1.8d" detail="within 2-day target" icon={Clock3} tone="yellow" /><StatCard label="Evidence coverage" value="94%" detail="2 source warnings" icon={BookOpen} tone="teal" /><StatCard label="Escalation rate" value="12%" detail="6 cases need review" icon={AlertTriangle} tone="purple" /></div><div className="dashboard-grid"><Panel className="dashboard-chart-panel"><div className="panel-heading"><div><div className="panel-kicker">Throughput</div><h2>Review activity</h2><p>Completed and active review requests over the last seven days.</p></div><button className="button button-ghost"><Download size={14} /> Export</button></div><div className="chart-legend"><span><i className="legend-blue" /> Completed</span><span><i className="legend-yellow" /> In progress</span></div><div className="bar-chart" aria-label="Review activity bar chart">{weekly.map((value, index) => <div className="bar-column" key={`${value}-${index}`}><div className="bar-value">{value}</div><div className="bar-track"><span className="bar-fill" style={{ height: `${(value / maxWeekly) * 100}%` }} /></div><small>{["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][index]}</small></div>)}</div></Panel><Panel className="dashboard-risk-panel"><div className="panel-heading compact"><div><div className="panel-kicker">Routing distribution</div><h2>Risk routes</h2></div><ShieldCheck size={17} /></div><div className="risk-donut"><div className="risk-donut-center"><strong>48</strong><span>reviews</span></div></div><div className="risk-legend"><div><i className="risk-low" /><span>Low risk</span><strong>24 · 50%</strong></div><div><i className="risk-medium" /><span>Medium risk</span><strong>18 · 38%</strong></div><div><i className="risk-safe" /><span>Safe escalation</span><strong>6 · 12%</strong></div></div></Panel><Panel className="dashboard-owners"><div className="panel-heading"><div><div className="panel-kicker">Workload</div><h2>Reviewer capacity</h2><p>Open work grouped by current owner.</p></div><button className="icon-button"><ArrowUpRight size={15} /></button></div><div className="capacity-list">{[["Alex Reviewer", "6 open", 78, "yellow"], ["Jordan Lee", "4 open", 61, "blue"], ["Maya Patel", "3 open", 44, "teal"]].map(([name, open, value, color]) => <div className="capacity-row" key={String(name)}><div className="capacity-label"><Avatar label={String(name).split(" ").map((part) => part[0]).join("")} tone="gray" small /><div><strong>{name}</strong><span>{open}</span></div><em>{value}%</em></div><div className="progress-track"><span className={`progress-${color}`} style={{ width: `${value}%` }} /></div></div>)}</div></Panel><Panel className="dashboard-activity"><div className="panel-heading"><div><div className="panel-kicker">Latest decisions</div><h2>Recent approvals and escalations</h2></div><button className="text-button">View audit <ArrowRight size={14} /></button></div><AuditList /></Panel></div>
  </>;
}

function WorkflowBuilder({ workflow, onViewChange, onNotice }: { workflow: (typeof workflowRecords)[number]; onViewChange: (view: ViewKey) => void; onNotice: (message: string) => void }) {
  const initialNodes = createBuilderNodes(workflow.id);
  const [nodes, setNodes] = useState<BuilderNode[]>(initialNodes);
  const [selectedNodeId, setSelectedNodeId] = useState(initialNodes[1]?.id ?? initialNodes[0].id);
  const [inspectorMode, setInspectorMode] = useState<"config" | "library">("config");
  const [workflowStatus, setWorkflowStatus] = useState<"Draft" | "Active">("Draft");
  const selectedNode = nodes.find((node) => node.id === selectedNodeId);
  const groupedTemplates = ["Review operations", "AI and evidence", "Flow", "Human input", "Connector"].map((group) => ({ group, templates: builderNodeTemplates.filter((template) => template.group === group) })).filter((item) => item.templates.length);
  const updateSelectedNode = (field: "title" | "detail", value: string) => setNodes((current) => current.map((node) => node.id === selectedNodeId ? { ...node, [field]: value } : node));
  const addNode = (template: BuilderNode) => { const newNode = { ...template, id: `${template.id}-${Date.now()}` }; setNodes((current) => [...current, newNode]); setSelectedNodeId(newNode.id); setInspectorMode("config"); onNotice(`${template.title} added to the workflow.`); };
  const resetDraft = () => { const resetNodes = createBuilderNodes(workflow.id); setNodes(resetNodes); setSelectedNodeId(resetNodes[1]?.id ?? resetNodes[0].id); setWorkflowStatus("Draft"); onNotice("Draft changes discarded."); };
  const removeSelectedNode = () => { if (!selectedNode || selectedNode.kind === "trigger") return; const next = nodes.filter((node) => node.id !== selectedNode.id); setNodes(next); setSelectedNodeId(next[Math.max(0, next.length - 1)].id); onNotice(`${selectedNode.title} removed from the draft.`); };
  const selectNode = (id: string) => { setSelectedNodeId(id); setInspectorMode(id ? "config" : "library"); };

  return <div className="workflow-builder-shell"><div className="workflow-builder-toolbar"><div className="builder-breadcrumb"><Workflow size={16} /><span>Workflows</span><ChevronRight size={13} /><strong>{workflow.name}</strong><StatusBadge label={workflowStatus} /></div><div className="builder-toolbar-actions"><button className="icon-button bordered" aria-label="Workflow options"><MoreHorizontal size={16} /></button><button className="button button-ghost" onClick={() => { setWorkflowStatus("Active"); onNotice("Workflow activated locally."); }}><CheckCircle2 size={14} /> {workflowStatus === "Active" ? "Active" : "Activate"}</button><button className="button button-ghost" onClick={resetDraft}><X size={14} /> Discard draft</button><button className="button button-ghost" onClick={() => onViewChange("workflow-runs")}><CircleDotDashed size={14} /> See runs</button><button className="button button-secondary" onClick={() => setInspectorMode("library")}><Plus size={14} /> Add a node</button></div></div><div className="workflow-builder-body"><div className="workflow-canvas"><div className="canvas-status"><StatusBadge label={workflowStatus} dot={false} /><span>{nodes.length} nodes · v2026.07.14</span></div><WorkflowCanvas nodes={nodes} selectedNodeId={selectedNodeId} onSelectNode={selectNode} onAddNode={() => setInspectorMode("library")} /></div><aside className="workflow-inspector">{inspectorMode === "config" && selectedNode ? <><div className="inspector-header"><div><div className="panel-kicker">Selected node</div><h2>{selectedNode.title}</h2><span>{selectedNode.kind === "trigger" ? "Trigger" : selectedNode.kind === "human" ? "Human input" : "Action step"}</span></div><button className="icon-button" onClick={() => setInspectorMode("library")} aria-label="Select another action"><Plus size={16} /></button></div><div className="inspector-form"><label>Display name<input value={selectedNode.title} onChange={(event) => updateSelectedNode("title", event.target.value)} /></label><label>Step description<textarea value={selectedNode.detail} onChange={(event) => updateSelectedNode("detail", event.target.value)} /></label><div className="inspector-section"><div className="detail-label">Execution boundary</div><div className="inspector-boundary"><ShieldCheck size={15} /><span>{selectedNode.kind === "human" ? "Pauses for a human decision" : "Read-only or draft-producing step"}</span></div></div><button className="button button-ghost full-width" onClick={removeSelectedNode} disabled={selectedNode.kind === "trigger"}><X size={14} /> Remove node</button></div></> : <><div className="inspector-header"><div><div className="panel-kicker">Add a node</div><h2>Select an action</h2><span>Choose a bounded step for this review workflow.</span></div><button className="icon-button" onClick={() => { setInspectorMode("config"); setSelectedNodeId(nodes[0].id); }} aria-label="Close action library"><X size={16} /></button></div><div className="action-library">{groupedTemplates.map(({ group, templates }) => <div className="action-group" key={group}><div className="action-group-title">{group}</div>{templates.map((template) => { const TemplateIcon = template.icon; return <button className="action-library-item" key={template.id} onClick={() => addNode(template)}><span className={`builder-node-icon builder-tone-${template.tone}`}><TemplateIcon size={15} /></span><span><strong>{template.title}</strong><small>{template.detail}</small></span><Plus size={14} /></button>; })}</div>)}</div></>}<div className="inspector-footer"><ShieldCheck size={14} /><span>Policy routing remains deterministic. Workflow steps cannot approve or write without human confirmation.</span></div></aside></div></div>;
}

function WorkflowPage({ view, onViewChange, onNotice }: { view: "workflows" | "workflow-runs" | "workflow-versions"; onViewChange: (view: ViewKey) => void; onNotice: (message: string) => void }) {
  const [selectedId, setSelectedId] = useState(workflowRecords[0].id);
  const selected = workflowRecords.find((workflow) => workflow.id === selectedId) ?? workflowRecords[0];
  return <div className="workflow-page"><Panel className="workflow-nav-panel"><div className="workflow-tabs"><button className={view === "workflows" ? "workflow-tab-active" : ""} onClick={() => onViewChange("workflows")}><Workflow size={14} /> Workflows</button><button className={view === "workflow-runs" ? "workflow-tab-active" : ""} onClick={() => onViewChange("workflow-runs")}><CircleDotDashed size={14} /> Workflow runs</button><button className={view === "workflow-versions" ? "workflow-tab-active" : ""} onClick={() => onViewChange("workflow-versions")}><History size={14} /> Workflow versions</button></div></Panel>{view === "workflows" && <><Panel className="workflow-picker"><div><div className="panel-kicker">Automation definition</div><strong>Choose a review workflow to edit</strong><span>Changes stay in this local draft until activated.</span></div><select value={selectedId} onChange={(event) => setSelectedId(event.target.value)} aria-label="Choose workflow"><option value={workflowRecords[0].id}>Technology review intake</option>{workflowRecords.slice(1).map((workflow) => <option value={workflow.id} key={workflow.id}>{workflow.name}</option>)}</select><button className="button button-ghost" onClick={() => onNotice("New workflow draft created from the review template.")}><Plus size={14} /> New workflow</button></Panel><WorkflowBuilder key={selected.id} workflow={selected} onViewChange={onViewChange} onNotice={onNotice} /></>}{view === "workflow-runs" && <Panel className="full-panel"><div className="panel-heading"><div><div className="panel-kicker">Automation executions</div><h2>Workflow runs</h2><p>Every execution is traceable to a review run and a versioned definition.</p></div><FilterButton /></div><div className="table-scroll"><table className="data-table"><thead><tr><th>Workflow run</th><th>Workflow</th><th>Current step</th><th>Started</th><th>Status</th></tr></thead><tbody>{reviewRuns.map((run, index) => <tr key={run.id}><td><div className="record-cell"><div className="workflow-run-marker"><CircleDotDashed size={14} /></div><div><strong>{run.id}</strong><span>{run.request}</span></div></div></td><td><span className="table-muted">{index % 2 ? "Medium-risk packet" : "Technology review intake"}</span></td><td><span>{run.status === "Complete" ? "Human review" : run.result}</span></td><td><span className="table-muted">{run.started}</span></td><td><StatusBadge label={run.status} /></td></tr>)}</tbody></table></div><div className="panel-footer"><span>{reviewRuns.length} workflow executions</span><span>Source-linked and auditable</span></div></Panel>}{view === "workflow-versions" && <div className="version-grid">{workflowRecords.slice(0, 3).map((workflow, index) => <Panel className="version-card" key={workflow.id}><div className="version-card-top"><div className="workflow-record-icon"><GitBranch size={14} /></div><StatusBadge label={index === 0 ? "Published" : "Draft"} /></div><h2>{workflow.name}</h2><p>{workflow.description}</p><div className="version-meta"><span>v{index === 0 ? "2026.07.14" : `0.${index + 3}`}</span><span>{index === 0 ? "Published today" : "Edited yesterday"}</span></div><button className="button button-ghost full-width" onClick={() => { setSelectedId(workflow.id); onViewChange("workflows"); }}><ExternalLink size={14} /> View definition</button></Panel>)}</div>}</div>;
}

function ChatPage({ onNotice }: { onNotice: (message: string) => void }) {
  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState([{ role: "assistant", text: "I can help you inspect review runs, vendor evidence, workflow state, and source-linked decisions. I will keep campus policy and vendor evidence in separate scopes." }, { role: "user", text: "What needs human action today?" }, { role: "assistant", text: "Two items are waiting: the LabArchives packet needs a reviewer decision, and Notion AI is safely escalated because current vendor evidence is missing." }]);
  const sendMessage = () => { if (!message.trim()) return; setMessages([...messages, { role: "user", text: message.trim() }, { role: "assistant", text: "I’ll look across the current review workspace and return only source-linked findings. Human approval is still required for any consequential action." }]); setMessage(""); onNotice("Grounded review chat updated."); };
  return <div className="chat-layout"><Panel className="chat-panel"><div className="chat-header"><div className="chat-title"><div className="chat-avatar"><Sparkles size={16} /></div><div><div className="panel-kicker">Reviewer assistant</div><h2>CSUB review copilot</h2><span>Grounded in the current workspace</span></div></div><StatusBadge label="Read-only analysis" dot={false} /></div><div className="chat-messages">{messages.map((item, index) => <div className={`chat-message chat-${item.role}`} key={`${item.role}-${index}`}><div className="chat-message-avatar">{item.role === "assistant" ? <Sparkles size={13} /> : "AR"}</div><div><span className="chat-message-role">{item.role === "assistant" ? "Review copilot" : "You"}</span><p>{item.text}</p></div></div>)}</div><div className="chat-composer"><div className="chat-suggestions"><button onClick={() => setMessage("Summarize today’s review queue")}>Summarize queue</button><button onClick={() => setMessage("Show missing evidence")}>Show evidence gaps</button><button onClick={() => setMessage("Explain the LabArchives route")}>Explain a route</button></div><div className="chat-input-row"><input value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") sendMessage(); }} placeholder="Ask about a review, vendor, or source…" aria-label="Message review copilot" /><button className="button button-secondary" onClick={sendMessage}>Send <ArrowRight size={14} /></button></div><small>Chat can explain and summarize. It cannot approve a request, change policy, or write to ServiceNow.</small></div></Panel><div className="chat-side"><Panel><div className="panel-heading compact"><div><div className="panel-kicker">Current scope</div><h2>Workspace context</h2></div><ShieldCheck size={17} /></div><div className="scope-list"><div><span>Review runs</span><strong>6 loaded</strong></div><div><span>Vendor evidence</span><strong>5 sources</strong></div><div><span>Policy sources</span><strong>2 versions</strong></div><div><span>Human decisions</span><strong>Required</strong></div></div></Panel><Panel><div className="panel-heading compact"><div><div className="panel-kicker">Suggested next step</div><h2>Open the review inbox</h2></div></div><p className="side-copy">Start with the records waiting for evidence or a human decision.</p><button className="button button-secondary full-width" onClick={() => onNotice("Review inbox opened from chat.")}><Inbox size={14} /> Open inbox</button></Panel></div></div>;
}

function SettingsPage() {
  const [tab, setTab] = useState("Workspace");
  const tabs = ["Workspace", "Review controls", "Members", "Integrations", "Notifications"];
  return <div className="settings-layout"><Panel className="settings-nav"><div className="panel-kicker">Administration</div><h2>Workspace settings</h2><div className="settings-tabs">{tabs.map((item) => <button className={tab === item ? "settings-tab-active" : ""} key={item} onClick={() => setTab(item)}><Settings2 size={14} />{item}</button>)}</div></Panel><Panel className="settings-content"><div className="panel-heading"><div><div className="panel-kicker">{tab}</div><h2>{tab} settings</h2><p>These controls are represented locally for the prototype and do not change live AWS or ServiceNow configuration.</p></div><StatusBadge label="Prototype" dot={false} /></div>{tab === "Workspace" && <div className="settings-form"><label>Workspace name<input defaultValue="CSUB Technology Review" /></label><label>Workspace description<textarea defaultValue="Human-reviewed vendor management and technology review operations." /></label><label>Default evidence scope<select defaultValue="Vendor and case scoped"><option>Vendor and case scoped</option><option>Policy only</option></select></label></div>}{tab === "Review controls" && <div className="settings-option-list"><div><div><strong>Require human confirmation for matches</strong><span>Fuzzy and semantic approved-software candidates always pause.</span></div><input type="checkbox" defaultChecked /></div><div><div><strong>Require second confirmation before write-back</strong><span>Mock ServiceNow updates remain two-step and auditable.</span></div><input type="checkbox" defaultChecked /></div><div><div><strong>Keep policy route immutable</strong><span>Model findings can explain a result but cannot alter deterministic routing.</span></div><input type="checkbox" defaultChecked /></div></div>}{tab === "Members" && <div className="settings-member-list">{["Alex Reviewer", "Jordan Lee", "Maya Patel"].map((member) => <div className="linked-person" key={member}><Avatar label={member.split(" ").map((part) => part[0]).join("")} tone="gray" /><div><strong>{member}</strong><span>{member === "Alex Reviewer" ? "Admin · Human reviewer" : "Reviewer"}</span></div><StatusBadge label="Active" /></div>)}</div>}{tab === "Integrations" && <div className="integration-grid"><div><div className="integration-icon"><ShieldCheck size={16} /></div><strong>Mock ServiceNow</strong><span>Configured preview and simulated write-back.</span><StatusBadge label="Connected" /></div><div><div className="integration-icon"><FolderOpen size={16} /></div><strong>Box source corpus</strong><span>Read-only source manifest for prototype evidence.</span><StatusBadge label="Connected" /></div><div><div className="integration-icon"><Sparkles size={16} /></div><strong>Review assistant</strong><span>Local grounded analysis surface.</span><StatusBadge label="Enabled" /></div></div>}{tab === "Notifications" && <div className="settings-option-list"><div><div><strong>Inbox assignment alerts</strong><span>Notify reviewers when a task or review needs human action.</span></div><input type="checkbox" defaultChecked /></div><div><div><strong>Evidence freshness warnings</strong><span>Surface stale and mismatched sources in the review queue.</span></div><input type="checkbox" defaultChecked /></div></div>}<div className="settings-footer"><span>Last saved locally just now</span><button className="button button-secondary">Save changes</button></div></Panel></div>;
}

function DocumentationPage() {
  const sections = [{ title: "Start a technology review", detail: "Create an intake record, attach sanitized evidence, and confirm the proposed software match.", icon: FileCheck2 }, { title: "Understand policy routing", detail: "Read source-linked deterministic results and keep model explanations separate from policy rules.", icon: ShieldCheck }, { title: "Review evidence", detail: "Use scoped policy and vendor sources. Expired, mismatched, or contradictory evidence must be surfaced.", icon: BookOpen }, { title: "Approve and write back", detail: "Edit the packet, record a human decision, preview the connector update, then confirm simulated write-back.", icon: CheckCircle2 }];
  return <div className="documentation-layout"><Panel className="documentation-list"><div className="panel-heading"><div><div className="panel-kicker">Getting started</div><h2>Reviewer documentation</h2><p>The operating guide for the CSUB prototype.</p></div><button className="button button-ghost"><ExternalLink size={14} /> Open guide</button></div>{sections.map((section, index) => <button className={`documentation-item ${index === 0 ? "documentation-item-active" : ""}`} key={section.title}><div className="documentation-icon"><section.icon size={16} /></div><div><strong>{section.title}</strong><span>{section.detail}</span></div><ChevronRight size={15} /></button>)}</Panel><Panel className="documentation-detail"><div className="doc-brand-large"><div className="doc-brand-mark">CSUB</div><span>Technology review documentation</span></div><div className="doc-heading-line" /><div className="panel-kicker">Core operating guide</div><h2>Human-reviewed vendor management</h2><p className="documentation-lede">This workspace brings intake, vendor relationships, evidence, deterministic routing, and review decisions into one operating surface.</p><div className="documentation-rule"><CheckCircle2 size={16} /><div><strong>What the assistant can do</strong><span>Extract, summarize, compare evidence, research configured official domains, explain findings, and draft from approved clauses.</span></div></div><div className="documentation-rule"><ShieldCheck size={16} /><div><strong>What stays human or deterministic</strong><span>Policy thresholds, fuzzy-match confirmation, final approval, TAAP signatures, ServiceNow fields, and external writes.</span></div></div><div className="documentation-footer"><span>Prototype docs · v0.1</span><button className="button button-secondary"><LifeBuoy size={14} /> Contact review operations</button></div></Panel></div>;
}

function App() {
  const [activeView, setActiveView] = useState<ViewKey>("overview");
  const [selectedRunId, setSelectedRunId] = useState(reviewRuns[1].id);
  const [selectedVendorId, setSelectedVendorId] = useState(vendors[1].id);
  const [selectedContactId, setSelectedContactId] = useState(contacts[3].id);
  const [selectedDocumentId, setSelectedDocumentId] = useState(documents[1].id);
  const [runsMode, setRunsMode] = useState<QueueMode>("all");
  const [notice, setNotice] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [workflowsExpanded, setWorkflowsExpanded] = useState(true);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  const selectedRun = useMemo(() => reviewRuns.find((run) => run.id === selectedRunId) ?? reviewRuns[1], [selectedRunId]);
  const showNotice = (message: string) => { setNotice(message); window.setTimeout(() => setNotice(""), 2800); };
  const handleNewReview = () => showNotice("Guided intake is queued for the next implementation pass.");
  const setView = (view: ViewKey) => setActiveView(view);
  const navigateTo = (view: ViewKey, queueMode?: QueueMode) => { if (queueMode) setRunsMode(queueMode); else if (view === "runs") setRunsMode("all"); setView(view); setMobileSidebarOpen(false); };
  const isNavActive = (key: ViewKey, queueMode?: QueueMode) => queueMode ? activeView === "runs" && runsMode === queueMode : activeView === key || (key === "workflows" && ["workflow-runs", "workflow-versions"].includes(activeView));

  return <div className={`app-shell ${sidebarCollapsed ? "sidebar-is-collapsed" : ""} ${mobileSidebarOpen ? "sidebar-mobile-open" : ""}`}>
    <aside className="sidebar"><div className="sidebar-top"><div className="brand-lockup"><div className="brand-mark"><ShieldCheck size={18} /></div><div className="brand-copy"><strong>CSUB REVIEW</strong><span>Vendor management</span></div></div><button className="collapse-button" onClick={() => setSidebarCollapsed(!sidebarCollapsed)} aria-label="Toggle sidebar"><ChevronRight size={15} /></button></div><div className="workspace-switcher"><div className="workspace-avatar">R</div><div className="workspace-copy"><strong>Reviewer workspace</strong><span>Prototype environment</span></div><ChevronDown size={14} /></div><div className="sidebar-quick-actions"><div className="sidebar-mode-toggle"><button className={activeView === "overview" ? "quick-action-active" : ""} onClick={() => navigateTo("overview")} aria-label="Home"><LayoutDashboard size={15} /></button><button className={activeView === "chat" ? "quick-action-active" : ""} onClick={() => navigateTo("chat")} aria-label="Chat"><MessageCircle size={15} /></button></div><button className="new-chat-button" onClick={() => { navigateTo("chat"); showNotice("New reviewer conversation started."); }}><MessageCircle size={14} /> <span>New chat</span></button></div><nav className="primary-nav" aria-label="Primary navigation"><div className="nav-section-label">Workspace</div>{mainNavItems.map(({ key, label, icon: Icon, count, queueMode }) => <button className={`nav-item ${isNavActive(key, queueMode) ? "nav-item-active" : ""}`} key={`${label}-${key}`} onClick={() => navigateTo(key, queueMode)}><Icon size={16} /><span>{label}</span>{count && <em>{count}</em>}</button>)}{workspaceNavItems.map(({ key, label, icon: Icon, count }) => <button className={`nav-item ${isNavActive(key) ? "nav-item-active" : ""}`} key={`${label}-${key}`} onClick={() => navigateTo(key)}><Icon size={16} /><span>{label}</span>{count && <em>{count}</em>}</button>)}<button className={`nav-item nav-parent ${isNavActive("workflows") ? "nav-item-active" : ""}`} onClick={() => { setWorkflowsExpanded(!workflowsExpanded); navigateTo("workflows"); }}><Workflow size={16} /><span>Workflows</span><ChevronDown className={workflowsExpanded ? "nav-chevron-open" : ""} size={13} /></button>{workflowsExpanded && <div className="nav-nested">{([{ key: "workflows", label: "Workflows", icon: Workflow }, { key: "workflow-runs", label: "Workflow runs", icon: CircleDotDashed }, { key: "workflow-versions", label: "Workflow versions", icon: History }] as Array<{ key: ViewKey; label: string; icon: typeof LayoutDashboard }>).map(({ key, label, icon: Icon }) => <button className={`nav-item nav-item-nested ${activeView === key ? "nav-item-active" : ""}`} key={key} onClick={() => navigateTo(key)}><Icon size={14} /><span>{label}</span></button>)}</div>}<div className="nav-section-label nav-section-spaced">Review system</div>{reviewNavItems.map(({ key, label, icon: Icon, count }) => <button className={`nav-item ${isNavActive(key) ? "nav-item-active" : ""}`} key={`${label}-${key}`} onClick={() => navigateTo(key)}><Icon size={16} /><span>{label}</span>{count && <em>{count}</em>}</button>)}</nav><div className="sidebar-divider" /><div className="nav-section-label">Favorites</div><button className="nav-item favorite-item" onClick={() => { navigateTo("runs", "inbox"); showNotice("Medium-risk packet loaded."); }}><CircleDot size={16} /><span>Medium-risk packet</span></button><button className="nav-item favorite-item" onClick={() => { navigateTo("evidence"); showNotice("Policy sources loaded."); }}><BookOpen size={16} /><span>Policy sources</span></button><div className="sidebar-divider" /><div className="nav-section-label">Other</div><button className={`nav-item ${activeView === "settings" ? "nav-item-active" : ""}`} onClick={() => navigateTo("settings")}><Settings2 size={16} /><span>Settings</span></button><button className={`nav-item ${activeView === "documentation" ? "nav-item-active" : ""}`} onClick={() => navigateTo("documentation")}><LifeBuoy size={16} /><span>Documentation</span></button><div className="sidebar-spacer" /><div className="profile-row"><Avatar label="AR" tone="yellow" small /><div><strong>Alex Reviewer</strong><span>Human reviewer</span></div><MoreHorizontal size={15} /></div></aside>
    <main className="main-content"><header className="topbar"><div className="topbar-left"><button className="mobile-menu" aria-label="Open menu" onClick={() => setMobileSidebarOpen(true)}><PanelLeftClose size={17} /></button><span className="topbar-context">CSUB technology review</span><span className="topbar-slash">/</span><strong>{pageCopy[activeView].title}</strong></div><div className="topbar-right"><label className="global-search"><Search size={14} /><input placeholder="Search records" aria-label="Search records" /><kbd>⌘ K</kbd></label><button className="icon-button" aria-label="Notifications"><Bell size={16} /><i className="notification-dot" /></button><div className="topbar-profile"><Avatar label="AR" tone="yellow" small /><ChevronDown size={13} /></div></div></header><div className="content-wrap"><PageHeader view={activeView} onAction={() => activeView === "chat" ? showNotice("New reviewer conversation started.") : activeView === "settings" ? showNotice("Settings saved locally for this prototype.") : activeView === "documentation" ? showNotice("Documentation guide opened.") : activeView === "workflows" ? showNotice("Workflow builder is ready for the next pass.") : handleNewReview} />{activeView === "overview" && <OverviewPage onViewChange={setView} onSelectRun={(run) => { setSelectedRunId(run.id); setRunsMode("all"); setView("runs"); }} selectedRunId={selectedRun.id} onOpenDocument={() => setView("evidence")} />}{activeView === "runs" && <RunsPage mode={runsMode} onSelectRun={(run) => { setSelectedRunId(run.id); showNotice(`${run.request} selected`); }} selectedRunId={selectedRun.id} />}{activeView === "vendors" && <VendorsPage selectedVendorId={selectedVendorId} onSelectVendor={(id) => { setSelectedVendorId(id); showNotice("Vendor relationship loaded."); }} />}{activeView === "contacts" && <ContactsPage selectedContactId={selectedContactId} onSelectContact={(id) => { setSelectedContactId(id); showNotice("Contact relationship loaded."); }} />}{activeView === "requests" && <RequestsPage onSelectRun={(run) => { setSelectedRunId(run.id); setRunsMode("all"); setView("runs"); }} />}{activeView === "tasks" && <TasksPage />}{activeView === "notes" && <NotesPage />}{activeView === "evidence" && <EvidencePage selectedDocumentId={selectedDocumentId} onSelectDocument={(id) => { setSelectedDocumentId(id); showNotice("Evidence document opened."); }} />}{activeView === "audit" && <AuditPage />}{activeView === "dashboard" && <DashboardPage />}{["workflows", "workflow-runs", "workflow-versions"].includes(activeView) && <WorkflowPage view={activeView as "workflows" | "workflow-runs" | "workflow-versions"} onViewChange={setView} onNotice={showNotice} />}{activeView === "chat" && <ChatPage onNotice={showNotice} />}{activeView === "settings" && <SettingsPage />}{activeView === "documentation" && <DocumentationPage />}</div>{notice && <div className="toast"><CheckCircle2 size={15} />{notice}</div>}</main>
  </div>;
}

export default App;

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("The application root element is missing.");
}

createRoot(rootElement).render(<App />);
