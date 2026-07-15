import { useState, type FormEvent } from "react";
import "./landing.css";

/*
 * Public, file-first vendor intake route (`/intake`).
 *
 * This is a FRONTEND boundary only. The real intake and case-creation contract
 * is owned by backend issue #19 and is not yet available. The types below are a
 * local placeholder for that boundary so the public route can own its own shape
 * without editing any shared `packages/contracts` schema. Replace
 * `submitVendorIntake` with the generated client once issue #19 lands.
 *
 * Every path here is simulated. No request leaves the browser, and nothing is
 * approved or written to any external system.
 */

export type VendorIntakeAttachment = {
  name: string;
  sizeBytes: number;
  kind: "policy" | "security" | "accessibility" | "other";
};

export type VendorIntakeSubmission = {
  productName: string;
  vendorName: string;
  requesterEmail: string;
  useCase: string;
  handlesStudentData: boolean;
  attachments: VendorIntakeAttachment[];
};

export type VendorIntakeReceipt = {
  simulated: true;
  referenceId: string;
  received: VendorIntakeSubmission;
};

/** Simulated boundary. Swap for the issue #19 client without changing callers. */
async function submitVendorIntake(input: VendorIntakeSubmission): Promise<VendorIntakeReceipt> {
  const stamp = new Date();
  const referenceId = `SIM-${stamp.getFullYear()}${String(stamp.getMonth() + 1).padStart(2, "0")}${String(stamp.getDate()).padStart(2, "0")}-${String(stamp.getHours()).padStart(2, "0")}${String(stamp.getMinutes()).padStart(2, "0")}`;
  return { simulated: true, referenceId, received: input };
}

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

export default function PublicIntake() {
  const [receipt, setReceipt] = useState<VendorIntakeReceipt | null>(null);
  const [error, setError] = useState<string>("");

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    const form = event.currentTarget;
    const data = new FormData(form);
    const productName = String(data.get("productName") ?? "").trim();
    const vendorName = String(data.get("vendorName") ?? "").trim();
    const requesterEmail = String(data.get("requesterEmail") ?? "").trim();
    const useCase = String(data.get("useCase") ?? "").trim();

    if (!productName || !vendorName || !requesterEmail) {
      setError("Add the product name, the vendor, and a contact email so a reviewer can follow up.");
      return;
    }

    const fileList = (form.elements.namedItem("attachments") as HTMLInputElement | null)?.files;
    const attachments: VendorIntakeAttachment[] = fileList
      ? Array.from(fileList).map((file) => ({ name: file.name, sizeBytes: file.size, kind: "other" }))
      : [];

    const submission: VendorIntakeSubmission = {
      productName,
      vendorName,
      requesterEmail,
      useCase,
      handlesStudentData: data.get("handlesStudentData") === "on",
      attachments,
    };

    setReceipt(await submitVendorIntake(submission));
  };

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
            <a className="vp-nav-login" href="/">
              Back to home
            </a>
            <a className="vp-btn vp-btn-ink vp-btn-sm" href="/app">
              Open the workspace
            </a>
          </div>
        </header>

        <section className="vp-intake">
          <div className="vp-header">
            <p className="vp-eyebrow">VENDOR INTAKE</p>
            <h2 className="vp-h2">Tell us what you want reviewed.</h2>
            <p className="vp-hero-lead" style={{ marginTop: "0.75rem" }}>
              Start with the product and any documents you have. The evidence you attach shapes which follow-up
              questions a reviewer asks. You do not need every file to begin.
            </p>
          </div>

          <div className="vp-sim-banner" role="note">
            <span aria-hidden="true">●</span>
            Demo intake. Nothing is submitted to a live system, and no file leaves your browser.
          </div>

          {receipt ? (
            <div className="vp-intake-result" role="status" aria-live="polite">
              <p style={{ marginTop: 0 }}>
                <strong>Simulated intake recorded.</strong> Reference {receipt.referenceId}.
              </p>
              <p>
                A reviewer would look up the approved-software export, run the deterministic policy rules, and open a
                case for {receipt.received.productName} by {receipt.received.vendorName}. This prototype does not create
                a real case or notify anyone.
              </p>
              <p style={{ marginBottom: 0 }}>
                Attachments named: {receipt.received.attachments.length > 0 ? receipt.received.attachments.map((a) => a.name).join(", ") : "none"}.
              </p>
            </div>
          ) : (
            <form className="vp-intake-card" onSubmit={onSubmit} noValidate>
              <div className="vp-field">
                <label htmlFor="productName">Product name</label>
                <input id="productName" name="productName" type="text" autoComplete="off" required />
              </div>
              <div className="vp-field">
                <label htmlFor="vendorName">Vendor</label>
                <input id="vendorName" name="vendorName" type="text" autoComplete="organization" required />
              </div>
              <div className="vp-field">
                <label htmlFor="requesterEmail">Your campus email</label>
                <input id="requesterEmail" name="requesterEmail" type="email" autoComplete="email" required />
                <span className="vp-field-hint">A reviewer uses this to ask follow-up questions.</span>
              </div>
              <div className="vp-field">
                <label htmlFor="useCase">What will it be used for?</label>
                <textarea id="useCase" name="useCase" />
              </div>
              <div className="vp-field">
                <label htmlFor="attachments">Evidence files</label>
                <div className="vp-dropzone">
                  <input id="attachments" name="attachments" type="file" multiple />
                  <p style={{ margin: "0.5rem 0 0" }}>Policy documents, HECVAT, SOC 2, VPAT, or anything you already have.</p>
                </div>
              </div>
              <div className="vp-field" style={{ flexDirection: "row", alignItems: "center", gap: "0.6rem" }}>
                <input id="handlesStudentData" name="handlesStudentData" type="checkbox" style={{ width: 16, height: 16 }} />
                <label htmlFor="handlesStudentData" style={{ fontWeight: 500 }}>
                  This product will handle student or staff data
                </label>
              </div>
              {error && (
                <p role="alert" style={{ color: "#b43b42", fontSize: 13, margin: 0 }}>
                  {error}
                </p>
              )}
              <button className="vp-btn vp-btn-ink" type="submit">
                Submit for review
              </button>
            </form>
          )}
        </section>
      </div>
    </div>
  );
}
