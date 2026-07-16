import { useEffect, useState } from "react";
import { AlertTriangle, Check, ShieldCheck } from "lucide-react";
import { reviewApi, ReviewApiError, type PolicyCriteria, type PolicyCriteriaInput } from "./api";

type Notify = (message: string) => void;

// A threshold field accepts a positive integer or an empty value meaning "no
// confirmed rule" (TBD), which downstream validation treats as manual review.
type FormState = {
  pentest_max_age_days: string;
  pci_attestation_max_age_days: string;
  evidence_expiry_days: string;
  coi_required_coverages: string;
  provisional: boolean;
};

function toForm(criteria: PolicyCriteria): FormState {
  const num = (value: number | null) => (value === null ? "" : String(value));
  return {
    pentest_max_age_days: num(criteria.pentest_max_age_days),
    pci_attestation_max_age_days: num(criteria.pci_attestation_max_age_days),
    evidence_expiry_days: num(criteria.evidence_expiry_days),
    coi_required_coverages: criteria.coi_required_coverages.join(", "),
    provisional: criteria.provisional,
  };
}

// Empty field => null (TBD). Any other value must be a positive integer.
function parseThreshold(raw: string, label: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const value = Number(trimmed);
  if (!Number.isInteger(value) || value < 1) {
    throw new Error(`${label} must be a positive whole number of days, or left blank for “not set”.`);
  }
  return value;
}

const THRESHOLDS: Array<{ key: keyof FormState; label: string; help: string }> = [
  {
    key: "pentest_max_age_days",
    label: "Penetration test max age (days)",
    help: "Older reports return for review.",
  },
  {
    key: "pci_attestation_max_age_days",
    label: "PCI attestation currency (days)",
    help: "Leave blank to review each PCI attestation manually.",
  },
  {
    key: "evidence_expiry_days",
    label: "Evidence expiry / re-review window (days)",
    help: "Older evidence returns for review.",
  },
];

export function PolicyCriteriaSettings({ notify }: { notify: Notify }) {
  const [criteria, setCriteria] = useState<PolicyCriteria | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [loadError, setLoadError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    reviewApi
      .getPolicyCriteria()
      .then((value) => {
        if (!active) return;
        setCriteria(value);
        setForm(toForm(value));
      })
      .catch((error) => {
        if (active) setLoadError(error instanceof ReviewApiError ? error.message : "Policy criteria are unavailable.");
      });
    return () => {
      active = false;
    };
  }, []);

  if (loadError) return <p className="record-context-error" role="alert">{loadError}</p>;
  if (!form || !criteria) return <p className="settings-loading">Loading evidence policy criteria…</p>;

  const update = (key: keyof FormState, value: string | boolean) =>
    setForm((current) => (current ? { ...current, [key]: value } : current));

  const save = async () => {
    setSaveError("");
    let input: PolicyCriteriaInput;
    try {
      input = {
        pentest_max_age_days: parseThreshold(form.pentest_max_age_days, "Penetration test max age"),
        pci_attestation_max_age_days: parseThreshold(form.pci_attestation_max_age_days, "PCI attestation currency"),
        evidence_expiry_days: parseThreshold(form.evidence_expiry_days, "Evidence expiry window"),
        coi_required_coverages: form.coi_required_coverages
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        provisional: form.provisional,
      };
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "Invalid criteria.");
      return;
    }
    setSaving(true);
    try {
      const saved = await reviewApi.updatePolicyCriteria(input);
      setCriteria(saved);
      setForm(toForm(saved));
      notify(`Evidence policy criteria saved (version ${saved.version}).`);
    } catch (error) {
      setSaveError(error instanceof ReviewApiError ? error.message : "The criteria could not be saved.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="policy-criteria">
      {criteria.provisional && (
        <p className="policy-provisional" role="note">
          <AlertTriangle size={15} aria-hidden="true" />
          <span>
            <strong>Provisional values.</strong> Leave a threshold blank to require manual review.
          </span>
        </p>
      )}
      <div className="settings-form">
        {THRESHOLDS.map((field) => (
          <label key={field.key}>
            {field.label}
            <input
              type="number"
              min={1}
              inputMode="numeric"
              placeholder="Not set (manual review)"
              value={form[field.key] as string}
              onChange={(event) => update(field.key, event.target.value)}
            />
            <small>{field.help}</small>
          </label>
        ))}
        <label>
          Required COI coverages
          <input
            type="text"
            value={form.coi_required_coverages}
            onChange={(event) => update("coi_required_coverages", event.target.value)}
            placeholder="cyber, privacy"
          />
          <small>Comma-separated coverage names.</small>
        </label>
        <label className="policy-provisional-toggle">
          <span>
            <strong>Mark values provisional</strong>
            <small>Turn off after CSUB confirms these values.</small>
          </span>
          <input
            type="checkbox"
            checked={form.provisional}
            onChange={(event) => update("provisional", event.target.checked)}
          />
        </label>
      </div>
      {saveError && <p className="record-context-error" role="alert">{saveError}</p>}
      <footer className="policy-criteria-footer">
        <span>
          <ShieldCheck size={14} aria-hidden="true" />
          {criteria.version === 0
            ? "Provisional defaults"
            : `Version ${criteria.version} · ${criteria.updated_by || "reviewer"}`}
        </span>
        <button type="button" className="policy-save" onClick={save} disabled={saving}>
          <Check size={14} aria-hidden="true" /> {saving ? "Saving…" : "Save criteria"}
        </button>
      </footer>
    </div>
  );
}
