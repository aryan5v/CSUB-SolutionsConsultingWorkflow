import { lazy, Suspense, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  Building2,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleDotDashed,
  ClipboardCheck,
  ContactRound,
  ExternalLink,
  FileCheck2,
  FileText,
  FolderLock,
  GitBranch,
  History,
  Inbox,
  LifeBuoy,
  Link2,
  Mail,
  MessageCircle,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Trash2,
  UserPlus,
  Users,
  Workflow,
  X,
} from "lucide-react";
import { PolicyCriteriaSettings } from "./PolicyCriteriaSettings";
import { DitherAvatar } from "@/components/dither-kit/avatar";
import { DitherButton } from "@/components/dither-kit/button";
import type { WorkflowCanvasNode } from "@/components/twenty/workflow/WorkflowCanvas";
import "./workspace.css";

const WorkflowCanvas = lazy(async () => {
  const module = await import("@/components/twenty/workflow/WorkflowCanvas");
  return { default: module.WorkflowCanvas };
});

export type RestoredPage = "vendors" | "contacts" | "requests" | "tasks" | "notes" | "workflows" | "workflow-runs" | "workflow-versions" | "chat" | "settings" | "documentation";

type Notify = (message: string) => void;
type WorkflowView = "workflows" | "workflow-runs" | "workflow-versions";

type Vendor = {
  id: string;
  name: string;
  domain: string;
  owner: string;
  ownerRole: string;
  contacts: number;
  activeRuns: number;
  lastReview: string;
  status: "Active" | "Needs review" | "Draft";
  route: "Low risk" | "Medium risk" | "Safe escalation";
  note: string;
};

type Contact = {
  id: string;
  name: string;
  role: string;
  type: "Internal" | "Vendor";
  vendor: string;
  email: string;
  linkedStaff: string;
  status: "Primary" | "Supporting";
};

const initialVendors: Vendor[] = [
  { id: "instructure", name: "Instructure", domain: "instructure.com", owner: "Jordan Lee", ownerRole: "Academic Technology", contacts: 3, activeRuns: 1, lastReview: "Today, 09:30", status: "Active", route: "Low risk", note: "Canvas AI Assist matched the approved-software export exactly." },
  { id: "labarchives", name: "LabArchives, LLC", domain: "labarchives.com", owner: "Maya Patel", ownerRole: "Research Technology", contacts: 4, activeRuns: 1, lastReview: "Today, 08:42", status: "Needs review", route: "Medium risk", note: "The packet is ready; the VPAT version still needs human review." },
  { id: "notion", name: "Notion Labs, Inc.", domain: "notion.so", owner: "Alex Reviewer", ownerRole: "Information Security", contacts: 2, activeRuns: 1, lastReview: "Today, 08:04", status: "Needs review", route: "Safe escalation", note: "Current official-domain evidence is incomplete for this request." },
  { id: "zoom", name: "Zoom Video Communications", domain: "zoom.us", owner: "Jordan Lee", ownerRole: "Academic Technology", contacts: 5, activeRuns: 1, lastReview: "Today, 07:25", status: "Active", route: "Medium risk", note: "Security and accessibility analysis are running in parallel." },
  { id: "turnitin", name: "Turnitin, LLC", domain: "turnitin.com", owner: "Maya Patel", ownerRole: "Research Technology", contacts: 3, activeRuns: 0, lastReview: "Yesterday", status: "Active", route: "Low risk", note: "The latest review completed with source-linked approval." },
  { id: "qualtrics", name: "Qualtrics", domain: "qualtrics.com", owner: "Alex Reviewer", ownerRole: "Information Security", contacts: 2, activeRuns: 0, lastReview: "Yesterday", status: "Active", route: "Medium risk", note: "A simulated ServiceNow write-back is recorded in the local audit." },
];

const initialContacts: Contact[] = [
  { id: "jordan", name: "Jordan Lee", role: "Academic Technology lead", type: "Internal", vendor: "Vendor portfolio", email: "jordan.lee@csub.edu", linkedStaff: "6 vendor relationships", status: "Primary" },
  { id: "maya", name: "Maya Patel", role: "Research Technology lead", type: "Internal", vendor: "Vendor portfolio", email: "maya.patel@csub.edu", linkedStaff: "4 vendor relationships", status: "Primary" },
  { id: "alex", name: "Alex Reviewer", role: "Information Security reviewer", type: "Internal", vendor: "Vendor portfolio", email: "alex.reviewer@csub.edu", linkedStaff: "3 vendor relationships", status: "Primary" },
  { id: "instructure-contact", name: "Sam Rivera", role: "Education partnerships", type: "Vendor", vendor: "Instructure", email: "sam.rivera@instructure.com", linkedStaff: "Jordan Lee", status: "Primary" },
  { id: "labarchives-contact", name: "Priya Nair", role: "Higher education solutions", type: "Vendor", vendor: "LabArchives, LLC", email: "priya.nair@labarchives.com", linkedStaff: "Maya Patel", status: "Primary" },
  { id: "notion-contact", name: "Taylor Chen", role: "Public sector partnerships", type: "Vendor", vendor: "Notion Labs, Inc.", email: "taylor.chen@notion.so", linkedStaff: "Alex Reviewer", status: "Supporting" },
];

