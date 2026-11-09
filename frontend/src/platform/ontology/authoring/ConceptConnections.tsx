import { Link } from "react-router-dom";
import { useServerQuery } from "../../../api/server_queries";
import { bindingApi } from "../bindings/api";

export function ConceptConnections({
  conceptId,
  namespace,
}: {
  conceptId: string;
  namespace: string;
}) {
  const result = useServerQuery(
    ["ontology", "bindings", namespace, conceptId],
    (signal) =>
      bindingApi.bindings(
        undefined,
        undefined,
        { namespace, conceptId },
        signal,
      ),
  );
  const items = result.data?.items ?? null;
  const error = result.error;
  const href = `/admin/semantic-model/ontology?${new URLSearchParams({ view: "connections", namespace, binding_concept: conceptId })}`;
  return (
    <section aria-label="연결된 데이터·용어">
      <h3>연결된 데이터·용어</h3>
      {error ? (
        <p role="alert">{error}</p>
      ) : items === null ? (
        <p>연결 조회 중…</p>
      ) : !items.length ? (
        <p>연결된 데이터·용어가 없습니다.</p>
      ) : (
        items.slice(0, 5).map((item) => (
          <p key={item.binding_id}>
            <Link to={`${href}&binding=${encodeURIComponent(item.binding_id)}`}>
              {item.fully_qualified_name || item.target_locator}
            </Link>{" "}
            ·{" "}
            {
              {
                draft: "검토 대기",
                approved: "승인",
                rejected: "반려",
                deprecated: "중단",
              }[item.status]
            }
          </p>
        ))
      )}
      <Link to={href}>이 개념의 데이터·용어 연결 관리</Link>
    </section>
  );
}
