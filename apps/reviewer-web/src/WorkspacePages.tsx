import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import {
  ArrowRight,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronRight,
  ContactRound,
  FileCheck2,
  LifeBuoy,
  Mail,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  UserPlus,
} from "lucide-react";
import { DitherAvatar } from "@/components/dither-kit/avatar";
import { DitherButton } from "@/components/dither-kit/button";
import { ReviewApiError, reviewApi, type VendorContact, type VendorRecord } from "./api";
import { PolicyCriteriaSettings } from "./PolicyCriteriaSettings";
import "./workspace.css";

export type RestoredPage = "vendors" | "contacts" | "requests" | "chat" | "settings" | "documentation";

type Notify = (message: string) => void;

function errorMessage(error: unknown): string {
  return error instanceof ReviewApiError || error instanceof Error ? error.message : "The reviewer API request failed.";
}

function hueFor(value: string) {
  return [...value].reduce((sum, character) => sum + character.charCodeAt(0), 0) % 360;
}

function PersonAvatar({ name, size = 34 }: { name: string; size?: number }) {
  return <span className="dither-avatar-shell" style={{ width: size, height: size }}><DitherAvatar name={name} hue={hueFor(name)} size={size} animate={false} /></span>;
}

function Pill({ children }: { children: string }) {
  const lower = children.toLowerCase();
  const tone = lower.includes("active") || lower.includes("primary") ? "positive" : lower.includes("draft") || lower.includes("review") ? "warning" : "info";
  return <span className={`workspace-pill workspace-pill-${tone}`}><i />{children}</span>;
}

function WorkspaceIntro({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description?: string; actions?: ReactNode }) {
  return <header className={`workspace-intro${description ? "" : " workspace-intro-compact"}`}><div><p className="workspace-eyebrow">{eyebrow}</p><h1>{title}</h1>{description && <p>{description}</p>}</div>{actions && <div className="workspace-actions">{actions}</div>}</header>;
}

function DitherAction({ children, onClick, disabled = false, type = "button" }: { children: ReactNode; onClick?: () => void; disabled?: boolean; type?: "button" | "submit" }) {
  return <DitherButton color="orange" variant="solid" bloom="low" className="workspace-dither-button" onClick={onClick} disabled={disabled} type={type}>{children}</DitherButton>;
}

function SearchBox({ value, onChange, placeholder }: { value: string; onChange: (value: string) => void; placeholder: string }) {
  return <label className="workspace-search"><Search size={15} /><span className="sr-only">{placeholder}</span><input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /></label>;
}

export function ContactsPage({ notify }: { notify: Notify }) {
  const [vendors, setVendors] = useState<VendorRecord[]>([]);
  const [contacts, setContacts] = useState<VendorContact[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([reviewApi.listVendors(), reviewApi.listContacts()]).then(([nextVendors, nextContacts]) => {
      if (!active) return;
      setVendors(nextVendors);
      setContacts(nextContacts);
      setSelectedId(nextContacts[0]?.contact_id ?? "");
    }).catch((reason) => active && setError(errorMessage(reason))).finally(() => active && setLoading(false));
    return () => { active = false; };
  }, []);

  const selected = contacts.find((contact) => contact.contact_id === selectedId) ?? contacts[0];
  const vendorName = (vendorId: string) => vendors.find((vendor) => vendor.vendor_id === vendorId)?.name ?? "Unknown vendor";
  const filtered = contacts.filter((contact) => `${contact.name} ${contact.email} ${vendorName(contact.vendor_id)}`.toLowerCase().includes(query.toLowerCase()));

  const createContact = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true);
    setError("");
    try {
      const created = await reviewApi.createContact({
        vendor_id: String(data.get("vendor_id") || ""),
        name: String(data.get("name") || "").trim(),
        email: String(data.get("email") || "").trim(),
      });
      setContacts((current) => [created, ...current]);
      setSelectedId(created.contact_id);
      form.reset();
      notify(`${created.name} added.`);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  return <>
    <WorkspaceIntro eyebrow="People / Vendor relationships" title="Contacts" />
    {error && <div className="record-api-error" role="alert"><ContactRound size={16} /><span>{error}</span></div>}
    <form className="workspace-panel contact-create-form" onSubmit={createContact}>
      <label>Vendor<select name="vendor_id" required defaultValue=""><option value="" disabled>Select vendor</option>{vendors.map((vendor) => <option key={vendor.vendor_id} value={vendor.vendor_id}>{vendor.name}</option>)}</select></label>
      <label>Name<input name="name" required placeholder="Vendor contact name" /></label>
      <label>Email<input name="email" required type="email" placeholder="contact@vendor.example" /></label>
      <DitherAction type="submit" disabled={busy || !vendors.length}><UserPlus size={14} />{busy ? "Adding…" : "Add contact"}</DitherAction>
    </form>
    {loading ? <section className="workspace-panel record-loading">Loading live contacts…</section> : <div className="workspace-split">
      <section className="workspace-panel workspace-records"><div className="workspace-toolbar"><SearchBox value={query} onChange={setQuery} placeholder="Search contacts" /><span>{filtered.length} people</span></div><div className="workspace-record-list workspace-contact-list">{filtered.map((contact) => <button key={contact.contact_id} className={selected?.contact_id === contact.contact_id ? "selected" : ""} onClick={() => setSelectedId(contact.contact_id)}><span className="workspace-record-identity"><PersonAvatar name={contact.name} /><span><strong>{contact.name}</strong><small>{contact.email}</small></span></span><span><strong>{vendorName(contact.vendor_id)}</strong><small>Vendor contact</small></span><Pill>Active</Pill><ChevronRight size={15} /></button>)}</div></section>
      {selected && <aside className="workspace-panel workspace-detail"><div className="workspace-detail-head"><PersonAvatar name={selected.name} size={44} /><div><p className="workspace-eyebrow">Vendor contact</p><h2>{selected.name}</h2><span>{selected.email}</span></div><Pill>Active</Pill></div><div className="workspace-detail-actions"><a className="workspace-button" href={`mailto:${selected.email}`}><Mail size={14} /> Email contact</a></div><dl className="workspace-definition-grid"><div><dt>Email</dt><dd>{selected.email}</dd></div><div><dt>Vendor</dt><dd>{vendorName(selected.vendor_id)}</dd></div><div><dt>Contact ID</dt><dd>{selected.contact_id}</dd></div><div><dt>Workspace</dt><dd>{selected.workspace_id}</dd></div></dl></aside>}
    </div>}
  </>;
}