const requestRecords = [
  { id: "TR-260714-014", product: "LabArchives", vendor: "LabArchives, LLC", requester: "College of Science", status: "Ready for review", route: "Medium risk", updated: "8 min ago" },
  { id: "TR-260714-011", product: "Notion AI", vendor: "Notion Labs, Inc.", requester: "Student Success", status: "Needs evidence", route: "Safe escalation", updated: "34 min ago" },
  { id: "TR-260714-006", product: "Zoom AI Companion", vendor: "Zoom", requester: "Academic Senate", status: "Analyzing", route: "Medium risk", updated: "52 min ago" },
  { id: "TR-260714-018", product: "Canvas AI Assist", vendor: "Instructure", requester: "College of Education", status: "Completed", route: "Low risk", updated: "1 hr ago" },
  { id: "TR-260713-034", product: "Qualtrics XM", vendor: "Qualtrics", requester: "Institutional Research", status: "Completed", route: "Medium risk", updated: "Yesterday" },
];

const initialTasks = [
  { id: "TASK-104", title: "Confirm LabArchives VPAT version", assignee: "Alex Reviewer", due: "Today", priority: "High", status: "In progress", related: "TR-260714-014" },
  { id: "TASK-103", title: "Request current Notion security overview", assignee: "Maya Patel", due: "Today", priority: "High", status: "Open", related: "TR-260714-011" },
  { id: "TASK-102", title: "Review Zoom AI accessibility findings", assignee: "Jordan Lee", due: "Tomorrow", priority: "Medium", status: "Open", related: "TR-260714-006" },
  { id: "TASK-099", title: "Attach approved Canvas match citation", assignee: "Alex Reviewer", due: "Complete", priority: "Low", status: "Complete", related: "TR-260714-018" },
];

const initialNotes = [
  { id: "NOTE-21", title: "Canvas AI Assist approval context", body: "Exact approved-software match confirmed against the July export. Keep the source row attached to the decision.", author: "Jordan Lee", updated: "12 min ago", tag: "Decision" },
  { id: "NOTE-18", title: "LabArchives reviewer handoff", body: "The packet draft is ready. Accessibility claims need a version-specific check before approval.", author: "Alex Reviewer", updated: "41 min ago", tag: "Handoff" },
  { id: "NOTE-13", title: "Evidence boundary reminder", body: "Campus policy sources and vendor evidence must remain in separate retrieval scopes for every case.", author: "Review operations", updated: "Yesterday", tag: "Policy" },
];

const workflowRecords = [
  { id: "wf-review-intake", name: "Technology review intake", description: "Validate intake, find approved-software candidates, and start a review.", status: "Active", owner: "Review operations" },
  { id: "wf-medium-packet", name: "Medium-risk packet", description: "Run scoped specialist checks and prepare an editable packet.", status: "Active", owner: "Information Security" },
  { id: "wf-safe-escalation", name: "Safe escalation", description: "Pause incomplete or contradictory cases for a person.", status: "Active", owner: "Review operations" },
  { id: "wf-evidence-refresh", name: "Evidence freshness check", description: "Flag stale or mismatched evidence before reuse.", status: "Draft", owner: "Data & policy" },
];

function hueFor(value: string) {
  return [...value].reduce((sum, character) => sum + character.charCodeAt(0), 0) % 360;
}

function PersonAvatar({ name, size = 34 }: { name: string; size?: number }) {
  return <span className="dither-avatar-shell" style={{ width: size, height: size }}><DitherAvatar name={name} hue={hueFor(name)} size={size} animate={false} /></span>;
}

function Pill({ children }: { children: string }) {
  const lower = children.toLowerCase();
  const tone = lower.includes("complete") || lower.includes("active") || lower.includes("primary") || lower.includes("low risk") ? "positive" : lower.includes("safe") || lower.includes("needs") || lower.includes("high") ? "critical" : lower.includes("medium") || lower.includes("review") || lower.includes("progress") ? "warning" : "info";
  return <span className={`workspace-pill workspace-pill-${tone}`}><i />{children}</span>;
}

function WorkspaceIntro({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description: string; actions?: ReactNode }) {
  return <header className="workspace-intro"><div><p className="workspace-eyebrow">{eyebrow}</p><h1>{title}</h1><p>{description}</p></div>{actions && <div className="workspace-actions">{actions}</div>}</header>;
}

function DitherAction({ children, onClick, disabled = false }: { children: ReactNode; onClick: () => void; disabled?: boolean }) {
  return <DitherButton color="orange" variant="solid" bloom="low" className="workspace-dither-button" onClick={onClick} disabled={disabled}>{children}</DitherButton>;
}

function PlainAction({ children, onClick, danger = false, disabled = false }: { children: ReactNode; onClick: () => void; danger?: boolean; disabled?: boolean }) {
  return <button className={`workspace-button ${danger ? "workspace-button-danger" : ""}`} onClick={onClick} disabled={disabled}>{children}</button>;
}

function SearchBox({ value, onChange, placeholder }: { value: string; onChange: (value: string) => void; placeholder: string }) {
  return <label className="workspace-search"><Search size={15} /><span className="sr-only">{placeholder}</span><input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /></label>;
}

