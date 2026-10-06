import { CheckCircle2, FileWarning } from "lucide-react";

import type { ValidationReport } from "../../api/admin";

type Props = {
  report: ValidationReport | null;
};

export function ValidationView({ report }: Props) {
  if (!report) return <div className="loading-state">Registry 검증 결과를 불러오고 있습니다…</div>;

  if (report.status === "valid") {
    return (
      <div className="validation-empty">
        <CheckCircle2 size={36} />
        <strong>Registry가 유효합니다</strong>
        <p>Source, Mapping, Ontology와 Capability 계약에서 진단이 발견되지 않았습니다.</p>
      </div>
    );
  }

  return (
    <div className="validation-list">
      {report.diagnostics.map((diagnostic, index) => (
        <article key={`${diagnostic.code}-${diagnostic.path}-${diagnostic.location ?? index}`}>
          <FileWarning size={17} />
          <div>
            <header><strong>{diagnostic.code}</strong><span className={diagnostic.severity}>{diagnostic.severity}</span></header>
            <p>{diagnostic.message}</p>
            <code>{diagnostic.path}{diagnostic.location ? ` · ${diagnostic.location}` : ""}</code>
          </div>
        </article>
      ))}
    </div>
  );
}
