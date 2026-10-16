import type { CanonicalGraph } from '../types/graph';
import rawDemoGraph from './demo_graph.json';
import rawSubmission from './demo_submission.json';
import rawEvidence from './demo_evidence.json';
import rawFacts from './demo_facts.json';
import { mergePipelineFiles } from '../adapters/dataLoader';

/**
 * Канонический демонстрационный граф микросервисов Train Ticket (базовый срез 9 сервисов).
 */
export const demoGraph: CanonicalGraph = rawDemoGraph as unknown as CanonicalGraph;

/**
 * Полный бенчмарк Train Ticket Slice (19 узлов, 27 рёбер, все типы связей и evidence: AST, CFG, ML, LLM-Judge, DB, MQ).
 */
export const trainTicketBenchmarkGraph: CanonicalGraph = mergePipelineFiles([
  { name: 'demo_submission.json', content: rawSubmission },
  { name: 'demo_evidence.json', content: rawEvidence },
  { name: 'demo_facts.json', content: rawFacts },
]).graph;

/**
 * Загрузка эталонного демо-графа через HTTP с fallback на встроенный JSON.
 */
export async function fetchDemoGraph(): Promise<CanonicalGraph> {
  try {
    const response = await fetch('/data/canonical_graph.json');
    if (response.ok) {
      return (await response.json()) as CanonicalGraph;
    }
  } catch {
    // fallback to demo_graph.json
  }
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