export function VendorsPage({ notify }: { notify: Notify }) {
  const [vendors, setVendors] = useState(initialVendors);
  const [selectedId, setSelectedId] = useState("labarchives");
  const [query, setQuery] = useState("");
  const selected = vendors.find((vendor) => vendor.id === selectedId) ?? vendors[0];
  const filtered = vendors.filter((vendor) => `${vendor.name} ${vendor.domain} ${vendor.owner}`.toLowerCase().includes(query.toLowerCase()));
  const addVendor = () => {
    const draft: Vendor = { id: `draft-${vendors.length + 1}`, name: "New vendor draft", domain: "Domain pending", owner: "Alex Reviewer", ownerRole: "Information Security", contacts: 0, activeRuns: 0, lastReview: "Not reviewed", status: "Draft", route: "Safe escalation", note: "Complete vendor identity and evidence scope before analysis." };
    setVendors((current) => [draft, ...current]);
    setSelectedId(draft.id);
    notify("New local vendor draft created.");
  };
  return <>
    <WorkspaceIntro eyebrow="Companies / Relationship records" title="Vendors" description="Keep ownership, current reviews, contacts, and evidence boundaries together without turning vendor claims into campus policy." actions={<DitherAction onClick={addVendor}><Plus size={14} aria-hidden="true" /> Add vendor</DitherAction>} />
    <div className="workspace-split">
      <section className="workspace-panel workspace-records" aria-label="Vendor records"><div className="workspace-toolbar"><SearchBox value={query} onChange={setQuery} placeholder="Search vendors" /><span>{filtered.length} records</span></div><div className="workspace-column-labels"><span>Vendor</span><span>Owner</span><span>Status</span></div><div className="workspace-record-list" role="listbox" aria-label="Vendors">{filtered.map((vendor) => <button key={vendor.id} type="button" role="option" className={selected.id === vendor.id ? "selected" : ""} aria-selected={selected.id === vendor.id} onClick={() => setSelectedId(vendor.id)}><span className="workspace-record-identity"><PersonAvatar name={vendor.name} /><span><strong>{vendor.name}</strong><small>{vendor.domain} · {vendor.activeRuns} active reviews</small></span></span><span className="workspace-record-owner"><PersonAvatar name={vendor.owner} size={26} /><span><strong>{vendor.owner}</strong><small>{vendor.ownerRole}</small></span></span><span><Pill>{vendor.status}</Pill><small>{vendor.route}</small></span><ChevronRight size={15} aria-hidden="true" /></button>)}</div></section>
      <aside className="workspace-panel workspace-detail" aria-label={`${selected.name} details`}><div className="workspace-detail-head"><PersonAvatar name={selected.name} size={44} /><div><p className="workspace-eyebrow">Vendor record</p><h2>{selected.name}</h2><span>{selected.domain}</span></div><Pill>{selected.route}</Pill></div><div className="workspace-detail-actions"><DitherAction onClick={() => notify(`Message draft opened for ${selected.owner}.`)}><Mail size={14} aria-hidden="true" /> Email owner</DitherAction><PlainAction onClick={() => notify(`${selected.name} record opened locally.`)}><ExternalLink size={14} aria-hidden="true" /> Open record</PlainAction></div><dl className="workspace-definition-grid"><div><dt>Internal owner</dt><dd>{selected.owner}</dd></div><div><dt>Role</dt><dd>{selected.ownerRole}</dd></div><div><dt>Contacts</dt><dd>{selected.contacts}</dd></div><div><dt>Last review</dt><dd>{selected.lastReview}</dd></div></dl><section className="workspace-detail-section"><p className="workspace-eyebrow">Current context</p><p>{selected.note}</p></section><section className="workspace-detail-section"><p className="workspace-eyebrow">Relationship map</p><div className="relationship-line"><PersonAvatar name={selected.owner} size={28} /><strong>{selected.owner}</strong><ArrowRight size={14} aria-hidden="true" /><Building2 size={15} aria-hidden="true" /><strong>{selected.name}</strong></div></section><div className="workspace-boundary"><FolderLock size={16} aria-hidden="true" /><span><strong>Vendor-scoped evidence</strong> stays with {selected.name}. It cannot modify deterministic campus policy.</span></div></aside>
    </div>
  </>;
}

