import { useEffect, useMemo, useRef, useState } from "react";
import { Building2, Package, Search, ShieldCheck } from "lucide-react";
import { ReviewApiError, reviewApi, type CatalogListItem } from "./api";
import "./workspace.css";

type Notify = (message: string) => void;

function errorMessage(error: unknown): string {
  return error instanceof ReviewApiError || error instanceof Error ? error.message : "The catalog request failed.";
}

function flagTone(flag: string | null | undefined): string {
  const value = (flag ?? "").toLowerCase();
  if (/support|licens|enterprise|site|institution/.test(value)) return "positive";
  if (/condition|limited|depart|pending/.test(value)) return "warning";
  if (/no |none|unsupported|expired/.test(value)) return "critical";
  return "info";
}

const PAGE_SIZE = 20;

export function CatalogPage({ notify }: { notify: Notify }) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<CatalogListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const notified = useRef(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    const handle = window.setTimeout(() => {
      reviewApi.listCatalog(query, PAGE_SIZE, offset).then((response) => {
        if (!active) return;
        setItems(response.items);
        setTotal(response.total);
        setLoading(false);
        if (!notified.current) {
          notified.current = true;
          notify("Catalog rows are lookup results. Membership is not blanket approval.");
        }
      }).catch((reason) => {
        if (!active) return;
        setError(errorMessage(reason));
        setItems([]);
        setLoading(false);
      });
    }, 200);
    return () => { active = false; window.clearTimeout(handle); };
  }, [query, offset, notify]);

  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const rangeLabel = useMemo(() => {
    if (total === 0) return "0 records";
    const start = offset + 1;
    const end = Math.min(offset + items.length, total);
    return `${start}-${end} of ${total} records`;
  }, [offset, items.length, total]);

  return <>
    <header className="workspace-intro">
      <div>
        <p className="workspace-eyebrow">Records / Approved-software catalog</p>
        <h1>Software catalog</h1>
        <p>Search the approved-software export. Each row shows the vendor, product, support, and license fields as recorded. A catalog row can support a review; it is not blanket approval for a product, use case, or evidence version.</p>
      </div>
      <div className={`record-mode record-mode-${reviewApi.mode}`}><i />{reviewApi.mode === "fixture" ? "Fixture mode · simulated records" : "Live API mode"}</div>
    </header>

    <section className="workspace-panel catalog-panel">
      <div className="catalog-toolbar">
        <label className="search-control">
          <Search size={15} />
          <span className="sr-only">Search the software catalog</span>
          <input
            value={query}
            onChange={(event) => { setOffset(0); setQuery(event.target.value); }}
            placeholder="Search by product or vendor…"
            type="search"
          />
        </label>
        <span className="catalog-range">{rangeLabel}</span>
      </div>

      {error && <div className="record-api-error" role="alert"><strong>Catalog request failed.</strong><span>{error}</span><small>{reviewApi.mode === "live" ? "Live failures are not replaced with fixture data." : "This failure occurred in the explicit fixture adapter."}</small></div>}

      <div className="catalog-columns"><span>Product</span><span>Vendor</span><span>Platform / audience</span><span>Support</span><span>License</span><span>Source</span></div>

      <div className="catalog-list" aria-label="Software catalog results">
        {loading && <div className="catalog-empty" role="status">Loading catalog records…</div>}
        {!loading && items.length === 0 && !error && <div className="catalog-empty"><Search size={18} /><strong>No catalog records match this search.</strong><span>Try a different product or vendor name.</span></div>}
        {!loading && items.map((item) => (
          <article className="catalog-row" key={item.record_id}>
            <span className="catalog-product">
              <span className="catalog-glyph" aria-hidden="true"><Package size={15} /></span>
              <span><strong>{item.canonical_name}</strong>{item.product && item.product !== item.canonical_name ? <small>{item.product}</small> : null}</span>
            </span>
            <span className="catalog-vendor"><Building2 size={13} aria-hidden="true" />{item.vendor}</span>
            <span className="catalog-meta">{[item.platform, item.audience].filter(Boolean).join(" · ") || "Not recorded"}</span>
            <span><span className={`status status-${flagTone(item.support_flag)}`}><span aria-hidden="true" className="status-mark" />{item.support_flag ?? "Not recorded"}</span></span>
            <span><span className={`status status-${flagTone(item.license_flag)}`}><span aria-hidden="true" className="status-mark" />{item.license_flag ?? "Not recorded"}</span></span>
            <span className="catalog-source">{item.source_row ? `Row ${item.source_row}` : "-"}</span>
          </article>
        ))}
      </div>

      <div className="catalog-footer">
        <div className="catalog-boundary"><ShieldCheck size={15} /><span>Catalog membership is a lookup result, never blanket approval. Fuzzy and semantic matches still need a reviewer to confirm them.</span></div>
        <div className="catalog-pagination">
          <button type="button" onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} disabled={loading || offset === 0}>Previous</button>
          <span>Page {page} of {pageCount}</span>
          <button type="button" onClick={() => setOffset(offset + PAGE_SIZE)} disabled={loading || page >= pageCount}>Next</button>
        </div>
      </div>
    </section>
  </>;
}
