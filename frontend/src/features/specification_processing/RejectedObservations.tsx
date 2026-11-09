import { useState } from "react";
import { processingApi } from "../../api/specification_processing";
import { type ResultRecord as Row, resultRows as rows } from "./document_results";
import { AttributeValue, attributeName } from "./AttributeValue";

const validationReasons: Record<string, string> = {
  source_numeric_literal_mismatch: "추출한 숫자가 원문의 완전한 숫자와 다릅니다",
  source_numeric_evidence_span_mismatch: "숫자의 원문 위치가 일치하지 않습니다",
  source_literal_mismatch: "추출값·단위가 원문과 일치하지 않습니다",
  source_qualifier_mismatch: "조건이 원문과 일치하지 않습니다",
  invalid_attribute_subject: "속성의 대상이 확인되지 않습니다",
  invalid_source_reference: "원문 위치를 찾을 수 없습니다",
  duplicate_attribute_id: "중복된 속성 식별자입니다",
};
export const validationReason = (code: unknown) => validationReasons[String(code)] || "추출 결과의 근거를 검토해야 합니다";

export function RejectedObservations({ document, runId, onSource, sourceText }: {
  document: Row; runId?: string; onSource: (a: Row) => void; sourceText: (a: Row) => string;
}) {
  const rejected = rows(document.quarantined_attributes);
  const [busy, setBusy] = useState("");
  const [results, setResults] = useState<Record<string, string>>({});
  if (!rejected.length) return null;
  return <section className="validation-rejections" aria-label="원문 검증 보류 항목">
    <h3>원문 검증 보류 {rejected.length}건</h3>
    <p>이 항목은 표준 적용에서 제외됐습니다. 추출값과 원문을 대조하세요.</p>
    {rejected.map((row, index) => {
      const a = row.attribute as Row; const issue = row.issue as Row; const id = String(a.id);
      return <article key={`${id}-${index}`}>
        <strong>{attributeName(a)}</strong>
        <AttributeValue attribute={a} mapping={undefined} standard={false} />
        <p>{validationReason(issue.code)}</p>
        <blockquote>{sourceText(a) || "원문 위치를 확인할 수 없습니다."}</blockquote>
        <button type="button" onClick={() => onSource(a)}>원문 위치 확인</button>
        {runId && <button type="button" disabled={!!busy} onClick={async () => {
          setBusy(id);
          try {
            const result = await processingApi.reproduceValidation(runId, String(document.document_id), id);
            setResults(old => ({ ...old, [id]: result.verdict === "valid" ? "현재 검사에서는 통과했습니다. 재처리하면 새 결과를 만들 수 있습니다." : validationReason(result.code) }));
          } catch { setResults(old => ({ ...old, [id]: "검사를 재현하지 못했습니다. 잠시 후 다시 시도하세요." })); }
          finally { setBusy(""); }
        }}>{busy === id ? "검사 중…" : "현재 기준으로 다시 검사"}</button>}
        {results[id] && <p role="status">{results[id]}</p>}
      </article>;
    })}
  </section>;
}
