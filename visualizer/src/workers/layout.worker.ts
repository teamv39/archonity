import ELK from 'elkjs/lib/elk.bundled.js';

const elk = new ELK();

export interface LayoutWorkerRequest {
  requestId: string;
  direction?: 'RIGHT' | 'DOWN';
  children: Array<{
    id: string;
    width: number;
    height: number;
  }>;
  edges: Array<{
    id: string;
    sources: string[];
    targets: string[];
  }>;
}

export interface LayoutWorkerResponse {
  requestId: string;
  success: boolean;
  nodes?: Array<{
    id: string;
    x: number;
    y: number;
    width: number;
    height: number;
  }>;
  error?: string;
}

self.onmessage = async (event: MessageEvent<LayoutWorkerRequest>) => {
  const { requestId, direction = 'RIGHT', children, edges } = event.data;

  try {
    const root = {
      id: 'root',
      layoutOptions: {
        'elk.algorithm': 'layered',
        'elk.direction': direction,
        'elk.spacing.nodeNode': '50',
        'elk.layered.spacing.nodeNodeBetweenLayers': '90',
        'elk.edgeRouting': 'SPLINES',
        'elk.layered.nodePlacement.bk.fixedAlignment': 'BALANCED',
      },
      children: children.map((c) => ({
        id: c.id,
        width: c.width,
        height: c.height,
      })),
      edges: edges.map((e) => ({
        id: e.id,
        sources: e.sources,
        targets: e.targets,
      })),
    };

    const layouted = await elk.layout(root);

    const nodes = (layouted.children || []).map((node: { id: string; x?: number; y?: number; width?: number; height?: number }) => ({
      id: node.id,
      x: node.x ?? 0,
      y: node.y ?? 0,
      width: node.width ?? 280,
      height: node.height ?? 120,
    }));

    self.postMessage({
      requestId,
      success: true,
      nodes,
    } as LayoutWorkerResponse);
  } catch (err) {
    self.postMessage({
      requestId,
      success: false,
      error: err instanceof Error ? err.message : String(err),
    } as LayoutWorkerResponse);
  }
};
