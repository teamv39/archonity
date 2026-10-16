import { toPng, toSvg } from 'html-to-image';
import type { CanonicalGraph } from '../types/graph';

/**
 * Фильтр для исключения элементов интерфейса (контролы зума, миникарта) при экспорте
 */
function exportFilter(node: HTMLElement): boolean {
  if (!node.classList) return true;
  if (
    node.classList.contains('react-flow__minimap') ||
    node.classList.contains('react-flow__controls') ||
    node.classList.contains('layout-loading-indicator')
  ) {
    return false;
  }
  return true;
}

/**
 * Экспорт видимой области графа в PNG (2x Retina разрешение)
 */
export async function exportGraphToPng(fileName: string = 'archonity-graph.png'): Promise<void> {
  const target = (document.querySelector('.canvas-wrapper .react-flow') as HTMLElement) ||
                 (document.querySelector('.react-flow__viewport') as HTMLElement);

  if (!target) {
    throw new Error('Canvas элемента React Flow не найден для экспорта');
  }

  const dataUrl = await toPng(target, {
    backgroundColor: '#F7F6F2',
    pixelRatio: 2,
    filter: exportFilter,
    cacheBust: true,
  });

  const link = document.createElement('a');
  link.download = fileName;
  link.href = dataUrl;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

/**
 * Экспорт видимой области графа в векторный SVG
 */
export async function exportGraphToSvg(fileName: string = 'archonity-graph.svg'): Promise<void> {
  const target = (document.querySelector('.canvas-wrapper .react-flow') as HTMLElement) ||
                 (document.querySelector('.react-flow__viewport') as HTMLElement);

  if (!target) {
    throw new Error('Canvas элемента React Flow не найден для экспорта');
  }

  const dataUrl = await toSvg(target, {
    backgroundColor: '#F7F6F2',
    filter: exportFilter,
    cacheBust: true,
  });

  const link = document.createElement('a');
  link.download = fileName;
  link.href = dataUrl;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

/**
 * Экспорт текущего канонического графа в JSON (canonical_graph.json)
 */
export function exportGraphToJson(
  graph: CanonicalGraph,
  fileName: string = 'canonical_graph.json'
): void {
  const blob = new Blob([JSON.stringify(graph, null, 2)], {
    type: 'application/json;charset=utf-8',
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
