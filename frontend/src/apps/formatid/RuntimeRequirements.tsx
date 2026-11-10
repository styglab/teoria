import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useServerQuery } from "../../api/server_queries";
import { Button } from "../../components/ui/button";
import { processingApi } from "./api";

const scopes: Record<string, string> = {
  per_module: "모듈당",
  per_component: "구성품당",
  system_total: "전체",
  per_socket: "소켓당",
  support_limit: "지원 상한",
};
const kinds: Record<string, string> = {
  requirement: "요구조건",
  capability: "지원 능력",
  reference: "참고 사양",
  recommendation: "권장",
  option: "선택",
};
export function RuntimeRequirements({
  runId,
  documentId,
}: {
  runId: string;
  documentId: string;
}) {
  const [open, setOpen] = useState(false);
  const [params, setParams] = useSearchParams();
  const offset = Math.max(0, Number(params.get("requirements_offset")) || 0);
  const result = useServerQuery(
    ["formatid", "runtime-requirements", runId, documentId, offset],
    (signal) =>
      processingApi.runtimeRequirements(runId, documentId, offset, signal),
    { enabled: open },
  );
  const page = result.data?.objects[0];
  const observations = page?.semantic_observations ?? [];
  const labels = result.data?.outcome?.concepts ?? {};
  const changePage = (value: number) =>
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      if (value) next.set("requirements_offset", String(value));
      else next.delete("requirements_offset");
      return next;
    });
  return (
    <section
      className="operations-section"
      aria-label="게시 의미 기반 요구조건"
    >
      <Button
        variant="outline"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        게시 의미로 조회 {open ? "접기" : "보기"}
      </Button>
      {open && (
        <>
          <p>
            승인된 의미 연결과 처리 기준으로 확정한 요구조건을 조회합니다.
            미연결 관찰은 원래 추출 결과에 남습니다.
          </p>
          {result.loading && <p role="status">요구조건을 조회하고 있습니다…</p>}
          {result.error && (
            <p role="alert">
              {result.error}{" "}
              <Button variant="outline" onClick={result.retry}>
                다시 조회
              </Button>
            </p>
          )}
          {page && (
            <>
              <p>
                조회 기준 {page.properties.view_version} · 전체{" "}
                {page.properties.total}건 · 보류{" "}
                {page.properties.deferred_count}건
              </p>
              <table className="page-table">
                <thead>
                  <tr>
                    <th>속성</th>
                    <th>값</th>
                    <th>범위</th>
                    <th>성격</th>
                    <th>원문 근거</th>
                  </tr>
                </thead>
                <tbody>
                  {observations.map((observation) => (
                    <tr key={observation.observation_id}>
                      <td>
                        {labels[observation.concept_id] ||
                          observation.concept_id}
                      </td>
                      <td>
                        {observation.operator}{" "}
                        {observation.value.decimal ?? observation.value.text}{" "}
                        {observation.value.unit}
                      </td>
                      <td>{scopes[observation.scope] || observation.scope}</td>
                      <td>
                        {kinds[observation.information_kind] ||
                          observation.information_kind}
                      </td>
                      <td>
                        {observation.source.evidence?.node_id ||
                          observation.source.attribute_id}{" "}
                        · 원문 {String(observation.value_raw)}{" "}
                        {observation.unit_raw}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!observations.length && (
                <p>이 조회 범위에 확정된 요구조건이 없습니다.</p>
              )}
              {!!result.data?.outcome?.compositions?.length && (
                <section aria-label="승인된 구성 수량">
                  <h3>구성 수량</h3>
                  <table className="page-table">
                    <thead><tr><th>상위 물품</th><th>구성품</th><th>수량</th><th>포함 조건</th><th>범위·근거</th></tr></thead>
                    <tbody>{result.data.outcome.compositions.map((composition) => (
                      <tr key={composition.composition_id}>
                        <td>{result.data?.outcome?.subjects?.[composition.parent_ref] || composition.parent_ref}</td>
                        <td>{result.data?.outcome?.subjects?.[composition.child_ref] || composition.child_ref}</td>
                        <td>{composition.quantity.operator} {composition.quantity.value} {composition.quantity.unit_raw}</td>
                        <td>{{ required: "필수", optional: "선택", excluded: "제외" }[composition.inclusion_role]}</td>
                        <td>{composition.quantity.scope} · {composition.evidence.map((item) => item.quote).join(" / ")}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </section>
              )}
              <Button
                variant="outline"
                disabled={!offset || result.loading}
                onClick={() => changePage(Math.max(0, offset - 100))}
              >
                이전 요구조건
              </Button>
              <Button
                variant="outline"
                disabled={
                  offset + 100 >= page.properties.total || result.loading
                }
                onClick={() => changePage(offset + 100)}
              >
                다음 요구조건
              </Button>
            </>
          )}
        </>
      )}
    </section>
  );
}
