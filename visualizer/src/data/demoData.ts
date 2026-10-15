import type { CanonicalGraph } from '../types/graph';
import rawDemoGraph from './demo_graph.json';

/**
 * Канонический демонстрационный граф микросервисов Train Ticket.
 * Вынесен в отдельный JSON-файл demo_graph.json для изоляции тестовых данных
 * и единого источника правды между фронтендом, CLI и тестами.
 */
export const demoGraph: CanonicalGraph = rawDemoGraph as unknown as CanonicalGraph;

/**
 * Загрузка эталонного демо-графа через HTTP с fallback на встроенный JSON.
 */
export async function fetchDemoGraph(): Promise<CanonicalGraph> {
  try {
    const response = await fetch('/data/demo_graph.json');
    if (response.ok) {
      return (await response.json()) as CanonicalGraph;
    }
  } catch (err) {
    console.warn('Failed to fetch /data/demo_graph.json, falling back to static import', err);
  }
  return demoGraph;
}
