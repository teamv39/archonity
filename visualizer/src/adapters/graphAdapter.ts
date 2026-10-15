import type { Node, Edge } from '@xyflow/react';
import type {
  CanonicalGraph,
  CanonicalNode,
  CanonicalEdge,
  SourceType,
  RelationType,
  ColorMode,
  BlastRadiusResult,
  DagDirection,
} from '../types/graph';

export interface FilterOptions {
  confidenceThreshold: number;
  activeSources: Record<SourceType, boolean>;
  allowedRelations: Set<RelationType>;
  searchQuery: string;
  colorMode: ColorMode;
  showTransitive?: boolean;
}

export interface NodeData extends Record<string, unknown> {
  rawNode: CanonicalNode;
  blastState: 'normal' | 'root' | 'upstream' | 'downstream' | 'dimmed';
  isMatchedSearch: boolean;
  direction?: DagDirection;
}

export interface EdgeData extends Record<string, unknown> {
  rawEdge: CanonicalEdge;
  colorMode: ColorMode;
  blastState: 'normal' | 'affected' | 'dimmed';
}

export const NODE_DIMENSIONS: Record<string, { width: number; height: number }> = {
  SERVICE: { width: 300, height: 130 },
  DATABASE: { width: 250, height: 110 },
  MESSAGE_QUEUE: { width: 250, height: 100 },
};

/**
 * Расчет Blast Radius для выбранного узла графа
 */
export function calculateBlastRadius(
  graph: CanonicalGraph,
  selectedNodeId: string | null
): BlastRadiusResult | null {
  if (!selectedNodeId) return null;

  const upstreamNodeIds = new Set<string>();
  const downstreamNodeIds = new Set<string>();
  const transitiveNodeIds = new Set<string>();
  const affectedEdgeIds = new Set<string>();

  // Прямые и косвенные исходящие (downstream: кого вызывает selectedNode)
  const forwardQueue: Array<{ id: string; depth: number }> = [{ id: selectedNodeId, depth: 0 }];
  const visitedForward = new Set<string>([selectedNodeId]);

  let maxDepth = 0;

  while (forwardQueue.length > 0) {
    const current = forwardQueue.shift()!;
    if (current.depth > maxDepth) maxDepth = current.depth;

    for (const edge of graph.edges) {
      if (edge.source === current.id) {
        affectedEdgeIds.add(edge.id);
        if (!visitedForward.has(edge.target)) {
          visitedForward.add(edge.target);
          if (current.depth === 0) {
            downstreamNodeIds.add(edge.target);
          } else {
            transitiveNodeIds.add(edge.target);
          }
          forwardQueue.push({ id: edge.target, depth: current.depth + 1 });
        }
      }
    }
  }

  // Прямые и косвенные входящие (upstream: кто вызывает selectedNode)
  const backwardQueue: Array<{ id: string; depth: number }> = [{ id: selectedNodeId, depth: 0 }];
  const visitedBackward = new Set<string>([selectedNodeId]);

  while (backwardQueue.length > 0) {
    const current = backwardQueue.shift()!;
    for (const edge of graph.edges) {
      if (edge.target === current.id) {
        affectedEdgeIds.add(edge.id);
        if (!visitedBackward.has(edge.source)) {
          visitedBackward.add(edge.source);
          if (current.depth === 0) {
            upstreamNodeIds.add(edge.source);
          } else {
            transitiveNodeIds.add(edge.source);
          }
          backwardQueue.push({ id: edge.source, depth: current.depth + 1 });
        }
      }
    }
  }

  const allAffectedNodeIds = new Set<string>([
    selectedNodeId,
    ...upstreamNodeIds,
    ...downstreamNodeIds,
    ...transitiveNodeIds,
  ]);

  return {
    rootNodeId: selectedNodeId,
    upstreamNodeIds,
    downstreamNodeIds,
    transitiveNodeIds,
    allAffectedNodeIds,
    affectedEdgeIds,
    depth: maxDepth,
  };
}

/**
 * Фильтрация ребер графа по критериям (источники, порог уверенности ML, протокол)
 */
export function filterGraph(
  graph: CanonicalGraph,
  filters: FilterOptions
): { filteredNodes: CanonicalNode[]; filteredEdges: CanonicalEdge[] } {
  const filteredEdges = graph.edges.filter((edge) => {
    // Источник доказательства (AST_EXACT, CONFIG, ML_PREDICTED, LLM_JUDGE_VERIFIED, TRANSITIVE)
    if (!filters.activeSources[edge.sourceType]) return false;

    // Тип отношения / протокола (REST_HTTP, DATABASE, MESSAGE_QUEUE, TRANSITIVE)
    if (!filters.allowedRelations.has(edge.relationType)) return false;

    // Порог уверенности: применяется к ML и LLM гипотезам
    if (edge.sourceType === 'ML_PREDICTED' || edge.sourceType === 'LLM_JUDGE_VERIFIED') {
      if (edge.confidence < filters.confidenceThreshold) return false;
    }

    return true;
  });

  // Все узлы сохраняются для топологической стабильности, поисковые совпадения подсвечиваются
  const filteredNodes = graph.nodes;

  return { filteredNodes, filteredEdges };
}

/**
 * Преобразование в элементы React Flow
 */
export function buildReactFlowElements(
  nodes: CanonicalNode[],
  edges: CanonicalEdge[],
  positions: Map<string, { x: number; y: number }>,
  blastRadius: BlastRadiusResult | null,
  colorMode: ColorMode,
  searchQuery: string,
  direction: DagDirection = 'RIGHT'
): { flowNodes: Node<NodeData>[]; flowEdges: Edge<EdgeData>[] } {
  const query = searchQuery.trim().toLowerCase();

  const flowNodes: Node<NodeData>[] = nodes.map((node) => {
    const pos = positions.get(node.id) || { x: 0, y: 0 };
    let blastState: NodeData['blastState'] = 'normal';

    if (blastRadius) {
      if (blastRadius.rootNodeId === node.id) {
        blastState = 'root';
      } else if (blastRadius.upstreamNodeIds.has(node.id)) {
        blastState = 'upstream';
      } else if (blastRadius.downstreamNodeIds.has(node.id) || blastRadius.transitiveNodeIds.has(node.id)) {
        blastState = 'downstream';
      } else {
        blastState = 'dimmed';
      }
    }

    const isMatchedSearch = Boolean(
      query &&
        (node.name.toLowerCase().includes(query) ||
          node.endpoints?.some((ep) => ep.path.toLowerCase().includes(query)) ||
          node.tables?.some((t) => t.tableName.toLowerCase().includes(query)))
    );

    const dims = NODE_DIMENSIONS[node.type] || { width: 280, height: 120 };

    return {
      id: node.id,
      type: node.type.toLowerCase(), // 'service' | 'database' | 'message_queue'
      position: pos,
      width: dims.width,
      height: dims.height,
      data: {
        rawNode: node,
        blastState,
        isMatchedSearch,
        direction,
      },
    };
  });

  const flowEdges: Edge<EdgeData>[] = edges.map((edge) => {
    let blastState: EdgeData['blastState'] = 'normal';

    if (blastRadius) {
      blastState = blastRadius.affectedEdgeIds.has(edge.id) ? 'affected' : 'dimmed';
    }

    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: 'custom',
      animated: edge.relationType === 'MESSAGE_QUEUE' || edge.sourceType === 'ML_PREDICTED',
      data: {
        rawEdge: edge,
        colorMode,
        blastState,
      },
    };
  });

  return { flowNodes, flowEdges };
}
