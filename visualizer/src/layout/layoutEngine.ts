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
    const dims = NODE_DIMENSIONS[n.type] || { width: 280, height: 120 };
    return {
      id: n.id,
      width: dims.width,
      height: dims.height,
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
      'elk.spacing.nodeNode': '60',
      'elk.layered.spacing.nodeNodeBetweenLayers': '100',
      'elk.edgeRouting': 'SPLINES',
      'elk.layered.nodePlacement.bk.fixedAlignment': 'BALANCED',
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