export function ContactsPage({ notify }: { notify: Notify }) {
  const [contacts, setContacts] = useState(initialContacts);
  const [selectedId, setSelectedId] = useState(initialContacts[3].id);
  const [query, setQuery] = useState("");
  const selected = contacts.find((contact) => contact.id === selectedId) ?? contacts[0];
  const filtered = contacts.filter((contact) => `${contact.name} ${contact.role} ${contact.vendor} ${contact.email}`.toLowerCase().includes(query.toLowerCase()));
  const addContact = () => {
    const draft: Contact = { id: `contact-${contacts.length + 1}`, name: "New contact", role: "Role pending", type: "Vendor", vendor: "Unassigned", email: "Email pending", linkedStaff: "Alex Reviewer", status: "Supporting" };
    setContacts((current) => [draft, ...current]); setSelectedId(draft.id); notify("New local contact draft created.");
  };
  return <>
    <WorkspaceIntro eyebrow="People / Relationship records" title="Contacts" description="Connect vendor contacts to the internal staff member accountable for each relationship." actions={<DitherAction onClick={addContact}><UserPlus size={14} aria-hidden="true" /> Add contact</DitherAction>} />
    <div className="workspace-split"><section className="workspace-panel workspace-records" aria-label="Contacts"><div className="workspace-toolbar"><SearchBox value={query} onChange={setQuery} placeholder="Search contacts" /><span>{filtered.length} people</span></div><div className="workspace-record-list workspace-contact-list" role="listbox" aria-label="People">{filtered.map((contact) => <button key={contact.id} type="button" role="option" className={selected.id === contact.id ? "selected" : ""} aria-selected={selected.id === contact.id} onClick={() => setSelectedId(contact.id)}><span className="workspace-record-identity"><PersonAvatar name={contact.name} /><span><strong>{contact.name}</strong><small>{contact.role}</small></span></span><span><strong>{contact.vendor}</strong><small>{contact.linkedStaff}</small></span><Pill>{contact.status}</Pill><ChevronRight size={15} aria-hidden="true" /></button>)}</div></section><aside className="workspace-panel workspace-detail" aria-label={`${selected.name} details`}><div className="workspace-detail-head"><PersonAvatar name={selected.name} size={44} /><div><p className="workspace-eyebrow">{selected.type} contact</p><h2>{selected.name}</h2><span>{selected.role}</span></div><Pill>{selected.status}</Pill></div><div className="workspace-detail-actions"><DitherAction onClick={() => notify(`Email draft opened for ${selected.name}.`)}><Mail size={14} aria-hidden="true" /> Email contact</DitherAction><PlainAction onClick={() => notify(`${selected.name} attached to ${selected.vendor}.`)}><Link2 size={14} aria-hidden="true" /> Attach</PlainAction></div><dl className="workspace-definition-grid"><div><dt>Email</dt><dd>{selected.email}</dd></div><div><dt>Contact type</dt><dd>{selected.type}</dd></div><div><dt>Vendor / portfolio</dt><dd>{selected.vendor}</dd></div><div><dt>Linked staff</dt><dd>{selected.linkedStaff}</dd></div></dl><section className="workspace-detail-section"><p className="workspace-eyebrow">Relationship map</p><div className="relationship-line"><PersonAvatar name={selected.name} size={28} /><strong>{selected.name}</strong><ArrowRight size={14} aria-hidden="true" /><Building2 size={15} aria-hidden="true" /><strong>{selected.vendor}</strong></div><p>{selected.type === "Vendor" ? `${selected.linkedStaff} owns the internal relationship.` : `${selected.name} can be assigned as the reporting person on vendor records.`}</p></section></aside></div>
  </>;
}

export function RequestsPage({ onOpenReview, notify }: { onOpenReview: () => void; notify: Notify }) {
  const [query, setQuery] = useState("");
  const filtered = requestRecords.filter((request) => `${request.product} ${request.vendor} ${request.requester} ${request.id}`.toLowerCase().includes(query.toLowerCase()));
  return <><WorkspaceIntro eyebrow="Intake / Request records" title="Review requests" description="Requester context stays attached from guided intake through the final human decision." actions={<DitherAction onClick={() => notify("Guided intake opened from Review requests.")}><Plus size={14} /> New request</DitherAction>} /><section className="workspace-panel"><div className="workspace-toolbar"><SearchBox value={query} onChange={setQuery} placeholder="Search requests" /><span>{filtered.length} requests</span></div><div className="request-grid">{filtered.map((request) => <button key={request.id} onClick={() => request.id === "TR-260714-014" ? onOpenReview() : notify(`${request.product} selected in the local request list.`)}><div className="request-card-top"><PersonAvatar name={request.product} /><Pill>{request.status}</Pill></div><strong>{request.product}</strong><span>{request.vendor}</span><small>{request.requester}</small><div><Pill>{request.route}</Pill><em>{request.updated}</em></div></button>)}</div></section></>;
}

export function TasksPage({ notify }: { notify: Notify }) {
  const [tasks, setTasks] = useState(initialTasks);
  const [selectedId, setSelectedId] = useState(initialTasks[0].id);
  const [query, setQuery] = useState("");
  const selected = tasks.find((task) => task.id === selectedId) ?? tasks[0];
  const filtered = tasks.filter((task) => `${task.title} ${task.assignee} ${task.related}`.toLowerCase().includes(query.toLowerCase()));
  const complete = () => { setTasks((current) => current.map((task) => task.id === selected.id ? { ...task, status: "Complete", due: "Complete" } : task)); notify(`${selected.id} marked complete.`); };
  return <><WorkspaceIntro eyebrow="Human work / Follow-ups" title="Tasks" description="Reviewer-owned follow-ups remain visible and separate from deterministic policy results." actions={<DitherAction onClick={() => notify("New task draft created.")}><Plus size={14} aria-hidden="true" /> New task</DitherAction>} /><div className="workspace-split"><section className="workspace-panel workspace-records" aria-label="Tasks"><div className="workspace-toolbar"><SearchBox value={query} onChange={setQuery} placeholder="Search tasks" /><span>{filtered.length} tasks</span></div><div className="task-list" role="listbox" aria-label="Tasks">{filtered.map((task) => <button key={task.id} type="button" role="option" className={selected.id === task.id ? "selected" : ""} aria-selected={selected.id === task.id} onClick={() => setSelectedId(task.id)}><span className="task-check" aria-hidden="true">{task.status === "Complete" ? <Check size={13} /> : <ClipboardCheck size={13} />}</span><span><strong>{task.title}</strong><small>{task.id} · {task.related}</small></span><span><Pill>{task.status}</Pill><small>{task.due}</small></span></button>)}</div></section><aside className="workspace-panel workspace-detail" aria-label={`${selected.title} details`}><p className="workspace-eyebrow">Task record / {selected.id}</p><h2>{selected.title}</h2><p>Linked to {selected.related}</p><div className="workspace-detail-actions"><DitherAction disabled={selected.status === "Complete"} onClick={complete}><CheckCircle2 size={14} aria-hidden="true" /> Mark complete</DitherAction><PlainAction onClick={() => notify(`${selected.related} opened from task.`)}><Link2 size={14} aria-hidden="true" /> Open review</PlainAction></div><dl className="workspace-definition-grid"><div><dt>Assignee</dt><dd>{selected.assignee}</dd></div><div><dt>Due</dt><dd>{selected.due}</dd></div><div><dt>Priority</dt><dd>{selected.priority}</dd></div><div><dt>Status</dt><dd>{selected.status}</dd></div></dl><div className="workspace-boundary"><ShieldCheck size={16} aria-hidden="true" /><span>Completing a task documents work. It cannot change the policy route or approve a request.</span></div></aside></div></>;
}

