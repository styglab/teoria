import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useServerQuery } from "../../api/server_queries";
import { modelOperationsApi } from "./api";
import { workflowsApi } from "../workflow_management/api";

export function ServingDeployments() {
  const [params, setParams] = useSearchParams();
  const [refresh, setRefresh] = useState(0);
  const [input, setInput] = useState("{}");
  const [result, setResult] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState<{ action: string; key: string } | null>(null);
  const query = useServerQuery(["mlops", "deployments"], signal =>
    modelOperationsApi.deployments(signal), {refresh, interval: 10000});
  const items = query.data?.items || [];
  const selected = items.find(item => item.deployment_id === params.get("deployment")) || items[0];
  async function operate(action: "stop" | "rollback") {
    if (!selected || busy) return;
    setBusy(true); setError("");
    const identity = `${selected.deployment_id}:${action}`;
    const key = pending?.action === identity ? pending.key : crypto.randomUUID();
    setPending({action: identity, key});
    try {
      const execution = action === "stop" ? {deployment_id: selected.deployment_id} : selected.previous_specification;
      if (!execution) throw Error("이전 배포 설정이 없습니다.");
      const run = await workflowsApi.run(action === "stop" ? "model-stop" : "model-deploy", key, {execution});
      setResult(`실행 요청: ${run.flow_run_id}`); setPending(null); setRefresh(v => v + 1);
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="workspace-page">
    <h1>모델 서빙</h1>
    <p>배포한 모델별 서비스와 상태를 확인합니다. 학습과 신규 배포는 <Link to="/admin/workflows">워크플로우</Link>에서 실행합니다.</p>
    {query.error && <p role="alert">{query.error}</p>}
    {!query.data && !query.error && <p>배포 목록을 불러오는 중…</p>}
    {query.data && !items.length && <p>배포한 모델이 없습니다.</p>}
    <ul>{items.map(item => <li key={item.deployment_id}><button onClick={() => {setParams({deployment: item.deployment_id}); setResult(""); setError("");}}>
      {item.deployment_id} · {item.specification.model_name} v{item.specification.model_version} · {item.health}
    </button></li>)}</ul>
    {selected && <article>
      <h2>{selected.deployment_id}</h2>
      <p>{selected.backend} · {selected.status} · {selected.health}</p>
      <p style={{overflowWrap: "anywhere"}}>{selected.specification.image}</p>
      <p>모델: {selected.specification.model_name} · 버전: {selected.specification.model_version}</p>
      <button disabled={busy || selected.status === "stopped"} onClick={() => void operate("stop")}>서빙 중지</button>{" "}
      <button disabled={busy || !selected.previous_specification} onClick={() => void operate("rollback")}>이전 설정으로 배포</button>
      <form onSubmit={async event => {
        event.preventDefault(); if (busy) return; setBusy(true); setError("");
        try {
          const body = JSON.parse(input);
          const output = await modelOperationsApi.predict(selected.deployment_id, body);
          setResult(JSON.stringify(output, null, 2));
        } catch (reason) {setError((reason as Error).message);} finally {setBusy(false);}
      }}>
        <label>추론 입력(JSON)<textarea value={input} onChange={event => setInput(event.target.value)} rows={6} required /></label>
        <button disabled={busy || selected.status !== "ready"}>추론 요청</button>
      </form>
    </article>}
    {error && <p role="alert">{error}</p>}
    {result && <pre style={{whiteSpace: "pre-wrap", overflowWrap: "anywhere"}}>{result}</pre>}
  </section>;
}
