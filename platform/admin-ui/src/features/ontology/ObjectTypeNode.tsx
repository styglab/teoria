import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Box } from "lucide-react";
import type { ObjectNode } from "../../api/admin";

export function ObjectTypeNode({ data, selected }: NodeProps) {
  const object = data as unknown as ObjectNode;
  return (
    <div className={`object-node ${selected ? "selected" : ""} ${object.external ? "external" : ""}`}>
      <Handle className="floating-handle" type="target" position={Position.Left} />
      <div className="node-body">
        <span className="node-icon"><Box size={15} /></span>
        <div className="node-copy">
          <strong>{object.name}</strong>
          <small>{object.id}</small>
          <div className="node-meta">
            <span>{object.external ? "외부 참조" : `${object.properties.length} properties`}</span>
            {object.primary_key && <code>PK · {object.primary_key}</code>}
          </div>
        </div>
      </div>
      <Handle className="floating-handle" type="source" position={Position.Right} />
    </div>
  );
}