export function ChatPage({ notify }: { notify: Notify }) {
  const [message, setMessage] = useState("");
  const preview = () => notify("Chat is not connected yet.");
  return <>
    <WorkspaceIntro eyebrow="Reviewer assistant" title="Chat" />
    <div className="chat-preview-banner" role="status"><Sparkles size={16} /><span><strong>Preview</strong><small>Workspace chat is not connected yet.</small></span></div>
    <div className="chat-workspace"><section className="workspace-panel chat-main"><header><span className="chat-spark"><Sparkles size={17} /></span><span><strong>Vetted review copilot</strong></span><Pill>Preview</Pill></header><div className="chat-messages chat-empty"><Sparkles size={22} /><strong>Choose a question to begin</strong></div><div className="chat-suggestions"><button onClick={() => setMessage("Summarize today's review queue")}>Summarize queue</button><button onClick={() => setMessage("Show missing evidence")}>Show evidence gaps</button><button onClick={() => setMessage("Explain a policy route")}>Explain a route</button></div><div className="chat-composer"><input value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Ask about a review" aria-label="Preview a question for the review copilot" /><DitherAction onClick={preview}>Preview <ArrowRight size={14} /></DitherAction></div></section><aside className="workspace-panel chat-context"><p className="workspace-eyebrow">Scope</p><h2>Read-only</h2><dl><div><dt>Vendor evidence</dt><dd>Case-scoped</dd></div><div><dt>Policy sources</dt><dd>Separate</dd></div><div><dt>Decisions</dt><dd>Reviewer-owned</dd></div></dl></aside></div>
  </>;
}

export function SettingsPage({ notify }: { notify: Notify }) {
  const tabs = ["Evidence policy", "Workspace"] as const;
  const [tab, setTab] = useState<(typeof tabs)[number]>("Evidence policy");
  return <><WorkspaceIntro eyebrow="Administration / Reviewer workspace" title="Settings" /><div className="settings-workspace"><nav className="workspace-panel settings-nav">{tabs.map((item) => <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}><Settings2 size={14} />{item}</button>)}</nav><section className="workspace-panel settings-main"><header><div><p className="workspace-eyebrow">{tab}</p><h2>{tab}</h2></div><Pill>{reviewApi.mode === "live" ? "Live API" : "Fixture"}</Pill></header>{tab === "Evidence policy" && <PolicyCriteriaSettings notify={notify} />}{tab === "Workspace" && <><div className="settings-form"><label>Workspace name<input defaultValue="CSUB reviewer workspace" /></label><label>Workspace description<textarea defaultValue="Human-reviewed vendor management and technology review operations." /></label><label>Default evidence scope<select defaultValue="Vendor and case scoped"><option>Vendor and case scoped</option><option>Campus policy only</option></select></label></div><footer><DitherAction onClick={() => notify("Workspace settings saved locally.")}><Check size={14} />Save changes</DitherAction></footer></>}</section></div></>;
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
  return <><WorkspaceIntro eyebrow="Operating guide" title="Documentation" /><div className="docs-workspace"><nav className="workspace-panel docs-list">{sections.map((item, index) => <button key={item.title} className={selected === index ? "active" : ""} onClick={() => setSelected(index)}><span><item.icon size={16} /></span><span><strong>{item.title}</strong><small>{item.detail}</small></span><ChevronRight size={15} /></button>)}</nav><article className="workspace-panel docs-article"><header><span>[ CSUB / REVIEW GUIDE ]</span><em>0{selected + 1}</em></header><div className="docs-rule" /><p className="workspace-eyebrow">Reviewer guide</p><h2>{section.title}</h2><p className="docs-lede">{section.detail}</p><footer><DitherAction onClick={() => notify("Support request drafted.")}><LifeBuoy size={14} /> Contact operations</DitherAction></footer></article></div></>;
}
