import type { DocumentResult } from "../../api/specification_processing";
export function authority(result: DocumentResult["result"]) {
  return result?.result_kind === "profile"
    ? "프로파일 표준 적용"
    : result?.result_kind === "extraction_standard"
      ? "추출용 표준 적용"
      : "원문 추출 결과";
}

export function standardSnapshot(document: DocumentResult): string {
  const norm = document.result?.normalization;
  if (!norm) return "원문";
  const ontology = norm.ontology as Record<string, unknown> | undefined;
  const standard = norm.standard_ref as Record<string, unknown> | undefined;
  if (
    document.result?.result_kind === "profile" &&
    ontology?.version_id &&
    ontology?.checksum &&
    norm.package_checksum
  )
    return `ontology:${ontology.version_id}:${ontology.checksum}:${norm.package_checksum}`;
  if (
    document.result?.result_kind === "extraction_standard" &&
    standard?.sha256
  )
    return `draft:${standard.sha256}`;
  return `document:${document.document.catalog_id}`;
}
