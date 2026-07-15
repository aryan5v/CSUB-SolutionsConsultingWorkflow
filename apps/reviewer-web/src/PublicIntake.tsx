import { useEffect, useMemo, useState, type ChangeEvent } from "react";
import {
  ReviewApiError,
  checklistStatusLabel,
  checklistStatusSettled,
  reviewApi,
  reviewStageLabel,
  suppressResolvedQuestions,
  type EvidenceUploadResult,
  type VendorInviteView,
  type VendorQuestion,
  type VendorReviewStatus,
} from "./api";
import "./landing.css";

type IntakeFile = {
  file: File;
  status: "ready" | "saving" | "saved" | "error";
  result?: EvidenceUploadResult;
  error?: string;
};

function PixelLogo() {
  return (
    <svg width={26} height={26} viewBox="0 0 30 30" xmlns="http://www.w3.org/2000/svg" style={{ flexShrink: 0 }} aria-hidden="true">
      <rect x="2" y="2" width="6" height="6" fill="#333333" />
      <rect x="9" y="2" width="6" height="6" fill="#3178C6" />
      <rect x="2" y="9" width="6" height="6" fill="#AAAAAA" />
      <rect x="16" y="9" width="6" height="6" fill="#F7DC6F" />
      <rect x="16" y="16" width="6" height="6" fill="#3178C6" />
      <rect x="23" y="23" width="6" height="6" fill="#333333" />
    </svg>
  );
}

