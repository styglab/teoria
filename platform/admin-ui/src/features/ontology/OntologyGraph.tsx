import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  Panel,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
  type ReactFlowInstance,
} from "@xyflow/react";
import type { LinkEdge, ObjectNode, OntologyGraph as GraphData } from "../../api/admin";
import { FloatingEdge } from "./FloatingEdge";
import { ObjectTypeNode } from "./ObjectTypeNode";

const nodeTypes = { objectType: ObjectTypeNode };
const edgeTypes = { floating: FloatingEdge };
const NODE_WIDTH = 250;
const NODE_HEIGHT = 76;

type LayoutMode = "organic" | "radial" | "hierarchy";

function graphNodes(graph: GraphData, positions: Map<string, { x: number; y: number }>): Node[] {
  return graph.nodes.map((object) => ({
    id: object.id,
    type: "objectType",
    position: positions.get(object.id) ?? { x: 0, y: 0 },
    data: object,
  }));
}

async function organicNodes(graph: GraphData): Promise<Node[]> {
  const { default: ELK } = await import("elkjs/lib/elk.bundled.js");
  const layout = await new ELK().layout({
    id: "root",
    layoutOptions: {
      "elk.algorithm": "stress",
      "elk.stress.desiredEdgeLength": "330",
      "elk.spacing.nodeNode": "100",
      "elk.aspectRatio": "1.35",
    },
    children: graph.nodes.map((object) => ({ id: object.id, width: NODE_WIDTH, height: NODE_HEIGHT })),
    edges: graph.edges.map((edge) => ({ id: edge.id, sources: [edge.source], targets: [edge.target] })),
  });
  return graphNodes(graph, new Map(layout.children?.map((node) => [node.id, { x: node.x ?? 0, y: node.y ?? 0 }])));
}

async function hierarchyNodes(graph: GraphData): Promise<Node[]> {
  const { default: ELK } = await import("elkjs/lib/elk.bundled.js");
  const layout = await new ELK().layout({
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      "elk.spacing.nodeNode": "70",
      "elk.layered.spacing.nodeNodeBetweenLayers": "120",
      "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
    },
    children: graph.nodes.map((object) => ({ id: object.id, width: NODE_WIDTH, height: NODE_HEIGHT })),
    edges: graph.edges.map((edge) => ({ id: edge.id, sources: [edge.source], targets: [edge.target] })),
  });
  return graphNodes(graph, new Map(layout.children?.map((node) => [node.id, { x: node.x ?? 0, y: node.y ?? 0 }])));
}

