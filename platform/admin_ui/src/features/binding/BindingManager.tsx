import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Check, Link2, Plus, ShieldCheck, X } from "lucide-react";
import { adminApi, type BindingValidation, type OntologyConcept, type SemanticBinding } from "../../api/admin";

const statuses = ["all", "draft", "approved", "rejected", "deprecated"] as const;

export function BindingManager() {
  const [items, setItems] = useState<SemanticBinding[]>([]);
  const [concepts, setConcepts] = useState<OntologyConcept[]>([]);
  const [validation, setValidation] = useState<BindingValidation | null>(null);
  const [status, setStatus] = useState<(typeof statuses)[number]>("all");
  const [formOpen, setFormOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ conceptId: "", targetType: "glossary_term", entityId: "", entityType: "glossaryTerm", fqn: "", bindingType: "equivalent_to", authority: "preferred", purpose: "semantic_resolution" });

  const load = useCallback(async () => {
    try {
      const [bindingResponse, conceptResponse, validationResponse] = await Promise.all([
        adminApi.bindings(status === "all" ? undefined : status), adminApi.ontologyConcepts(), adminApi.bindingValidation(),
      ]);
      setItems(bindingResponse.items); setConcepts(conceptResponse.items); setValidation(validationResponse); setError(null);
    } catch (reason) { setError((reason as Error).message); }
  }, [status]);
  useEffect(() => { load(); }, [load]);
  const selected = useMemo(() => concepts.find((item) => item.concept_id === form.conceptId), [concepts, form.conceptId]);

  const review = async (item: SemanticBinding, decision: "approve" | "reject" | "deprecate") => {
    setBusy(item.binding_id);
    try { await adminApi.reviewBinding(item.binding_id, decision); await load(); }
    catch (reason) { setError((reason as Error).message); }
    finally { setBusy(null); }
  };
  const create = async (event: FormEvent) => {
    event.preventDefault(); if (!selected) return;
    setBusy("create");
    try {
      await adminApi.createBinding({
        ontology_ref_type: selected.concept_kind, ontology_concept_id: selected.concept_id,
        target_type: form.targetType, external_entity_id: form.entityId, entity_type: form.entityType,
        fully_qualified_name: form.fqn, binding_type: form.bindingType, purpose: form.purpose,
        authority: form.authority, priority: 100, provenance: { source: "admin_ui", resolution: "review_required" },
      });
      setFormOpen(false); setForm((value) => ({ ...value, entityId: "", fqn: "" })); await load();
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(null); }
  };

  return <div className="binding-manager">
    <div className="binding-toolbar">
      <div className={`binding-health ${validation?.status ?? "unknown"}`}><ShieldCheck size={15} /><strong>{validation?.status ?? "checking"}</strong><span>{validation?.binding_count ?? 0} bindings · {validation?.diagnostic_count ?? 0} issues</span></div>
      <div className="binding-filters">{statuses.map((value) => <button key={value} className={status === value ? "active" : ""} onClick={() => setStatus(value)}>{value}</button>)}</div>
      <button className="binding-add" onClick={() => setFormOpen((value) => !value)}>{formOpen ? <X size={14} /> : <Plus size={14} />}{formOpen ? "닫기" : "Add Binding"}</button>
    </div>
    {formOpen && <form className="binding-form" onSubmit={create}>
      <label>Ontology Concept<select required value={form.conceptId} onChange={(e) => setForm({ ...form, conceptId: e.target.value })}><option value="">선택</option>{concepts.map((item) => <option key={item.concept_id} value={item.concept_id}>{item.stable_key} · {item.concept_kind}</option>)}</select></label>
      <label>Target Type<select value={form.targetType} onChange={(e) => setForm({ ...form, targetType: e.target.value, entityType: e.target.value === "glossary_term" ? "glossaryTerm" : "column" })}><option value="glossary_term">Glossary Term</option><option value="data_asset">Data Asset</option></select></label>
      <label>OpenMetadata Entity ID<input required value={form.entityId} onChange={(e) => setForm({ ...form, entityId: e.target.value })} /></label>
      <label>Fully Qualified Name<input required value={form.fqn} onChange={(e) => setForm({ ...form, fqn: e.target.value })} placeholder="Procurement.ContractAmount" /></label>
      <label>Entity Type<input required value={form.entityType} onChange={(e) => setForm({ ...form, entityType: e.target.value })} /></label>
      <label>Authority<select value={form.authority} onChange={(e) => setForm({ ...form, authority: e.target.value })}><option value="preferred">Preferred</option><option value="authoritative">Authoritative</option><option value="supplemental">Supplemental</option></select></label>
      <button disabled={busy === "create"} type="submit">Draft 생성</button>
    </form>}
    {error && <div className="binding-error">{error}</div>}
    <div className="binding-list">{items.map((item) => <article key={item.binding_id}>
      <header><div className="binding-icon"><Link2 size={15} /></div><div><small>{item.ontology_concept_kind}</small><h3>{item.ontology_stable_key}</h3></div><b className={`binding-status ${item.status}`}>{item.status}</b></header>
      <div className="binding-direction"><span>↕</span><div><strong>{item.fully_qualified_name}</strong><small>OpenMetadata · {item.entity_type} · {item.target_type}</small></div></div>
      <dl><div><dt>Binding</dt><dd>{item.binding_type}</dd></div><div><dt>Authority</dt><dd>{item.authority}</dd></div><div><dt>Purpose</dt><dd>{item.purpose ?? "—"}</dd></div><div><dt>Verified</dt><dd>{item.last_verified_at ? item.last_verified_at.slice(0, 10) : "not verified"}</dd></div></dl>
      <footer><small>created by {item.created_by}{item.approved_by ? ` · approved by ${item.approved_by}` : ""}</small><div>{item.status === "draft" && <><button disabled={busy === item.binding_id} onClick={() => review(item, "reject")}>Reject</button><button className="primary" disabled={busy === item.binding_id} onClick={() => review(item, "approve")}><Check size={13} />Approve</button></>}{item.status === "approved" && <button disabled={busy === item.binding_id} onClick={() => review(item, "deprecate")}>Deprecate</button>}</div></footer>
    </article>)}</div>
    {!error && !items.length && <div className="metadata-empty"><Link2 size={25} /><h3>해당 상태의 Binding이 없습니다.</h3></div>}
  </div>;
}
