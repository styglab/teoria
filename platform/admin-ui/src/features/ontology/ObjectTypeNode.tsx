import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { CSSProperties } from "react";
import { Box } from "lucide-react";
import type { ObjectNode } from "../../api/admin";

export function ObjectTypeNode({ data, selected }: NodeProps) {
  const object = data as unknown as ObjectNode;
  const domainColor = object.group ? domainColorFor(object.group) : "#7c70ff";
  return (
    <div className={`object-node ${selected ? "selected" : ""} ${object.external ? "external" : ""}`} style={{ "--domain-color": domainColor } as CSSProperties}>
      <Handle className="floating-handle" type="target" position={Position.Left} />
      <div className="node-body">
        <span className="node-icon"><Box size={15} /></span>
        <div className="node-copy">
          <strong>{object.name}</strong>
          <small>{object.id}</small>
          <div className="node-meta">
            {object.group && <span className="node-domain">{object.group}</span>}
            <span>{object.external ? "외부 참조" : `${object.properties.length} properties`}</span>
            {object.primary_key && <code>PK · {object.primary_key}</code>}
          </div>
        </div>
      </div>
      <Handle className="floating-handle" type="source" position={Position.Right} />
    </div>
  );
}

function domainColorFor(domain: string): string {
  const palette = ["#7c70ff", "#36b5a0", "#e59a52", "#5794e8", "#d26b91", "#79a84b", "#9b72d7"];
  const hash = [...domain].reduce((value, character) => ((value * 31) + character.charCodeAt(0)) >>> 0, 0);
  return palette[hash % palette.length];
}