function radialNodes(graph: GraphData, requestedCenter: string | null): Node[] {
  const degree = new Map(graph.nodes.map((node) => [node.id, 0]));
  const neighbors = new Map(graph.nodes.map((node) => [node.id, new Set<string>()]));
  graph.edges.forEach((edge) => {
    neighbors.get(edge.source)?.add(edge.target);
    neighbors.get(edge.target)?.add(edge.source);
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  });
  const center = requestedCenter && degree.has(requestedCenter)
    ? requestedCenter
    : [...degree.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
  if (!center) return [];

  const levels = new Map<string, number>([[center, 0]]);
  const queue = [center];
  while (queue.length) {
    const current = queue.shift()!;
    neighbors.get(current)?.forEach((neighbor) => {
      if (!levels.has(neighbor)) {
        levels.set(neighbor, (levels.get(current) ?? 0) + 1);
        queue.push(neighbor);
      }
    });
  }
  const outerLevel = Math.max(0, ...levels.values()) + 1;
  graph.nodes.forEach((node) => { if (!levels.has(node.id)) levels.set(node.id, outerLevel); });
  const rings = new Map<number, string[]>();
  levels.forEach((level, id) => rings.set(level, [...(rings.get(level) ?? []), id]));
  const positions = new Map<string, { x: number; y: number }>();
  rings.forEach((ids, level) => ids.forEach((id, index) => {
    const radius = level * 360;
    const angle = (index / ids.length) * Math.PI * 2 - Math.PI / 2;
    positions.set(id, { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius });
  }));
  return graphNodes(graph, positions);
}

async function layoutNodes(graph: GraphData, mode: LayoutMode, center: string | null) {
  if (mode === "radial") return radialNodes(graph, center);
  return mode === "organic" ? organicNodes(graph) : hierarchyNodes(graph);
}

export function OntologyGraph({ graph, onSelect }: { graph: GraphData; onSelect: (item: ObjectNode | LinkEdge | null) => void }) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [mode, setMode] = useState<LayoutMode>("organic");
  const [labelsPinned, setLabelsPinned] = useState(true);
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(null);
  const [layoutVersion, setLayoutVersion] = useState(0);
  const [layoutPending, setLayoutPending] = useState(true);
  const flowInstance = useRef<ReactFlowInstance<Node, Edge> | null>(null);
  const radialCenter = mode === "radial" ? focusedNodeId : null;

  const connectedEdgeIds = useMemo(() => new Set(focusedNodeId
    ? graph.edges.filter((edge) => edge.source === focusedNodeId || edge.target === focusedNodeId).map((edge) => edge.id)
    : []), [focusedNodeId, graph.edges]);
  const connectedNodeIds = useMemo(() => new Set(focusedNodeId
    ? graph.edges.flatMap((edge) => edge.source === focusedNodeId
      ? [edge.source, edge.target]
      : edge.target === focusedNodeId ? [edge.source, edge.target] : [])
    : []), [focusedNodeId, graph.edges]);

  useEffect(() => {
    let cancelled = false;
    setLayoutPending(true);
    layoutNodes(graph, mode, radialCenter).then((nextNodes) => {
      if (cancelled) return;
      setNodes(nextNodes);
      setLayoutPending(false);
      requestAnimationFrame(() => flowInstance.current?.fitView({ padding: 0.2, duration: 350 }));
    });
    return () => { cancelled = true; };
  }, [graph, layoutVersion, mode, radialCenter, setNodes]);

  useEffect(() => {
    setEdges(graph.edges.map((edge) => {
      const dimmed = focusedNodeId !== null && !connectedEdgeIds.has(edge.id);
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        type: "floating",
        markerEnd: { type: MarkerType.ArrowClosed, color: dimmed ? "#394158" : "#7c8cff" },
        data: { ...edge, label: edge.name, labelsPinned, dimmed },
      };
    }));
  }, [connectedEdgeIds, focusedNodeId, graph.edges, labelsPinned, setEdges]);

  useEffect(() => {
    setNodes((current) => current.map((node) => ({
      ...node,
      style: { opacity: focusedNodeId && !connectedNodeIds.has(node.id) ? 0.2 : 1 },
    })));
  }, [connectedNodeIds, focusedNodeId, setNodes]);

  const clearFocus = useCallback(() => {
    setFocusedNodeId(null);
    onSelect(null);
  }, [onSelect]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      fitView
      fitViewOptions={{ padding: 0.2 }}
      minZoom={0.15}
      maxZoom={1.8}
      nodesDraggable
      nodesConnectable={false}
      elementsSelectable
      onInit={(instance) => { flowInstance.current = instance; }}
      onNodeClick={(_, node) => {
        setFocusedNodeId(node.id);
        onSelect(node.data as unknown as ObjectNode);
      }}
      onEdgeClick={(_, edge) => {
        setFocusedNodeId(null);
        onSelect(edge.data as unknown as LinkEdge);
      }}
      onPaneClick={clearFocus}
    >
      <Background color="#283149" gap={22} size={1} />
      <MiniMap nodeColor={(node) => (node.data.external ? "#596078" : "#746cff")} maskColor="rgba(7,9,18,.68)" />
      <Controls showInteractive={false} />
      <Panel position="top-right" className="graph-toolbar">
        <button className={mode === "organic" ? "active" : ""} onClick={() => setMode("organic")}>Organic</button>
        <button className={mode === "radial" ? "active" : ""} onClick={() => setMode("radial")}>Radial</button>
        <button className={mode === "hierarchy" ? "active" : ""} onClick={() => setMode("hierarchy")}>Hierarchy</button>
        <button onClick={() => setLayoutVersion((version) => version + 1)} disabled={layoutPending}>{layoutPending ? "정렬 중…" : "자동 정렬"}</button>
        <button className={labelsPinned ? "active" : ""} onClick={() => setLabelsPinned((value) => !value)}>링크명 고정</button>
      </Panel>
      <div className="graph-help">링크명은 기본으로 표시됩니다 · 노드를 선택하면 연결 관계만 강조</div>
    </ReactFlow>
  );
}
