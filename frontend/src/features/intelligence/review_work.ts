import { suggestionApi } from "../../api/suggestions";
import { bindingApi } from "../../api/binding";
import { ontologyApi } from "../../api/ontology";

export type ReviewWorkItem = {
  id: string;
  kind: "suggestion" | "binding" | "ontology";
  title: string;
  description: string;
  state: string;
  created: string;
  href: string;
};
export async function loadReviewWork() {
  const items: ReviewWorkItem[] = [];
  const errors: string[] = [];
  let limited = false;
  const results = await Promise.allSettled([
    suggestionApi.suggestionPage("pending"),
    bindingApi.bindings("draft"),
    ontologyApi.authoredOntologies(),
  ]);
  const [suggestions, bindings, ontologies] = results;
  if (suggestions.status === "fulfilled") {
    limited = !!suggestions.value.next_cursor;
    items.push(
      ...suggestions.value.items.map((item) => ({
        id: item.suggestion_id,
        kind: "suggestion" as const,
        title:
          item.proposed_value.column_name ||
          item.target_ref.split("/").at(-1) ||
          item.target_ref,
        description: item.rationale || "변경 전후와 근거를 확인하세요.",
        state: "제안 검토 대기",
        created: item.created_at,
        href: `/admin/changes/review?suggestion=${encodeURIComponent(item.suggestion_id)}`,
      })),
    );
  } else errors.push("변경 제안");
  if (bindings.status === "fulfilled")
    items.push(
      ...bindings.value.items.map((item) => ({
        id: item.binding_id,
        kind: "binding" as const,
        title: item.ontology_stable_key,
        description: item.fully_qualified_name,
        state: "연결 초안 검토",
        created: item.created_at,
        href: `/admin/semantic-model/bindings?binding=${encodeURIComponent(item.binding_id)}`,
      })),
    );
  else errors.push("의미 연결");
  if (ontologies.status === "fulfilled") {
    const namespaces = ontologies.value.items;
    if (namespaces.length > 20) limited = true;
    let position = 0;
    await Promise.all(
      Array.from({ length: Math.min(4, namespaces.length) }, async () => {
        while (position < Math.min(20, namespaces.length)) {
          const item = namespaces[position++];
          try {
            const versions = await ontologyApi.ontologyVersions(item.namespace);
            items.push(
              ...versions.items
                .filter((v) => ["in_review", "approved"].includes(v.status))
                .map((v) => ({
                  id: v.ontology_version_id,
                  kind: "ontology" as const,
                  title: `${item.name} v${v.version}`,
                  description:
                    v.status === "approved"
                      ? "승인된 초안의 게시 영향을 확인하세요."
                      : "변경 내용·검증 결과·연결 영향을 확인하세요.",
                  state:
                    v.status === "approved" ? "게시 대기" : "온톨로지 검토",
                  created: v.created_at,
                  href: `/admin/semantic-model/ontology?version=${encodeURIComponent(v.ontology_version_id)}&view=review`,
                })),
            );
          } catch {
            errors.push(`${item.name} 버전`);
          }
        }
      }),
    );
  } else errors.push("온톨로지");
  items.sort((a, b) => b.created.localeCompare(a.created));
  return { items, errors, limited };
}
