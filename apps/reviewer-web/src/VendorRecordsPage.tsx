import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Check, Copy, FileCheck2, Link2, Plus, RefreshCw, Send, ShieldCheck, UserCheck } from "lucide-react";
import { DitherButton } from "@/components/dither-kit/button";
import {
  ReviewApiError,
  requiresReviewerConfirmation,
  reviewApi,
  type CatalogCandidate,
  type InviteProjection,
  type ReviewProfileVersion,
  type ReviewRun,
  type VendorContact,
  type VendorProduct,
  type VendorRecord,
} from "./api";
import "./workspace.css";

type Notify = (message: string) => void;

function errorMessage(error: unknown): string {
  return error instanceof ReviewApiError || error instanceof Error ? error.message : "The vendor API request failed.";
}

function statusLabel(status: InviteProjection["status"]): string {
  return status.replace("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function FieldButton({ children, onClick, disabled = false }: { children: React.ReactNode; onClick: () => void; disabled?: boolean }) {
  return <DitherButton color="orange" variant="solid" bloom="low" className="workspace-dither-button" onClick={onClick} disabled={disabled}>{children}</DitherButton>;
}

export function VendorRecordsPage({ notify }: { notify: Notify }) {
  const [vendors, setVendors] = useState<VendorRecord[]>([]);
  const [products, setProducts] = useState<VendorProduct[]>([]);
  const [contacts, setContacts] = useState<VendorContact[]>([]);
  const [selectedVendorId, setSelectedVendorId] = useState("");
  const [selectedProductId, setSelectedProductId] = useState("");
  const [selectedContactId, setSelectedContactId] = useState("");
  const [caseId, setCaseId] = useState("");
  const [invites, setInvites] = useState<InviteProjection[]>([]);
  const [profiles, setProfiles] = useState<ReviewProfileVersion[]>([]);
  const [runs, setRuns] = useState<ReviewRun[]>([]);
  const [candidates, setCandidates] = useState<CatalogCandidate[]>([]);
  const [confirmedCandidates, setConfirmedCandidates] = useState<Set<string>>(new Set());
  const [inviteUrl, setInviteUrl] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const selectedVendor = vendors.find((item) => item.vendor_id === selectedVendorId);
  const selectedProduct = products.find((item) => item.product_id === selectedProductId);
  const selectedContact = contacts.find((item) => item.contact_id === selectedContactId);
  const latestInvite = invites[0];
  const nextStep = !caseId ? "Create the case" : !latestInvite ? "Issue the vendor invitation" : latestInvite.status === "submitted" ? "Start a versioned review run" : latestInvite.status === "opened" || latestInvite.status === "in_progress" ? "Wait for the vendor submission" : "Track invitation delivery";
  const evidenceCoverage = latestInvite?.status === "submitted" ? "Submission received; coverage is checked in the review" : "No finalized vendor submission";

  const refreshRelationships = async (vendorId: string) => {
    const [nextProducts, nextContacts] = await Promise.all([reviewApi.listProducts(vendorId), reviewApi.listContacts(vendorId)]);
    setProducts(nextProducts);
    setContacts(nextContacts);
    setSelectedProductId((current) => nextProducts.some((item) => item.product_id === current) ? current : nextProducts[0]?.product_id ?? "");
    setSelectedContactId((current) => nextContacts.some((item) => item.contact_id === current) ? current : nextContacts[0]?.contact_id ?? "");
  };

  useEffect(() => {
    let active = true;
    Promise.all([reviewApi.listVendors(), reviewApi.listProfiles()]).then(async ([nextVendors, nextProfiles]) => {
      if (!active) return;
      setVendors(nextVendors);
      setProfiles(nextProfiles);
      const vendorId = nextVendors[0]?.vendor_id ?? "";
      setSelectedVendorId(vendorId);
      if (vendorId) await refreshRelationships(vendorId);
      if (active) setLoading(false);
    }).catch((reason) => {
      if (!active) return;
      setError(errorMessage(reason));
      setLoading(false);
    });
    return () => { active = false; };
  }, []);

  const chooseVendor = async (vendorId: string) => {
    setSelectedVendorId(vendorId);
    setCaseId("");
    setInvites([]);
    setCandidates([]);
    setInviteUrl("");
    setError("");
    try { await refreshRelationships(vendorId); } catch (reason) { setError(errorMessage(reason)); }
  };

  const createVendor = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true); setError("");
    try {
      const created = await reviewApi.createVendor({ name: String(data.get("name") || "").trim(), official_domain: String(data.get("domain") || "").trim() || undefined });
      setVendors((current) => [...current, created]);
      setSelectedVendorId(created.vendor_id);
      setProducts([]); setContacts([]); setSelectedProductId(""); setSelectedContactId("");
      form.reset();
      notify(`${created.name} created through the ${reviewApi.mode} vendor API.`);
    } catch (reason) { setError(errorMessage(reason)); } finally { setBusy(false); }
  };

  const createProduct = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedVendorId) return;
    const form = event.currentTarget;
    const name = String(new FormData(form).get("name") || "").trim();
    setBusy(true); setError("");
    try {
      const created = await reviewApi.createProduct({ vendor_id: selectedVendorId, name });
      setProducts((current) => [...current, created]); setSelectedProductId(created.product_id); form.reset();
      notify(`${created.name} added to the selected vendor.`);
    } catch (reason) { setError(errorMessage(reason)); } finally { setBusy(false); }
  };

  const createContact = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedVendorId) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true); setError("");
    try {
      const created = await reviewApi.createContact({ vendor_id: selectedVendorId, name: String(data.get("name") || "").trim(), email: String(data.get("email") || "").trim() });
      setContacts((current) => [...current, created]); setSelectedContactId(created.contact_id); form.reset();
      notify(`${created.name} added as a vendor contact.`);
    } catch (reason) { setError(errorMessage(reason)); } finally { setBusy(false); }
  };

  const createCase = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedVendor || !selectedProduct) return;
    const data = new FormData(event.currentTarget);
    setBusy(true); setError("");
    try {
      const created = await reviewApi.createCase({
        product_name: selectedProduct.name,
        vendor_name: selectedVendor.name,
        requester: { name: String(data.get("requester_name") || "").trim(), email: String(data.get("requester_email") || "").trim(), department: String(data.get("department") || "").trim() || undefined },
        use_case: String(data.get("use_case") || "").trim(),
        expected_users: Number(data.get("expected_users") || 0),
        platform: [String(data.get("platform") || "web")],
        data_classification: String(data.get("data_classification") || "unknown") as "public" | "internal" | "confidential" | "level1" | "level2" | "unknown",
        estimated_cost_usd: Number(data.get("cost") || 0),
        integrations: String(data.get("integrations") || "").split(",").map((item) => item.trim()).filter(Boolean),
        uses_sso: data.get("uses_sso") === "on",
        uses_ai: data.get("uses_ai") === "on",
        accessibility_context: String(data.get("accessibility_context") || "").trim() || undefined,
        official_domain: selectedVendor.official_domain ?? undefined,
        classroom_or_public_use: data.get("public_use") === "on",
      });
      setCaseId(created.case_id);
      const catalog = await reviewApi.searchCatalog(selectedProduct.name, selectedVendor.name);
      setCandidates(catalog.matches);
      setInvites([]); setRuns([]); setInviteUrl("");
      notify(`${created.case_id} created. Catalog candidates are matches, not blanket approval.`);
    } catch (reason) { setError(errorMessage(reason)); } finally { setBusy(false); }
  };

  const issueInvite = async () => {
    if (!caseId || !selectedContactId) return;
    setBusy(true); setError("");
    try {
      const issued = await reviewApi.issueInvite(caseId, selectedContactId);
      setInvites((current) => [issued.invite, ...current]);
      const url = `${window.location.origin}/intake#token=${encodeURIComponent(issued.token)}`;
      setInviteUrl(url);
      notify("Tracked invitation issued. Its opaque token is shown once in the URL fragment.");
    } catch (reason) { setError(errorMessage(reason)); } finally { setBusy(false); }
  };

  const refreshCase = async () => {
    if (!caseId) return;
    setBusy(true); setError("");
    try {
      const [nextInvites, nextRuns] = await Promise.all([reviewApi.listInvites(caseId), reviewApi.listReviewRuns(caseId)]);
      setInvites([...nextInvites].reverse()); setRuns(nextRuns);
      notify("Case tracking refreshed from the API.");
    } catch (reason) { setError(errorMessage(reason)); } finally { setBusy(false); }
  };

  const confirmCandidate = async (candidate: CatalogCandidate) => {
    setBusy(true); setError("");
    try {
      await reviewApi.confirmCatalogMatch(candidate.record_id, candidate.match_method, "alex.reviewer@example.edu");
      setConfirmedCandidates((current) => new Set(current).add(candidate.record_id));
      notify("Candidate match confirmed by Alex Reviewer. No approval was granted.");
    } catch (reason) { setError(errorMessage(reason)); } finally { setBusy(false); }
  };

  const copyInvite = async () => {
    await navigator.clipboard.writeText(inviteUrl);
    notify("Invitation link copied. Share it only with the selected vendor contact.");
  };

  const activeProfiles = useMemo(() => profiles.filter((item) => item.status === "activated"), [profiles]);

  return <>
    <header className="workspace-intro"><div><p className="workspace-eyebrow">Companies / API records</p><h1>Vendor intake records</h1><p>Create or select the vendor, product, contact, case, and tracked invitation. Catalog membership remains a lookup result, never blanket approval.</p></div><div className={`record-mode record-mode-${reviewApi.mode}`}><i />{reviewApi.mode === "fixture" ? "Fixture mode · simulated records" : "Live API mode"}</div></header>
    {error && <div className="record-api-error" role="alert"><strong>API request failed.</strong><span>{error}</span><small>{reviewApi.mode === "live" ? "Live failures are not replaced with fixture data." : "This failure occurred in the explicit fixture adapter."}</small></div>}
    {loading ? <section className="workspace-panel record-loading" role="status">Loading vendor records…</section> : <div className="vendor-record-layout">
      <section className="workspace-panel vendor-record-builder" aria-label="Vendor intake golden path">
        <div className="record-step"><span aria-hidden="true">01</span><div><h2>Vendor</h2><label>Select vendor<select value={selectedVendorId} onChange={(event) => chooseVendor(event.target.value)} aria-label="Select vendor"><option value="">Select a vendor</option>{vendors.map((vendor) => <option key={vendor.vendor_id} value={vendor.vendor_id}>{vendor.name}</option>)}</select></label><form className="record-inline-form" onSubmit={createVendor}><input name="name" required placeholder="New vendor name" aria-label="New vendor name" /><input name="domain" placeholder="official.example" aria-label="Official domain" /><button type="submit" disabled={busy}><Plus size={13} aria-hidden="true" />Create</button></form></div></div>
        <div className="record-step"><span aria-hidden="true">02</span><div><h2>Product</h2><label>Select product<select value={selectedProductId} onChange={(event) => setSelectedProductId(event.target.value)} disabled={!selectedVendorId} aria-label="Select product"><option value="">Select a product</option>{products.map((product) => <option key={product.product_id} value={product.product_id}>{product.name}</option>)}</select></label><form className="record-inline-form" onSubmit={createProduct}><input name="name" required placeholder="New product name" aria-label="New product name" disabled={!selectedVendorId} /><button type="submit" disabled={busy || !selectedVendorId}><Plus size={13} aria-hidden="true" />Create</button></form></div></div>
        <div className="record-step"><span aria-hidden="true">03</span><div><h2>Vendor contact</h2><label>Select contact<select value={selectedContactId} onChange={(event) => setSelectedContactId(event.target.value)} disabled={!selectedVendorId} aria-label="Select contact"><option value="">Select a contact</option>{contacts.map((contact) => <option key={contact.contact_id} value={contact.contact_id}>{contact.name} · {contact.email}</option>)}</select></label><form className="record-inline-form record-contact-form" onSubmit={createContact}><input name="name" required placeholder="Contact name" aria-label="Contact name" disabled={!selectedVendorId} /><input name="email" type="email" required placeholder="contact@vendor.example" aria-label="Contact email" disabled={!selectedVendorId} /><button type="submit" disabled={busy || !selectedVendorId}><Plus size={13} aria-hidden="true" />Create</button></form></div></div>
        <div className="record-step"><span>04</span><div><h2>Product-scoped case</h2><form className="record-case-form" onSubmit={createCase}><label>Requester name<input name="requester_name" required placeholder="Sample Requester" /></label><label>Requester email<input name="requester_email" type="email" required placeholder="requester@example.edu" /></label><label>Department<input name="department" placeholder="Department" /></label><label>Expected users<input name="expected_users" type="number" min="0" defaultValue="1" required /></label><label>Platform<select name="platform" defaultValue="web"><option value="web">Web</option><option value="windows">Windows</option><option value="macos">macOS</option><option value="mobile">Mobile</option></select></label><label>Data classification<select name="data_classification" defaultValue="unknown"><option value="unknown">Unknown · escalate</option><option value="public">Public</option><option value="internal">Internal</option><option value="confidential">Confidential</option><option value="level1">Level 1</option><option value="level2">Level 2</option></select></label><label>Estimated cost<input name="cost" type="number" min="0" step="0.01" defaultValue="0" /></label><label>Integrations<input name="integrations" placeholder="Canvas, Microsoft 365" /></label><label className="record-wide">Intended use<textarea name="use_case" required placeholder="Describe the product-scoped use case." /></label><label className="record-wide">Accessibility context<textarea name="accessibility_context" placeholder="Classroom, public, assistive technology, or VPAT context" /></label><div className="record-checks"><label><input name="uses_sso" type="checkbox" />Uses SSO</label><label><input name="uses_ai" type="checkbox" />Uses AI</label><label><input name="public_use" type="checkbox" />Classroom or public use</label></div><button className="workspace-dither-button" type="submit" disabled={busy || !selectedVendor || !selectedProduct}><FileCheck2 size={14} />Create case</button></form></div></div>
        <div className="record-step"><span>05</span><div><h2>Tracked invitation</h2><p>{caseId ? `${caseId} is linked to ${selectedProduct?.name}.` : "Create a case before issuing an invitation."}</p><div className="record-action-row"><FieldButton onClick={issueInvite} disabled={busy || !caseId || !selectedContactId}><Send size={14} />Issue invitation</FieldButton><button className="workspace-button" onClick={refreshCase} disabled={busy || !caseId}><RefreshCw size={14} />Refresh tracking</button></div>{inviteUrl && <div className="invite-once"><Link2 size={15} /><span><strong>One-time invitation URL</strong><code>{inviteUrl}</code></span><button onClick={copyInvite} aria-label="Copy invitation URL"><Copy size={14} /></button></div>}</div></div>
      </section>

      <aside className="vendor-record-sidebar">
        <section className="workspace-panel record-summary"><p className="workspace-eyebrow">Current record</p><h2>{selectedProduct?.name ?? "Select a product"}</h2><p>{selectedVendor?.name ?? "No vendor selected"}</p><dl><div><dt>Contact</dt><dd>{selectedContact?.name ?? "Not selected"}</dd></div><div><dt>Internal owner</dt><dd>Alex Reviewer</dd></div><div><dt>Case</dt><dd>{caseId || "Not created"}</dd></div><div><dt>Next step</dt><dd>{nextStep}</dd></div><div><dt>Evidence coverage</dt><dd>{evidenceCoverage}</dd></div><div><dt>Profile versions</dt><dd>{activeProfiles.length ? activeProfiles.map((item) => `${item.profile_key} v${item.version}`).join(", ") : "No active profile returned"}</dd></div><div><dt>Review runs</dt><dd>{runs.length ? runs.map((item) => `v${item.run_version}`).join(", ") : "No run yet"}</dd></div></dl></section>
        <section className="workspace-panel record-tracking"><div className="record-panel-heading"><div><p className="workspace-eyebrow">Invitation tracking</p><h2>Created → opened → submitted</h2></div><ShieldCheck size={17} /></div>{invites.length ? <ol>{invites.map((invite) => <li key={invite.invite_id}><span className={`invite-state invite-state-${invite.status}`}><i /></span><div><strong>{statusLabel(invite.status)}</strong><small>Issued {new Date(invite.issued_at).toLocaleString()}</small>{invite.opened_at && <small>Opened {new Date(invite.opened_at).toLocaleString()}</small>}{invite.submitted_at && <small>Submitted {new Date(invite.submitted_at).toLocaleString()}</small>}</div></li>)}</ol> : <p>No invitation has been issued for this case.</p>}</section>
        <section className="workspace-panel record-candidates"><p className="workspace-eyebrow">Catalog candidates</p><h2>Match, then verify</h2><p className="catalog-boundary">A catalog row may support review. It is not blanket approval for this product, use case, or evidence version.</p>{candidates.length ? candidates.map((candidate) => { const needsConfirmation = requiresReviewerConfirmation(candidate); const confirmed = confirmedCandidates.has(candidate.record_id); return <article key={candidate.record_id}><div><strong>{candidate.canonical_name}</strong><small>{candidate.match_method.replace("_", " + ")} · Row {candidate.source_row} · {Math.round(candidate.score * 100)}%</small></div>{needsConfirmation ? <button onClick={() => confirmCandidate(candidate)} disabled={busy || confirmed}>{confirmed ? <Check size={13} /> : <UserCheck size={13} />}{confirmed ? "Confirmed" : "Confirm match"}</button> : <span>Structured match</span>}</article>; }) : <p>Create a case to search the catalog.</p>}</section>
      </aside>
    </div>}
  </>;
}
