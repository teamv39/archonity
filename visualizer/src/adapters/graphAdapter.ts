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
import type { LayoutWorkerRequest, LayoutWorkerResponse } from '../workers/layout.worker';

export interface FilterOptions {
  confidenceThreshold: number;
  allowedSources: Set<SourceType>;
  allowedRelations: Set<RelationType>;
  searchQuery: string;
  colorMode: ColorMode;
  showTransitive: boolean;
}

export interface NodeData extends Record<string, unknown> {
  rawNode: CanonicalNode;
  blastState: 'normal' | 'root' | 'upstream' | 'downstream' | 'dimmed';
  isMatchedSearch: boolean;
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
 * Фильтрация ребер и узлов графа по критериям
 */
export function filterGraph(
  graph: CanonicalGraph,
  filters: FilterOptions
): { filteredNodes: CanonicalNode[]; filteredEdges: CanonicalEdge[] } {
  // Фильтруем ребра
  const filteredEdges = graph.edges.filter((edge) => {
    // Порог уверенности
    if (edge.confidence < filters.confidenceThreshold) return false;

    // Источник доказательства
    if (!filters.allowedSources.has(edge.sourceType)) return false;

    // Тип отношения
    if (!filters.allowedRelations.has(edge.relationType)) return false;

    // Транзитивные ребра
    if (!filters.showTransitive && edge.relationType === 'TRANSITIVE') return false;

    return true;
  });

  const activeNodeIds = new Set<string>();
  filteredEdges.forEach((e) => {
    activeNodeIds.add(e.source);
    activeNodeIds.add(e.target);
  });

  // Узлы показываем, если они участвуют в активных ребрах, либо если нет фильтра по поиску
  const query = filters.searchQuery.trim().toLowerCase();
  const filteredNodes = graph.nodes.filter((node) => {
    if (query) {
      const matchName = node.name.toLowerCase().includes(query);
      const matchEndpoints = node.endpoints?.some((ep) =>
        ep.path.toLowerCase().includes(query) || ep.handlerMethod?.toLowerCase().includes(query)
      );
      const matchTables = node.tables?.some((t) => t.tableName.toLowerCase().includes(query));
      if (!matchName && !matchEndpoints && !matchTables) return false;
    }
    return true;
  });

  return { filteredNodes, filteredEdges };
}

/**
 * Асинхронный расчет координат через ELK.js Web Worker
 */
export async function computeElkLayout(
  worker: Worker,
  nodes: CanonicalNode[],
  edges: CanonicalEdge[],
  direction: DagDirection = 'RIGHT'
): Promise<Map<string, { x: number; y: number }>> {
  return new Promise((resolve, reject) => {
    const requestId = `req_${Date.now()}_${Math.random()}`;

    const handleMessage = (event: MessageEvent<LayoutWorkerResponse>) => {
      if (event.data.requestId === requestId) {
        worker.removeEventListener('message', handleMessage);
        if (event.data.success && event.data.nodes) {
          const positions = new Map<string, { x: number; y: number }>();
          event.data.nodes.forEach((n) => positions.set(n.id, { x: n.x, y: n.y }));
          resolve(positions);
        } else {
          reject(new Error(event.data.error || 'Layout computation failed'));
        }
      }
    };

    worker.addEventListener('message', handleMessage);

    const children = nodes.map((n) => {
      const dims = NODE_DIMENSIONS[n.type] || { width: 280, height: 120 };
      return { id: n.id, width: dims.width, height: dims.height };
    });

    const elkEdges = edges.map((e) => ({
      id: e.id,
      sources: [e.source],
      targets: [e.target],
    }));

    const req: LayoutWorkerRequest = {
      requestId,
      direction,
      children,
      edges: elkEdges,
    };

    worker.postMessage(req);
  });
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
  searchQuery: string
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