export function NotesPage({ notify }: { notify: Notify }) {
  const [notes, setNotes] = useState(initialNotes);
  const [selectedId, setSelectedId] = useState(initialNotes[0].id);
  const selected = notes.find((note) => note.id === selectedId) ?? notes[0];
  const [draft, setDraft] = useState(selected.body);
  const select = (id: string) => { const note = notes.find((item) => item.id === id); if (note) { setSelectedId(id); setDraft(note.body); } };
  const save = () => { setNotes((current) => current.map((note) => note.id === selected.id ? { ...note, body: draft, updated: "Just now" } : note)); notify("Review note saved locally."); };
  const add = () => { const note = { id: `NOTE-${notes.length + 22}`, title: "Untitled review note", body: "Add source-aware handoff context here.", author: "Alex Reviewer", updated: "Just now", tag: "Draft" }; setNotes((current) => [note, ...current]); setSelectedId(note.id); setDraft(note.body); };
  return <><WorkspaceIntro eyebrow="Shared context / Handoffs" title="Notes" description="Capture durable context without copying unsupported claims into policy results." actions={<DitherAction onClick={add}><Plus size={14} aria-hidden="true" /> New note</DitherAction>} /><div className="notes-workspace"><section className="workspace-panel notes-list" aria-label="Notes"><div role="listbox" aria-label="Note list">{notes.map((note) => <button key={note.id} type="button" role="option" className={selected.id === note.id ? "selected" : ""} aria-selected={selected.id === note.id} onClick={() => select(note.id)}><div><Pill>{note.tag}</Pill><span>{note.updated}</span></div><strong>{note.title}</strong><p>{note.body}</p><small>{note.author}</small></button>)}</div></section><section className="workspace-panel note-editor" aria-label="Note editor"><div><p className="workspace-eyebrow">{selected.id} / {selected.tag}</p><h2>{selected.title}</h2><span>{selected.author} · {selected.updated}</span></div><textarea value={draft} onChange={(event) => setDraft(event.target.value)} aria-label="Review note text" /><div className="note-editor-actions"><span><BookOpen size={14} aria-hidden="true" />Notes are context, not policy.</span><DitherAction onClick={save}><Check size={14} aria-hidden="true" /> Save note</DitherAction></div></section></div></>;
}

function createWorkflowNodes(workflowId: string): WorkflowCanvasNode[] {
  const templates: WorkflowCanvasNode[] = [
    { id: "validate", title: "Validate intake", detail: "Required fields and evidence metadata", kind: "action", group: "Review operations", icon: FileCheck2, tone: "blue" },
    { id: "policy", title: "Calculate policy route", detail: "Versioned deterministic rules", kind: "condition", group: "Review operations", icon: ShieldCheck, tone: "teal" },
    { id: "evidence", title: "Evidence specialist", detail: "Read case-scoped vendor evidence", kind: "action", group: "AI and evidence", icon: BookOpen, tone: "purple" },
    { id: "human", title: "Human review", detail: "Pause for a recorded decision", kind: "human", group: "Human input", icon: ClipboardCheck, tone: "yellow" },
  ];
  const trigger: WorkflowCanvasNode = { id: `${workflowId}-trigger`, title: "New review request", detail: "Requester submits guided intake", kind: "trigger", group: "Trigger", icon: Workflow, tone: "blue" };
  return [trigger, ...templates.map((node, index) => ({ ...node, id: `${workflowId}-${node.id}-${index}` }))];
}

const libraryNodes: WorkflowCanvasNode[] = [
  { id: "accessibility", title: "Accessibility analysis", detail: "Compare VPAT / ACR evidence", kind: "action", group: "AI and evidence", icon: CheckCircle2, tone: "teal" },
  { id: "citation", title: "Citation checker", detail: "Reject unsupported findings", kind: "action", group: "AI and evidence", icon: BookOpen, tone: "purple" },
  { id: "pause", title: "Wait for evidence", detail: "Hold until a person responds", kind: "human", group: "Human input", icon: Inbox, tone: "yellow" },
  { id: "preview", title: "Mock write preview", detail: "Prepare configured field changes", kind: "action", group: "Connector", icon: ExternalLink, tone: "red" },
];

