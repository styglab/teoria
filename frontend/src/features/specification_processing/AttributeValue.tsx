import {
  type ResultRecord as Row,
  resultRows,
  resultLabel,
  requirementValue,
  requirementContext,
} from "./document_results";
function RawValue({
  attribute,
  unit = false,
}: {
  attribute: Row;
  unit?: boolean;
}) {
  return (
    <>
      <span>
        {[
          attribute.operator_raw,
          resultLabel(
            attribute.value_raw ?? attribute.value ?? attribute.raw_value,
          ),
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
