import ELK from 'elkjs/lib/elk.bundled.js';
import type { CanonicalNode, CanonicalEdge, DagDirection } from '../types/graph';
import { NODE_DIMENSIONS } from '../adapters/graphAdapter';

const elk = new ELK();

export async function computeLayout(
  nodes: CanonicalNode[],
  edges: CanonicalEdge[],
  direction: DagDirection = 'RIGHT'
): Promise<Map<string, { x: number; y: number }>> {
  const nodeIds = new Set(nodes.map((n) => n.id));
  const validEdges = edges.filter(
    (e) => nodeIds.has(e.source) && nodeIds.has(e.target)
  );

  const children = nodes.map((n) => {
    const dims = NODE_DIMENSIONS[n.type] || { width: 300, height: 130 };
    const isGateway = n.id === 'ts-gateway-service';
    const isDb = n.type === 'DATABASE';

    const childLayoutOptions: Record<string, string> = {};
    if (isGateway) {
      childLayoutOptions['elk.layered.layering.layerConstraint'] = 'FIRST';
    } else if (isDb) {
      childLayoutOptions['elk.layered.layering.layerConstraint'] = 'LAST';
    }

    return {
      id: n.id,
      width: dims.width,
      height: dims.height,
      layoutOptions: childLayoutOptions,
    };
  });

  const elkEdges = validEdges.map((e) => ({
    id: e.id,
    sources: [e.source],
    targets: [e.target],
  }));

  const root = {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': direction,
      // Просторное расстояние между узлами и слоями без наездов
      'elk.spacing.nodeNode': '80',
      'elk.layered.spacing.nodeNodeBetweenLayers': '160',
      'elk.spacing.edgeNode': '40',
      'elk.spacing.edgeEdge': '25',
      'elk.spacing.componentComponent': '140',
      'elk.layered.spacing.edgeNodeBetweenLayers': '35',
      // Минимизация пересечений и сбалансированное размещение
      'elk.edgeRouting': 'SPLINES',
      'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
      'elk.layered.crossingMinimization.greedySwitch.type': 'TWO_SIDED',
      'elk.layered.nodePlacement.strategy': 'BRANDES_KOEPF',
      'elk.layered.nodePlacement.bk.fixedAlignment': 'BALANCED',
      'elk.layered.cycleBreaking.strategy': 'GREEDY',
      'elk.layered.layering.strategy': 'NETWORK_SIMPLEX',
      'elk.separateConnectedComponents': 'true',
      'elk.layered.compaction.postCompaction.strategy': 'EDGE_LENGTH',
      'elk.aspectRatio': '1.6',
    },
    children,
    edges: elkEdges,
  };

  try {
    const layouted = await elk.layout(root);
    const positions = new Map<string, { x: number; y: number }>();

    (layouted.children || []).forEach((c: { id: string; x?: number; y?: number }) => {
      positions.set(c.id, { x: c.x ?? 0, y: c.y ?? 0 });
    });

    return positions;
  } catch (err) {
    console.error('ELK Layout error:', err);
    // Фолбэк на базовую сетку при ошибке
    const fallback = new Map<string, { x: number; y: number }>();
    nodes.forEach((n, idx) => {
      const col = idx % 4;
      const row = Math.floor(idx / 4);
      fallback.set(n.id, { x: col * 340 + 50, y: row * 200 + 100 });
    });
    return fallback;
  }
}