export function WorkflowsPage({ view, navigate, notify }: { view: WorkflowView; navigate: (page: WorkflowView) => void; notify: Notify }) {
  const [selectedWorkflowId, setSelectedWorkflowId] = useState(workflowRecords[0].id);
  const workflow = workflowRecords.find((item) => item.id === selectedWorkflowId) ?? workflowRecords[0];
  const [nodes, setNodes] = useState<WorkflowCanvasNode[]>(() => createWorkflowNodes(workflow.id));
  const [selectedNodeId, setSelectedNodeId] = useState(nodes[1]?.id ?? nodes[0].id);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [status, setStatus] = useState<"Draft" | "Active">("Draft");
  const selectedNode = nodes.find((node) => node.id === selectedNodeId);
  const chooseWorkflow = (id: string) => { setSelectedWorkflowId(id); const next = createWorkflowNodes(id); setNodes(next); setSelectedNodeId(next[1].id); setStatus("Draft"); };
  const addNode = (template: WorkflowCanvasNode) => { const node = { ...template, id: `${template.id}-${Date.now()}` }; setNodes((current) => [...current, node]); setSelectedNodeId(node.id); setLibraryOpen(false); notify(`${template.title} added to the local draft.`); };
  const updateNode = (field: "title" | "detail", value: string) => setNodes((current) => current.map((node) => node.id === selectedNodeId ? { ...node, [field]: value } : node));
  const removeNode = () => { if (!selectedNode || selectedNode.kind === "trigger") return; const next = nodes.filter((node) => node.id !== selectedNode.id); setNodes(next); setSelectedNodeId(next[next.length - 1]?.id ?? ""); notify(`${selectedNode.title} removed from the draft.`); };
  return <><WorkspaceIntro eyebrow="Automation / Local definitions" title={view === "workflows" ? "Workflows" : view === "workflow-runs" ? "Workflow runs" : "Workflow versions"} description="Compose bounded review automation without allowing a workflow or model to establish policy or approve a request." />
    <div className="workflow-tabs" role="tablist" aria-label="Workflow sections">
      <button type="button" role="tab" className={view === "workflows" ? "active" : ""} onClick={() => navigate("workflows")} aria-selected={view === "workflows"}><Workflow size={14} aria-hidden="true" />Definitions</button>
      <button type="button" role="tab" className={view === "workflow-runs" ? "active" : ""} onClick={() => navigate("workflow-runs")} aria-selected={view === "workflow-runs"}><CircleDotDashed size={14} aria-hidden="true" />Runs</button>
      <button type="button" role="tab" className={view === "workflow-versions" ? "active" : ""} onClick={() => navigate("workflow-versions")} aria-selected={view === "workflow-versions"}><History size={14} aria-hidden="true" />Versions</button>
    </div>
    {view === "workflows" && <><section className="workspace-panel workflow-picker"><span><p className="workspace-eyebrow">Automation definition</p><strong>Choose a workflow to edit</strong><small>Changes remain local until activated.</small></span><label className="sr-only" htmlFor="workflow-definition">Workflow definition</label><select id="workflow-definition" value={selectedWorkflowId} onChange={(event) => chooseWorkflow(event.target.value)} aria-label="Workflow definition">{workflowRecords.map((record) => <option key={record.id} value={record.id}>{record.name}</option>)}</select><DitherAction onClick={() => { setStatus("Active"); notify("Workflow activated locally."); }}><CheckCircle2 size={14} aria-hidden="true" />{status === "Active" ? "Active" : "Activate"}</DitherAction></section><div className="workflow-builder"><section className="workflow-canvas-panel"><div className="workflow-canvas-meta"><Pill>{status}</Pill><span>{nodes.length} nodes · local draft</span><PlainAction onClick={() => setLibraryOpen(true)}><Plus size={14} /> Add node</PlainAction></div><Suspense fallback={<div className="workflow-canvas-loading"><CircleDotDashed size={18} /><span>Loading workflow canvas…</span></div>}><WorkflowCanvas nodes={nodes} selectedNodeId={selectedNodeId} onSelectNode={(id) => { setSelectedNodeId(id); setLibraryOpen(!id); }} onAddNode={() => setLibraryOpen(true)} /></Suspense></section><aside className="workspace-panel workflow-inspector">{libraryOpen || !selectedNode ? <><div className="workflow-inspector-head"><div><p className="workspace-eyebrow">Action library</p><h2>Add a bounded step</h2></div><button onClick={() => setLibraryOpen(false)} aria-label="Close action library"><X size={17} /></button></div><div className="workflow-library">{libraryNodes.map((template) => <button key={template.id} onClick={() => addNode(template)}><span><template.icon size={16} /></span><span><strong>{template.title}</strong><small>{template.detail}</small></span><Plus size={14} /></button>)}</div></> : <><div className="workflow-inspector-head"><div><p className="workspace-eyebrow">Selected node</p><h2>{selectedNode.title}</h2></div><Pill>{selectedNode.kind}</Pill></div><label>Display name<input value={selectedNode.title} onChange={(event) => updateNode("title", event.target.value)} /></label><label>Description<textarea value={selectedNode.detail} onChange={(event) => updateNode("detail", event.target.value)} /></label><div className="workspace-boundary"><ShieldCheck size={16} /><span>{selectedNode.kind === "human" ? "This step pauses for a human decision." : "This step can read or draft; it cannot approve."}</span></div><PlainAction danger disabled={selectedNode.kind === "trigger"} onClick={removeNode}><Trash2 size={14} /> Remove node</PlainAction></>}</aside></div></>}
    {view === "workflow-runs" && <section className="workspace-panel workflow-run-list">{requestRecords.map((run, index) => <article key={run.id}><span className="workflow-run-icon"><CircleDotDashed size={16} /></span><span><strong>{run.id}</strong><small>{run.product}</small></span><span><strong>{index % 2 ? "Medium-risk packet" : "Technology review intake"}</strong><small>{run.status === "Completed" ? "Human review" : run.status}</small></span><Pill>{run.status}</Pill><time>{run.updated}</time></article>)}</section>}
    {view === "workflow-versions" && <div className="workflow-version-grid">{workflowRecords.slice(0, 3).map((record, index) => <article className="workspace-panel" key={record.id}><div><span className="workflow-run-icon"><GitBranch size={15} /></span><Pill>{index === 0 ? "Published" : "Draft"}</Pill></div><h2>{record.name}</h2><p>{record.description}</p><dl><div><dt>Version</dt><dd>{index === 0 ? "v2026.07.14" : `v0.${index + 3}`}</dd></div><div><dt>Owner</dt><dd>{record.owner}</dd></div></dl><PlainAction onClick={() => { chooseWorkflow(record.id); navigate("workflows"); }}><ExternalLink size={14} /> View definition</PlainAction></article>)}</div>}
  </>;
}

