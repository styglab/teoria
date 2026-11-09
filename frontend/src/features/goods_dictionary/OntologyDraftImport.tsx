import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ontologyApi, type OntologyVersion } from "../../api/ontology";
import { goodsDictionaryApi } from "../../api/goods_dictionary";

export function OntologyDraftImport({ revisionId }: { revisionId: string }) {
  const [namespaces, setNamespaces] = useState<string[]>([]);
  const [namespace, setNamespace] = useState("");
  const [drafts, setDrafts] = useState<OntologyVersion[]>([]);
  const [draft, setDraft] = useState("");
  const [rationale, setRationale] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState<Array<{ legacy_revision_id: string; status: string; reason?: string; stable_key?: string }> | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    ontologyApi.authoredOntologies().then(p => {
      if (active) setNamespaces(p.items.map(o => o.namespace));
    }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    let active = true;
    setDraft(""); setDrafts([]);
    if (namespace) ontologyApi.ontologyVersions(namespace).then(p => {
      if (active) setDrafts(p.items.filter(v => v.status === "draft"));
    }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [namespace]);
  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError("");
    try {
      const response = await goodsDictionaryApi.importLegacy({ ontology_draft_id: draft, revision_ids: [revisionId], rationale });
      setResult(response.items);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <form className="dictionary-form" onSubmit={submit}>
    <h4>온톨로지 Draft로 가져오기</h4>
    <p>선택한 과거 정의와 필요한 소유 유형을 검토할 초안으로 가져옵니다. 게시·표현 연결 승인은 별도입니다.</p>
    <label>대상 온톨로지<select required value={namespace} onChange={e => setNamespace(e.target.value)}>
      <option value="">선택</option>{namespaces.map(n => <option key={n}>{n}</option>)}
    </select></label>
    <label>대상 Draft<select required value={draft} onChange={e => setDraft(e.target.value)}>
      <option value="">선택</option>{drafts.map(v => <option key={v.ontology_version_id} value={v.ontology_version_id}>{v.version}</option>)}
    </select></label>
    {namespace && !drafts.length && <p>온톨로지 화면에서 Draft를 먼저 만드세요.</p>}
    <label>가져오기 근거<textarea required minLength={10} maxLength={4000} value={rationale} onChange={e => setRationale(e.target.value)} /></label>
    <button disabled={busy || !draft || rationale.trim().length < 10}>Draft에 제안</button>
    {error && <p role="alert">{error}</p>}
    {result && <div role="status">{result.map(r => <p key={r.legacy_revision_id}>{r.status === "draft" ? "초안 작성" : "검토 보류"} · {r.stable_key || r.reason}</p>)}<Link to="/admin/semantic-model/ontology">온톨로지에서 검토</Link></div>}
  </form>;
}
