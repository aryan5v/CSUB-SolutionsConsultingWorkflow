import {
  addEdge,
  applyNodeChanges,
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Connection,
  type Edge,
  type Node,
  type NodeChange,
  type NodeProps,
} from "@xyflow/react";
import type { LucideIcon } from "lucide-react";
import { ChevronRight, Plus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import "@xyflow/react/dist/style.css";

/**
 * Ported from Twenty's workflow diagram composition:
 * WorkflowDiagramCanvasBase, WorkflowDiagramStepNodeEditableContent, and
 * WorkflowDiagramConnector. The data/actions are CSUB-specific and local.
 */
export type WorkflowCanvasNode = {
  id: string;
  title: string;
  detail: string;
  kind: "trigger" | "action" | "condition" | "human";
  group: string;
  icon: LucideIcon;
  tone: string;
};

type WorkflowNodeData = { node: WorkflowCanvasNode };
type WorkflowFlowNode = Node<WorkflowNodeData, "workflow-step">;

const nodeTypes = { "workflow-step": WorkflowStepNode };

function WorkflowStepNode({ data, selected }: NodeProps<WorkflowFlowNode>) {
  const NodeIcon = data.node.icon;
  const label = data.node.kind === "trigger" ? "Trigger" : data.node.kind === "human" ? "Human input" : data.node.kind === "condition" ? "Flow" : "Action";

  return <div className={`twenty-workflow-node twenty-workflow-node-${data.node.kind} ${selected ? "twenty-workflow-node-selected" : ""}`}>
    <Handle className="twenty-workflow-target-handle" type="target" position={Position.Top} />
    <div className={`twenty-workflow-node-icon builder-tone-${data.node.tone}`}><NodeIcon size={16} /></div>
    <div className="twenty-workflow-node-copy"><span>{label}</span><strong>{data.node.title}</strong><small>{data.node.detail}</small></div>
    <ChevronRight className="twenty-workflow-node-arrow" size={15} />
    <Handle className="twenty-workflow-source-handle" type="source" position={Position.Bottom} />
  </div>;
}

function buildEdges(nodes: WorkflowCanvasNode[]): Edge[] {
  return nodes.slice(1).map((node, index) => ({
    id: `twenty-edge-${nodes[index].id}-${node.id}`,
    source: nodes[index].id,
    target: node.id,
    type: "smoothstep",
    markerEnd: { type: MarkerType.ArrowClosed, color: "#a0a0a0" },
  }));
}

export function WorkflowCanvas({ nodes, selectedNodeId, onSelectNode, onAddNode }: { nodes: WorkflowCanvasNode[]; selectedNodeId?: string; onSelectNode: (id: string) => void; onAddNode: () => void }) {
  const defaultNodes = useMemo<WorkflowFlowNode[]>(() => nodes.map((node, index) => ({ id: node.id, type: "workflow-step", position: { x: 235, y: 50 + index * 145 }, data: { node }, draggable: true })), [nodes]);
  const [flowNodes, setFlowNodes] = useState<WorkflowFlowNode[]>(defaultNodes);
  const [flowEdges, setFlowEdges] = useState<Edge[]>(() => buildEdges(nodes));

  useEffect(() => {
    setFlowNodes((current) => nodes.map((node, index) => {
      const previous = current.find((item) => item.id === node.id);
      return { id: node.id, type: "workflow-step", position: previous?.position ?? { x: 235, y: 50 + index * 145 }, data: { node }, draggable: true, selected: node.id === selectedNodeId };
    }));
    setFlowEdges((current) => {
      const defaultEdges = buildEdges(nodes);
      const customEdges = current.filter((edge) => !defaultEdges.some((defaultEdge) => defaultEdge.source === edge.source && defaultEdge.target === edge.target));
      return [...defaultEdges, ...customEdges];
    });
  }, [nodes, selectedNodeId]);

  const handleNodesChange = (changes: NodeChange<WorkflowFlowNode>[]) => setFlowNodes((current) => applyNodeChanges(changes, current) as WorkflowFlowNode[]);
  const handleConnect = (connection: Connection) => setFlowEdges((current) => addEdge({ ...connection, type: "smoothstep", markerEnd: { type: MarkerType.ArrowClosed, color: "#a0a0a0" } }, current));

  return <div className="twenty-workflow-canvas" data-testid="twenty-workflow-canvas"><ReactFlow nodes={flowNodes} edges={flowEdges} nodeTypes={nodeTypes} onNodesChange={handleNodesChange} onConnect={handleConnect} onNodeClick={(_, node) => onSelectNode(node.id)} onPaneClick={() => onSelectNode("")} nodesConnectable nodesDraggable fitView fitViewOptions={{ padding: 0.22, minZoom: 0.65, maxZoom: 1.1 }} minZoom={0.45} maxZoom={1.4} proOptions={{ hideAttribution: true }} defaultEdgeOptions={{ selectable: true }}><Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#d7d7d7" /><Controls showInteractive={false} /></ReactFlow><button className="twenty-workflow-add-step" onClick={onAddNode}><Plus size={14} /> Add a step</button></div>;
}
