import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { bindingApi, type SemanticBinding } from "../../api/binding";

export function ConceptConnections({
  conceptId,
  namespace,
}: {
  conceptId: string;
  namespace: string;
}) {
  const [items, setItems] = useState<SemanticBinding[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    bindingApi
      .bindings(undefined, undefined, { namespace, conceptId })
      .then((page) => {
        if (active) setItems(page.items);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [conceptId, namespace]);
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
