import { useState } from "react";
import {
  EdgeLabelRenderer,
  getBezierPath,
  Position,
  useInternalNode,
  type EdgeProps,
  type InternalNode,
} from "@xyflow/react";

type FloatingEdgeData = {
  label: string;
  labelsPinned: boolean;
  dimmed: boolean;
};

function boundaryPoint(node: InternalNode, toward: InternalNode) {
  const width = node.measured.width ?? 250;
  const height = node.measured.height ?? 76;
  const otherWidth = toward.measured.width ?? 250;
  const otherHeight = toward.measured.height ?? 76;
  const x = node.internals.positionAbsolute.x + width / 2;
  const y = node.internals.positionAbsolute.y + height / 2;
  const targetX = toward.internals.positionAbsolute.x + otherWidth / 2;
  const targetY = toward.internals.positionAbsolute.y + otherHeight / 2;
  const dx = targetX - x;
  const dy = targetY - y;
  const scale = 1 / Math.sqrt((dx * dx) / ((width / 2) ** 2) + (dy * dy) / ((height / 2) ** 2));
  const normalizedX = dx / width;
  const normalizedY = dy / height;

  return {
    x: x + dx * scale,
    y: y + dy * scale,
    position: Math.abs(normalizedX) > Math.abs(normalizedY)
      ? (dx > 0 ? Position.Right : Position.Left)
      : (dy > 0 ? Position.Bottom : Position.Top),
  };
}

export function FloatingEdge({ id, source, target, markerEnd, selected, data }: EdgeProps) {
  const sourceNode = useInternalNode(source);
  const targetNode = useInternalNode(target);
  const [hovered, setHovered] = useState(false);
  if (!sourceNode || !targetNode) return null;

  const sourcePoint = boundaryPoint(sourceNode, targetNode);
  const targetPoint = boundaryPoint(targetNode, sourceNode);
  const [path, labelX, labelY] = getBezierPath({
    sourceX: sourcePoint.x,
    sourceY: sourcePoint.y,
    sourcePosition: sourcePoint.position,
    targetX: targetPoint.x,
    targetY: targetPoint.y,
    targetPosition: targetPoint.position,
  });
  const edgeData = data as FloatingEdgeData | undefined;
  const dimmed = edgeData?.dimmed ?? false;
  const labelVisible = !dimmed && (hovered || selected || edgeData?.labelsPinned);

  return (
    <>
      <path
        id={id}
        className="react-flow__edge-path floating-edge-path"
        d={path}
        markerEnd={markerEnd}
        style={{ opacity: dimmed ? 0.18 : 1 }}
      />
      <path
        d={path}
        fill="none"
        stroke="transparent"
        strokeWidth={24}
        className="floating-edge-hit-area"
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      />
      {labelVisible && (
        <EdgeLabelRenderer>
          <div
            className="floating-edge-label nodrag nopan"
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)` }}
          >
            {edgeData?.label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
