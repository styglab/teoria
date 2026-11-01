import {
  type ResultRecord as Row,
  resultRows,
  resultLabel,
  requirementValue,
  requirementContext,
} from "./document_results";

/** A reading label is not an assertion that these words appeared in the original. */
export function attributeName(attribute: Row): string {
  const names: Record<string, string> = {
    quantity: "수량", model: "모델", manufacturer: "제조사",
    function: "기능", purpose: "용도",
  };
  return resultLabel(attribute.property_raw || attribute.property_name || attribute.property_label || attribute.name ||
    names[String(attribute.property_key)] || "속성명 확인 필요");
}

function RawValue({
  attribute,
  unit = false,
}: {
  attribute: Row;
  unit?: boolean;
}) {
  const value = resultLabel(attribute.value_raw ?? attribute.value ?? attribute.raw_value);
  const operator = String(attribute.operator_raw || "");
  const included = operator && (value.startsWith(operator) ||
    (attribute.operator === "range" && value.includes(operator)));
  return (
    <>
      <span>
        {[
          included ? "" : operator,
          value,
        ]
          .filter(Boolean)
          .map(resultLabel)
          .join(" ")}
      </span>
      {unit && attribute.unit_raw ? (
        <span> {resultLabel(attribute.unit_raw)}</span>
      ) : null}
      {Array.isArray(attribute.qualifiers_raw) &&
        attribute.qualifiers_raw.length > 0 && (
          <p className="operations-note">
            조건: {attribute.qualifiers_raw.map(resultLabel).join(" · ")}
          </p>
        )}
    </>
  );
}
export function AttributeValue({
  attribute,
  mapping,
  standard,
}: {
  attribute: Row;
  mapping: Row | undefined;
  standard: boolean;
}) {
  if (!standard) return <RawValue attribute={attribute} />;
  const facts = resultRows(mapping?.facts);
  return (
    <>
      {facts.length ? (
        facts.map((fact, index) => (
          <div key={index} className="analysis-mapped-fact">
            <p className="analysis-normalized-value">
              {requirementValue(fact)}
            </p>
            <p className="operations-note">{requirementContext(fact)}</p>
            {Array.isArray(fact.qualifiers_raw) &&
              fact.qualifiers_raw.length > 0 && (
                <p className="operations-note">
                  조건: {fact.qualifiers_raw.map(resultLabel).join(" · ")}
                </p>
              )}
            <details
              className="analysis-internal-key"
              onClick={(event) => event.stopPropagation()}
            >
              <summary>표준 식별자</summary>
              <code>
                {resultLabel(
                  fact.property_label ||
                    fact.property_stable_key ||
                    fact.property_id ||
                    fact.property_concept_id,
                )}
              </code>
            </details>
          </div>
        ))
      ) : (
        <>
          <RawValue attribute={attribute} unit />
          <p className="operations-note">원문 값 · 표준 적용 값 미제공</p>
        </>
      )}
      {facts.length > 0 && (
        <details
          className="analysis-internal-key"
          onClick={(event) => event.stopPropagation()}
        >
          <summary>원문 값·단위</summary>
          <RawValue attribute={attribute} unit />
        </details>
      )}
    </>
  );
}