export function ChatPage({ notify }: { notify: Notify }) {
  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState([{ role: "assistant", text: "I can summarize review runs, vendor evidence, workflow state, and source-linked decisions. Campus policy and vendor evidence stay in separate scopes." }, { role: "user", text: "What needs human action today?" }, { role: "assistant", text: "LabArchives needs a reviewer decision. Notion AI remains safely paused until current vendor evidence is available." }]);
  const send = () => { if (!message.trim()) return; setMessages((current) => [...current, { role: "user", text: message.trim() }, { role: "assistant", text: "I’ll use the current local workspace and return only source-linked context. A person still owns every consequential decision." }]); setMessage(""); notify("Grounded review chat updated."); };
  return <><WorkspaceIntro eyebrow="Reviewer assistant / Read-only" title="Chat" description="Ask grounded questions across the current workspace without giving the assistant policy or approval authority." /><div className="chat-workspace"><section className="workspace-panel chat-main" aria-label="Review copilot"><header><span className="chat-spark" aria-hidden="true"><Sparkles size={17} /></span><span><strong>CSUB review copilot</strong><small>Grounded in this local workspace</small></span><Pill>Read-only analysis</Pill></header><div className="chat-messages" role="log" aria-live="polite" aria-relevant="additions">{messages.map((item, index) => <article className={`chat-message chat-${item.role}`} key={`${item.role}-${index}`}><span aria-hidden="true">{item.role === "assistant" ? <Sparkles size={14} /> : <PersonAvatar name="Alex Reviewer" size={26} />}</span><div><small>{item.role === "assistant" ? "Review copilot" : "You"}</small><p>{item.text}</p></div></article>)}</div><div className="chat-suggestions" aria-label="Suggested prompts"><button type="button" onClick={() => setMessage("Summarize today’s review queue")}>Summarize queue</button><button type="button" onClick={() => setMessage("Show missing evidence")}>Show evidence gaps</button><button type="button" onClick={() => setMessage("Explain the LabArchives route")}>Explain a route</button></div><div className="chat-composer"><input value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") send(); }} placeholder="Ask about a review, vendor, or source…" aria-label="Message review copilot" /><DitherAction onClick={send}>Send <ArrowRight size={14} aria-hidden="true" /></DitherAction></div><footer>Chat can explain and summarize. It cannot approve, change policy, or write to ServiceNow.</footer></section><aside className="workspace-panel chat-context" aria-label="Workspace context"><p className="workspace-eyebrow">Current scope</p><h2>Workspace context</h2><dl><div><dt>Review runs</dt><dd>5 loaded</dd></div><div><dt>Vendor evidence</dt><dd>Case-scoped</dd></div><div><dt>Policy sources</dt><dd>Separate scope</dd></div><div><dt>Human decisions</dt><dd>Required</dd></div></dl><div className="workspace-boundary"><ShieldCheck size={16} aria-hidden="true" /><span>Retrieved content is untrusted and cannot override system boundaries.</span></div></aside></div></>;
}