function messageFor(error: unknown): string {
  if (error instanceof ReviewApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "The intake service could not complete this request.";
}

function ReviewStatusCard({ status }: { status: VendorReviewStatus }) {
  return (
    <section className="vp-intake-result vp-case-summary" aria-labelledby="review-status-heading">
      <p className="vp-eyebrow">REVIEW STATUS</p>
      <h2 id="review-status-heading">{reviewStageLabel(status)}</h2>
      {status.outcome && (
        <p role="status">
          {status.outcome === "approved"
            ? "This review passed. The campus team will follow up with any remaining steps."
            : "This review did not pass. Contact your campus reviewer for details about the decision."}
        </p>
      )}
      {status.checklist.length > 0 ? (
        <ul className="vp-file-list">
          {status.checklist.map((item) => (
            <li key={item.requirement_id}>
              <span>
                <strong>{item.expected_evidence.join(", ") || item.requirement_id}</strong>
                <small>{item.requirement_id}</small>
              </span>
              <b className={checklistStatusSettled(item.status) ? "vp-file-saved" : "vp-file-ready"}>
                {checklistStatusLabel(item.status)}
              </b>
            </li>
          ))}
        </ul>
      ) : (
        <p className="vp-field-hint">
          The received/outstanding document checklist appears after intake analysis runs on your submission.
        </p>
      )}
    </section>
  );
}

export default function PublicIntake({ initialToken }: { initialToken: string | null }) {
  const [view, setView] = useState<VendorInviteView | null>(null);
  const [reviewStatus, setReviewStatus] = useState<VendorReviewStatus | null>(null);
  const [questions, setQuestions] = useState<VendorQuestion[]>([]);
  const [files, setFiles] = useState<IntakeFile[]>([]);
  const [trustCenterUrl, setTrustCenterUrl] = useState("");
  const [draftAnswers, setDraftAnswers] = useState<Record<string, string>>({});
  const [savedAnswers, setSavedAnswers] = useState<Record<string, string>>({});
  const [coverage, setCoverage] = useState<Record<string, string>>({});
  const [savedCoverage, setSavedCoverage] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(Boolean(initialToken));
  const [error, setError] = useState(initialToken ? "" : "This invitation link is missing its access token. Ask your reviewer for a new link.");
  const [notice, setNotice] = useState("");
  const [finalized, setFinalized] = useState(false);

  useEffect(() => {
    if (!initialToken) return;
    let active = true;
    const loadStatus = () =>
      reviewApi.getReviewStatus(initialToken).then((status) => {
        if (active) setReviewStatus(status);
      }).catch(() => {
        // Status is additive; the intake form remains usable without it.
      });
    reviewApi.openInvite(initialToken).then((resolved) => {
      if (!active) return;
      setView(resolved);
      setQuestions(resolved.questions);
      setTrustCenterUrl(resolved.submission.trust_center_url ?? "");
      setDraftAnswers(resolved.submission.answers);
      setSavedAnswers(resolved.submission.answers);
      setFinalized(resolved.submission.status === "finalized");
      setLoading(false);
      void loadStatus();
    }).catch(async (reason) => {
      if (!active) return;
      if (reason instanceof ReviewApiError && reason.code === "invite_submitted") {
        // The submission is finalized, so the draft view is gone, but the
        // vendor can still track the review through the status projection.
        try {
          const status = await reviewApi.getReviewStatus(initialToken);
          if (!active) return;
          setReviewStatus(status);
          setFinalized(true);
        } catch (statusReason) {
          if (active) setError(messageFor(statusReason));
        }
        if (active) setLoading(false);
        return;
      }
      setError(messageFor(reason));
      setLoading(false);
    });
    return () => { active = false; };
  }, [initialToken]);

  const unresolved = useMemo(
    () => suppressResolvedQuestions(questions, savedAnswers, savedCoverage),
    [questions, savedAnswers, savedCoverage],
  );
  const savedFiles = files.filter((item) => item.result);
  const simulatedFiles = savedFiles.filter((item) => item.result?.transfer === "simulated");

  const chooseFiles = (event: ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(event.target.files ?? []);
    setFiles((current) => [
      ...current,
      ...selected.map((file): IntakeFile => ({ file, status: "ready" })),
    ]);
    event.target.value = "";
  };

  const refresh = async () => {
    if (!initialToken) return;
    const [resolved, nextQuestions] = await Promise.all([
      reviewApi.resolveInvite(initialToken),
      reviewApi.getVendorQuestions(initialToken),
    ]);
    setView(resolved);
    setQuestions(nextQuestions);
    await reviewApi.getReviewStatus(initialToken).then(setReviewStatus).catch(() => {});
  };

  const saveProgress = async (): Promise<boolean> => {
    if (!initialToken || finalized) return false;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      let currentFiles = [...files];
      for (let index = 0; index < currentFiles.length; index += 1) {
        const item = currentFiles[index];
        if (item.status === "saved") continue;
        currentFiles[index] = { ...item, status: "saving", error: undefined };
        setFiles([...currentFiles]);
        try {
          const result = await reviewApi.uploadEvidence(initialToken, item.file);
          currentFiles[index] = { ...item, status: "saved", result };
        } catch (reason) {
          currentFiles[index] = { ...item, status: "error", error: messageFor(reason) };
          setFiles([...currentFiles]);
          throw reason;
        }
        setFiles([...currentFiles]);
      }

      if (trustCenterUrl.trim()) {
        const parsed = new URL(trustCenterUrl.trim());
        if (parsed.protocol !== "https:") throw new Error("Use an HTTPS trust-center URL.");
        await reviewApi.saveTrustCenter(initialToken, parsed.toString());
      }

      const nextCovered = new Set(savedCoverage);
      for (const [requirementId, artifactId] of Object.entries(coverage)) {
        if (!artifactId || nextCovered.has(requirementId)) continue;
        await reviewApi.addCoverage(initialToken, requirementId, [artifactId]);
        nextCovered.add(requirementId);
      }
      setSavedCoverage(nextCovered);

      const answers = Object.fromEntries(
        Object.entries(draftAnswers).filter(([requirementId, value]) => value.trim() && !nextCovered.has(requirementId) && !savedAnswers[requirementId]?.trim()),
      );
      if (Object.keys(answers).length) await reviewApi.saveAnswers(initialToken, answers);
      setSavedAnswers((current) => ({ ...current, ...answers }));
      await refresh();
      const hasSimulatedTransfer = currentFiles.some((item) => item.result?.transfer === "simulated");
      setNotice(hasSimulatedTransfer
        ? "Draft saved. Evidence metadata reached the intake API, but file bytes stayed in this browser because no presigned upload was available."
        : "Draft saved. You can close this page and resume with the same invitation link.");
      return true;
    } catch (reason) {
      setError(messageFor(reason));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const finalize = async () => {
    if (!initialToken) return;
    const saved = await saveProgress();
    if (!saved) return;
    setBusy(true);
    try {
      const submission = await reviewApi.finalizeVendorSubmission(initialToken);
      setFinalized(submission.status === "finalized");
      setNotice("Submission finalized. Your reviewer can now see the frozen evidence version and continue the review.");
      // The draft view is closed once submitted; the status projection is the
      // surface that remains readable.
      await reviewApi.getReviewStatus(initialToken).then(setReviewStatus).catch(() => {});
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="vp">
      <div className="vp-band" aria-hidden="true" />
      <div className="vp-inner">
        <header className="vp-nav">
          <a className="vp-brand" href="/"><PixelLogo />Vetted</a>
          <div className="vp-nav-actions"><a className="vp-nav-login" href="/">Back to home</a></div>
        </header>

        <main className="vp-intake" id="main-content">
          <div className="vp-header">
            <p className="vp-eyebrow">SECURE VENDOR INTAKE</p>
            <h1 className="vp-h2">Share the evidence you already have.</h1>
            <p className="vp-hero-lead" style={{ marginTop: "0.75rem" }}>
              Start with files and an official trust-center link. We will only show follow-up questions that remain unresolved for this review.
            </p>
          </div>

          <div className={`vp-sim-banner ${reviewApi.mode === "live" ? "vp-live-banner" : ""}`} role="note">
            <span aria-hidden="true">●</span>
            {reviewApi.mode === "fixture"
              ? "Fixture mode is active. Records and transfers on this page are simulated."
              : "Live API mode. Your invitation limits this page to one case; uploaded content is treated as untrusted evidence."}
          </div>

          {loading && <div className="vp-intake-result" role="status">Opening your case-scoped invitation…</div>}
          {!loading && error && !view && !reviewStatus && <div className="vp-intake-result vp-intake-error" role="alert"><strong>We could not open this invitation.</strong><p>{error}</p></div>}

          {!loading && !view && reviewStatus && (
            <div className="vp-intake-stack">
              <section className="vp-intake-result vp-case-summary" aria-labelledby="submitted-heading">
                <p className="vp-eyebrow">CASE {reviewStatus.invite.case_id}</p>
                <h2 id="submitted-heading">{reviewStatus.product.name}</h2>
                <p>{reviewStatus.vendor.name} · Submission {reviewStatus.submission_status}</p>
              </section>
              <ReviewStatusCard status={reviewStatus} />
            </div>
          )}

          {view && (
            <div className="vp-intake-stack">
              <section className="vp-intake-result vp-case-summary" aria-labelledby="case-heading">
                <p className="vp-eyebrow">CASE {view.invite.case_id}</p>
                <h2 id="case-heading">{view.product.name}</h2>
                <p>{view.vendor.name} · Contact: {view.contact.name}</p>
                <dl><div><dt>Invitation</dt><dd>{view.invite.status.replace("_", " ")}</dd></div><div><dt>Expires</dt><dd>{new Date(view.invite.expires_at).toLocaleDateString()}</dd></div><div><dt>Draft version</dt><dd>v{view.submission.version}</dd></div></dl>
              </section>

              {reviewStatus && <ReviewStatusCard status={reviewStatus} />}

              <section className="vp-intake-card" aria-labelledby="evidence-heading">
                <div><p className="vp-eyebrow">01 / FILES FIRST</p><h2 id="evidence-heading">Evidence files</h2><p className="vp-field-hint">Add multiple current documents. File names and metadata are registered before bytes use a presigned upload.</p></div>
                <div className="vp-dropzone">
                  <label className="vp-btn vp-btn-outline" htmlFor="evidence-files">Choose files</label>
                  <input id="evidence-files" className="vp-file-input" type="file" multiple onChange={chooseFiles} disabled={busy || finalized} />
                  <p>HECVAT, SOC 2, penetration test, VPAT/ACR, or other product-specific evidence.</p>
                </div>
                {(files.length > 0 || view.submission.evidence_artifact_ids.length > 0) && <ul className="vp-file-list">
                  {view.submission.evidence_artifact_ids.length > 0 && files.length === 0 && <li><span><strong>{view.submission.evidence_artifact_ids.length} previously saved evidence item(s)</strong><small>Names are not returned in the vendor-safe projection.</small></span><b>Saved</b></li>}
                  {files.map((item, index) => <li key={`${item.file.name}-${index}`}><span><strong>{item.file.name}</strong><small>{Math.ceil(item.file.size / 1024)} KB · {item.file.type || "Unknown file type"}</small>{item.error && <small className="vp-file-error-message" role="alert">{item.error}</small>}</span><b className={`vp-file-${item.status}`}>{item.status}{item.result?.transfer === "simulated" ? " · metadata only" : ""}</b></li>)}
                </ul>}
                {simulatedFiles.length > 0 && <p className="vp-upload-fallback" role="status">No presigned upload was returned for {simulatedFiles.length} file(s). Metadata was saved, but the bytes did not leave this browser.</p>}
              </section>

              <section className="vp-intake-card" aria-labelledby="trust-heading">
                <div><p className="vp-eyebrow">02 / OFFICIAL SOURCE</p><h2 id="trust-heading">Trust center</h2></div>
                <div className="vp-field"><label htmlFor="trust-center">Public HTTPS trust-center URL</label><input id="trust-center" type="url" inputMode="url" value={trustCenterUrl} onChange={(event) => setTrustCenterUrl(event.target.value)} placeholder="https://trust.vendor.example" disabled={busy || finalized} /><span className="vp-field-hint">Saving the link does not browse it or treat vendor claims as campus policy.</span></div>
              </section>

              <section className="vp-intake-card" aria-labelledby="questions-heading">
                <div><p className="vp-eyebrow">03 / WHAT REMAINS</p><h2 id="questions-heading">Unresolved questions</h2><p className="vp-field-hint">Saved answers and cited evidence are removed from this list. The active review profile determines what appears.</p></div>
                {unresolved.length === 0 ? <div className="vp-intake-result"><strong>No unresolved questions are currently returned.</strong><p>Your reviewer will still verify scope, evidence, and any catalog candidate.</p></div> : unresolved.map((question) => (
                  <fieldset className="vp-question" key={question.requirement_id} disabled={busy || finalized}>
                    <legend>{question.question}</legend>
                    <small>{question.requirement_id} · Expected: {question.expected_evidence.join(", ")}</small>
                    <textarea aria-label={`Answer for ${question.requirement_id}`} value={draftAnswers[question.requirement_id] ?? ""} onChange={(event) => setDraftAnswers((current) => ({ ...current, [question.requirement_id]: event.target.value }))} placeholder="Answer only what the uploaded evidence does not cover." />
                    {savedFiles.length > 0 && <label>Or cite a saved file<select value={coverage[question.requirement_id] ?? ""} onChange={(event) => setCoverage((current) => ({ ...current, [question.requirement_id]: event.target.value }))}><option value="">No file selected</option>{savedFiles.map((item) => <option key={item.result!.artifact_id} value={item.result!.artifact_id}>{item.file.name}</option>)}</select></label>}
                  </fieldset>
                ))}
              </section>

              {error && <p className="vp-form-alert" role="alert">{error}</p>}
              {notice && <p className="vp-form-notice" role="status" aria-live="polite">{notice}</p>}
              <div className="vp-intake-actions">
                <button className="vp-btn vp-btn-outline" type="button" onClick={saveProgress} disabled={busy || finalized}>{busy ? "Saving…" : "Save progress"}</button>
                <button className="vp-btn vp-btn-ink" type="button" onClick={finalize} disabled={busy || finalized}>{finalized ? "Submission finalized" : "Finalize submission"}</button>
              </div>
              <p className="vp-field-hint">Finalizing freezes this evidence version. It does not approve the product or make an external system change.</p>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