export function SettingsPage({ notify }: { notify: Notify }) {
  const tabs = ["Workspace", "Review controls", "Evidence policy", "Members", "Integrations", "Notifications"] as const;
  const [tab, setTab] = useState<(typeof tabs)[number]>("Workspace");
  const [controls, setControls] = useState({ matches: true, writeback: true, policy: true, evidence: true });
  const toggle = (key: keyof typeof controls) => setControls((current) => ({ ...current, [key]: !current[key] }));
  return <><WorkspaceIntro eyebrow="Administration / Local prototype" title="Settings" description="Preview workspace controls without changing live AWS, Box, or ServiceNow configuration." /><div className="settings-workspace"><div className="workspace-panel settings-nav" role="tablist" aria-label="Settings sections">{tabs.map((item) => <button key={item} type="button" role="tab" className={tab === item ? "active" : ""} onClick={() => setTab(item)} aria-selected={tab === item}><Settings2 size={14} aria-hidden="true" />{item}</button>)}</div><section className="workspace-panel settings-main" role="tabpanel" aria-label={`${tab} settings`}><header><div><p className="workspace-eyebrow">{tab}</p><h2>{tab} settings</h2><p>Changes stay in this browser for the prototype.</p></div><Pill>Prototype</Pill></header>{tab === "Workspace" && <div className="settings-form"><label>Workspace name<input defaultValue="CSUB reviewer workspace" /></label><label>Workspace description<textarea defaultValue="Human-reviewed vendor management and technology review operations." /></label><label>Default evidence scope<select defaultValue="Vendor and case scoped"><option>Vendor and case scoped</option><option>Campus policy only</option></select></label></div>}{tab === "Review controls" && <div className="settings-toggles">{([['matches','Require human confirmation for non-exact matches','Fuzzy and semantic candidates always pause.'],['writeback','Require a second write-back confirmation','Mock connector updates remain two-step.'],['policy','Keep policy route immutable','Specialist findings cannot change routing.'],['evidence','Enforce retrieval boundaries','Policy, case, and vendor sources remain separate.']] as const).map(([key,title,detail]) => <label key={key}><span><strong>{title}</strong><small>{detail}</small></span><input type="checkbox" checked={controls[key]} onChange={() => toggle(key)} /></label>)}</div>}{tab === "Evidence policy" && <PolicyCriteriaSettings notify={notify} />}{tab === "Members" && <div className="member-list">{["Alex Reviewer", "Jordan Lee", "Maya Patel"].map((member) => <article key={member}><PersonAvatar name={member} /><span><strong>{member}</strong><small>{member === "Alex Reviewer" ? "Admin · Human reviewer" : "Reviewer"}</small></span><Pill>Active</Pill></article>)}</div>}{tab === "Integrations" && <div className="integration-grid">{[["Mock ServiceNow","Configured preview and simulated write-back.",ShieldCheck],["Box source corpus","Read-only source manifest for prototype evidence.",FolderLock],["Review assistant","Local grounded analysis surface.",Sparkles]].map(([name,detail,Icon]) => { const IntegrationIcon = Icon as typeof ShieldCheck; return <article key={String(name)}><span><IntegrationIcon size={17} /></span><strong>{String(name)}</strong><p>{String(detail)}</p><Pill>Connected</Pill></article>; })}</div>}{tab === "Notifications" && <div className="settings-toggles"><label><span><strong>Human-action alerts</strong><small>Show assignments and evidence holds in the inbox.</small></span><input type="checkbox" defaultChecked /></label><label><span><strong>Evidence freshness warnings</strong><small>Surface stale or mismatched sources.</small></span><input type="checkbox" defaultChecked /></label></div>}{tab !== "Evidence policy" && <footer><span>Local prototype configuration</span><DitherAction onClick={() => notify(`${tab} settings saved locally.`)}><Check size={14} /> Save changes</DitherAction></footer>}</section></div></>;
}

export function DocumentationPage({ notify }: { notify: Notify }) {
  const sections = [
    { title: "Start a technology review", detail: "Create guided intake, attach sanitized evidence, and confirm the software match.", icon: FileCheck2 },
    { title: "Understand policy routing", detail: "Read deterministic results and their source coordinates.", icon: ShieldCheck },
    { title: "Review evidence", detail: "Keep campus policy, case evidence, and vendor material scoped.", icon: BookOpen },
    { title: "Approve and write back", detail: "Edit the packet, decide, preview, then separately confirm the simulation.", icon: CheckCircle2 },
  ];
  const [selected, setSelected] = useState(0);
  const section = sections[selected];
  return <><WorkspaceIntro eyebrow="Operating guide / Prototype v0.1" title="Documentation" description="The practical guide for reviewers using this local technology-review workspace." /><div className="docs-workspace"><div className="workspace-panel docs-list" role="tablist" aria-label="Documentation sections" aria-orientation="vertical">{sections.map((item, index) => <button key={item.title} type="button" role="tab" className={selected === index ? "active" : ""} onClick={() => setSelected(index)} aria-selected={selected === index}><span><item.icon size={16} aria-hidden="true" /></span><span><strong>{item.title}</strong><small>{item.detail}</small></span><ChevronRight size={15} aria-hidden="true" /></button>)}</div><article className="workspace-panel docs-article" role="tabpanel" aria-label={section.title}><header><span>[ CSUB / REVIEW GUIDE ]</span><em>0{selected + 1}</em></header><div className="docs-rule" /><p className="workspace-eyebrow">Core operating guide</p><h2>{section.title}</h2><p className="docs-lede">{section.detail}</p><section><CheckCircle2 size={17} /><span><strong>Assistant boundary</strong><p>The assistant may extract, compare, summarize, and draft from approved clauses. Its output remains reviewable.</p></span></section><section><ShieldCheck size={17} /><span><strong>Human and deterministic boundary</strong><p>People confirm non-exact matches and decisions. Versioned rules calculate the route. External write-back remains simulated.</p></span></section><footer><span>Source-linked · Human-reviewed</span><DitherAction onClick={() => notify("Review operations support request drafted.")}><LifeBuoy size={14} /> Contact operations</DitherAction></footer></article></div></>;
}
