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
  ReachabilityMode,
  DeadCodeDisplay,
  CallTraceResult,
  CallTraceStep,
  EndpointInfo,
  ScenarioPlaybackState,
} from '../types/graph';
import { TOPOLOGY_HUB_EXCLUSIONS } from '../data/scenariosData';

export interface FilterOptions {
  confidenceThreshold: number;
  activeSources: Record<SourceType, boolean>;
  allowedRelations: Set<RelationType>;
  searchQuery: string;
  colorMode: ColorMode;
  reachabilityMode: ReachabilityMode;
  deadCodeDisplay: DeadCodeDisplay;
  showTransitive?: boolean;
  excludeHubs?: boolean;
}

export interface NodeData extends Record<string, unknown> {
  rawNode: CanonicalNode;
  blastState: 'normal' | 'root' | 'upstream' | 'downstream' | 'dimmed';
  traceState: 'none' | 'start' | 'hop' | 'sink' | 'dimmed';
  scenarioState?: 'none' | 'source' | 'target' | 'dimmed';
  isDeadCode: boolean;
  deadCodeDisplay: DeadCodeDisplay;
  isMatchedSearch: boolean;
  direction?: DagDirection;
}

export interface EdgeData extends Record<string, unknown> {
  rawEdge: CanonicalEdge;
  colorMode: ColorMode;
  blastState: 'normal' | 'affected' | 'dimmed';
  traceState: 'none' | 'active' | 'dimmed';
  scenarioState?: 'none' | 'active' | 'dimmed';
  isDeadCode: boolean;
  deadCodeDisplay: DeadCodeDisplay;
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
 * Проверка достижимости ребра из публичных точек входа (контроллеры, слушатели MQ, cron)
 */
export function isEdgeReachable(edge: CanonicalEdge): boolean {
  if (edge.isReachable !== undefined) return edge.isReachable;
  if (edge.evidenceDetails?.isReachable !== undefined) return edge.evidenceDetails.isReachable;

  // Анализ цепочки вызовов: начинается ли цепочка с публичной точки входа?
  const chain = edge.evidenceDetails?.callChain;
  if (chain && chain.length > 0) {
    const hasEntrypoint = chain.some((step) =>
      /controller|@postmapping|@getmapping|@requestmapping|@putmapping|@deletemapping|@patchmapping|@rabbitlistener|@kafkalistener|listener|consumer|@scheduled|cron/i.test(
        step
      )
    );
    return hasEntrypoint;
  }

  // Если указан вызывающий метод сервиса без связки с контроллером
  const caller = edge.evidenceDetails?.caller;
  if (caller && /serviceimpl|service\./i.test(caller) && !/controller/i.test(caller)) {
    if (edge.confidence < 0.4) return false;
  }

  return true;
}

/**
 * Проверка достижимости узла в рантайм-графе
 */
export function isNodeReachable(
  node: CanonicalNode,
  edges: CanonicalEdge[],
  reachableEdgeIds: Set<string>
): boolean {
  // База данных или очередь достижима, если к ней есть хотя бы одно активное достижимое ребро
  if (node.type === 'DATABASE' || node.type === 'MESSAGE_QUEUE') {
    return edges.some((e) => e.target === node.id && reachableEdgeIds.has(e.id));
  }

  // Микросервис считается достижимым, если у него есть объявленные эндпоинты/слушатели
  // ИЛИ если к нему ведут входящие/исходящие достижимые вызовы
  const hasEndpoints =
    (node.endpoints && node.endpoints.length > 0) ||
    (node.destinations && node.destinations.some((d) => d.role === 'CONSUMER'));

  const hasReachableEdges = edges.some(
    (e) => (e.source === node.id || e.target === node.id) && reachableEdgeIds.has(e.id)
  );

  return Boolean(hasEndpoints || hasReachableEdges);
}

/**
 * Сквозная трассировка цепочки вызовов от выбранного эндпоинта контроллера (Cross-Service Call Path Tracing)
 */
export function traceCallPath(
  graph: CanonicalGraph,
  rootServiceId: string,
  endpoint: EndpointInfo
): CallTraceResult | null {
  const affectedNodeIds = new Set<string>([rootServiceId]);
  const affectedEdgeIds = new Set<string>();
  const nodeRoles = new Map<string, 'start' | 'hop' | 'sink'>();
  nodeRoles.set(rootServiceId, 'start');

  const orderedSteps: CallTraceStep[] = [];
  const targetDatabases: string[] = [];
  const targetQueues: string[] = [];

  const epHandler =
    endpoint.handlerClass && endpoint.handlerMethod
      ? `${endpoint.handlerClass}.${endpoint.handlerMethod}`
      : endpoint.handlerMethod || '';
  const epPath = endpoint.path.toLowerCase();

  let stepCounter = 1;

  // 1. Начальный шаг - контроллер
  orderedSteps.push({
    stepIndex: stepCounter++,
    serviceId: rootServiceId,
    serviceName: graph.nodes.find((n) => n.id === rootServiceId)?.name || rootServiceId,
    endpoint: endpoint.path,
    httpMethod: endpoint.httpMethod,
    caller: epHandler || `${endpoint.httpMethod} ${endpoint.path}`,
  });

  // Очередь для поиска вызовов по графу
  const queue: Array<{
    serviceId: string;
    currentHandler?: string;
    currentPath?: string;
    depth: number;
  }> = [
    {
      serviceId: rootServiceId,
      currentHandler: epHandler,
      currentPath: epPath,
      depth: 0,
    },
  ];
  const visitedServices = new Set<string>([rootServiceId]);

  while (queue.length > 0) {
    const current = queue.shift()!;
    const sourceNode = graph.nodes.find((n) => n.id === current.serviceId);
    const sourceEdges = graph.edges.filter((e) => e.source === current.serviceId);

    for (const edge of sourceEdges) {
      let isMatch = false;

      if (current.depth === 0) {
        // Первый уровень: сопоставляем с начальным контроллером/эндпоинтом
        const chain = edge.evidenceDetails?.callChain;
        const caller = edge.evidenceDetails?.caller || '';

        if (chain && chain.length > 0) {
          isMatch = chain.some(
            (c) =>
              (epHandler && c.includes(epHandler)) ||
              (endpoint.handlerMethod && c.includes(endpoint.handlerMethod)) ||
              (epPath && c.toLowerCase().includes(epPath))
          );
        } else if (epHandler && caller.includes(epHandler)) {
          isMatch = true;
        } else if (endpoint.handlerMethod && caller.includes(endpoint.handlerMethod)) {
          isMatch = true;
        } else if (sourceNode?.endpoints && sourceNode.endpoints.length <= 1) {
          isMatch = true;
        }
      } else {
        // Последующие уровни (hops): сопоставляем по целевому пути
        if (current.currentPath) {
          const cleanPath = current.currentPath.replace(/\{[^}]+\}/g, '').toLowerCase();
          const edgeMatched = (edge.evidenceDetails?.matchedEndpoint || '').toLowerCase();
          const edgeChain = (edge.evidenceDetails?.callChain || []).join(' ').toLowerCase();

          isMatch = Boolean(
            (edgeMatched && (edgeMatched.includes(cleanPath) || cleanPath.includes(edgeMatched))) ||
              edgeChain.includes(cleanPath) ||
              edge.relationType === 'DATABASE' ||
              edge.relationType === 'MESSAGE_QUEUE'
          );
        } else {
          isMatch = true;
        }
      }

      if (isMatch) {
        affectedEdgeIds.add(edge.id);
        affectedNodeIds.add(edge.target);

        const targetNode = graph.nodes.find((n) => n.id === edge.target);
        const isDb = edge.relationType === 'DATABASE' || targetNode?.type === 'DATABASE';
        const isMq = edge.relationType === 'MESSAGE_QUEUE' || targetNode?.type === 'MESSAGE_QUEUE';

        if (isDb) {
          const tableName = targetNode?.tables?.[0]?.tableName || targetNode?.name || edge.target;
          if (!targetDatabases.includes(tableName)) targetDatabases.push(tableName);
          nodeRoles.set(edge.target, 'sink');
        } else if (isMq) {
          const qName =
            targetNode?.destinations?.[0]?.destination || targetNode?.name || edge.target;
          if (!targetQueues.includes(qName)) targetQueues.push(qName);
          nodeRoles.set(edge.target, 'sink');
        } else {
          if (!nodeRoles.has(edge.target)) {
            nodeRoles.set(edge.target, 'hop');
          }
        }

        orderedSteps.push({
          stepIndex: stepCounter++,
          serviceId: edge.source,
          serviceName: sourceNode?.name || edge.source,
          caller: edge.evidenceDetails?.caller,
          targetServiceId: edge.target,
          targetRelation: edge.relationType,
          targetEndpoint: edge.evidenceDetails?.matchedEndpoint,
          targetTable: isDb ? targetNode?.tables?.[0]?.tableName || targetNode?.name : undefined,
          edgeId: edge.id,
          codeSnippet: edge.evidenceDetails?.codeSnippet,
          callChain: edge.evidenceDetails?.callChain,
          isDbAccess: isDb,
          isMqPublish: isMq,
        });

        // Если цель — сервис и глубина < 4, продолжаем трассировку
        if (targetNode?.type === 'SERVICE' && !visitedServices.has(edge.target) && current.depth < 4) {
          visitedServices.add(edge.target);
          const nextPath = edge.evidenceDetails?.matchedEndpoint || '';
          queue.push({
            serviceId: edge.target,
            currentPath: nextPath,
            depth: current.depth + 1,
          });
        }
      }
    }
  }

  return {
    rootServiceId,
    rootEndpointId: endpoint.id,
    rootEndpointPath: endpoint.path,
    rootHttpMethod: endpoint.httpMethod,
    rootHandler: epHandler,
    affectedNodeIds,
    affectedEdgeIds,
    nodeRoles,
    orderedSteps,
    targetDatabases,
    targetQueues,
  };
}

/**
 * Фильтрация ребер графа по критериям (источники, порог уверенности ML, протокол, reachability)
 */
export function filterGraph(
  graph: CanonicalGraph,
  filters: FilterOptions
): { filteredNodes: CanonicalNode[]; filteredEdges: CanonicalEdge[]; unreachableEdgesCount: number } {
  // Находим все недостижимые ребра
  let unreachableEdgesCount = 0;

  const filteredEdges = graph.edges.filter((edge) => {
    // Источник доказательства (AST_EXACT, CONFIG, ML_PREDICTED, LLM_JUDGE_VERIFIED, TRANSITIVE)
    if (!filters.activeSources[edge.sourceType]) return false;

    // Тип отношения / протокола (REST_HTTP, DATABASE, MESSAGE_QUEUE, TRANSITIVE)
    if (!filters.allowedRelations.has(edge.relationType)) return false;

    // Порог уверенности: применяется к ML и LLM гипотезам
    if (edge.sourceType === 'ML_PREDICTED' || edge.sourceType === 'LLM_JUDGE_VERIFIED') {
      if (edge.confidence < filters.confidenceThreshold) return false;
    }

    // Исключение инфраструктурных хабов (Eureka, Gateway, RabbitMQ и т.д. по ADR-003)
    if (filters.excludeHubs) {
      if (TOPOLOGY_HUB_EXCLUSIONS.has(edge.source) || TOPOLOGY_HUB_EXCLUSIONS.has(edge.target)) {
        return false;
      }
    }

    const reachable = isEdgeReachable(edge);
    if (!reachable) {
      unreachableEdgesCount++;
      // Если включен режим РАБОЧИЙ РАНТАЙМ и выбрано полное скрытие (HIDE)
      if (filters.reachabilityMode === 'RUNTIME_ONLY' && filters.deadCodeDisplay === 'HIDE') {
        return false;
      }
    }

    return true;
  });

  const reachableEdgeIds = new Set(
    graph.edges.filter((e) => isEdgeReachable(e)).map((e) => e.id)
  );

  // Фильтрация узлов: исключение хабов и/или мертвых узлов
  let filteredNodes = graph.nodes;
  if (filters.excludeHubs) {
    filteredNodes = filteredNodes.filter((node) => !TOPOLOGY_HUB_EXCLUSIONS.has(node.id));
  }
  if (filters.reachabilityMode === 'RUNTIME_ONLY' && filters.deadCodeDisplay === 'HIDE') {
    filteredNodes = filteredNodes.filter((node) => isNodeReachable(node, graph.edges, reachableEdgeIds));
  }

  return { filteredNodes, filteredEdges, unreachableEdgesCount };
}

/**
 * Преобразование в элементы React Flow
 */
export function buildReactFlowElements(
  nodes: CanonicalNode[],
  edges: CanonicalEdge[],
  positions: Map<string, { x: number; y: number }>,
  blastRadius: BlastRadiusResult | null,
  callTrace: CallTraceResult | null,
  colorMode: ColorMode,
  searchQuery: string,
  reachabilityMode: ReachabilityMode,
  deadCodeDisplay: DeadCodeDisplay,
  direction: DagDirection = 'RIGHT',
  fullGraph?: CanonicalGraph,
  scenarioPlayback?: ScenarioPlaybackState | null
): { flowNodes: Node<NodeData>[]; flowEdges: Edge<EdgeData>[] } {
  const query = searchQuery.trim().toLowerCase();

  const referenceEdges = fullGraph ? fullGraph.edges : edges;
  const reachableEdgeIds = new Set(
    referenceEdges.filter((e) => isEdgeReachable(e)).map((e) => e.id)
  );

  const flowNodes: Node<NodeData>[] = nodes.map((node, idx) => {
    const pos = positions.get(node.id) || {
      x: (idx % 4) * 320 + 40,
      y: Math.floor(idx / 4) * 160 + 60,
    };
    let blastState: NodeData['blastState'] = 'normal';
    let traceState: NodeData['traceState'] = 'none';
    let scenarioState: NodeData['scenarioState'] = 'none';

    // 1. Blast Radius состояние
    if (blastRadius) {
      if (blastRadius.rootNodeId === node.id) {
        blastState = 'root';
      } else if (blastRadius.upstreamNodeIds.has(node.id)) {
        blastState = 'upstream';
      } else if (
        blastRadius.downstreamNodeIds.has(node.id) ||
        blastRadius.transitiveNodeIds.has(node.id)
      ) {
        blastState = 'downstream';
      } else {
        blastState = 'dimmed';
      }
    }

    // 2. Call Path Trace состояние
    if (callTrace) {
      if (callTrace.affectedNodeIds.has(node.id)) {
        traceState = callTrace.nodeRoles.get(node.id) || 'hop';
      } else {
        traceState = 'dimmed';
      }
    }

    // 3. Scenario Playback состояние
    if (scenarioPlayback) {
      const activeNodesSet = new Set<string>(scenarioPlayback.currentStep?.activeNodes || []);
      if (scenarioPlayback.sourceNodeId) activeNodesSet.add(scenarioPlayback.sourceNodeId);
      if (scenarioPlayback.targetNodeId) activeNodesSet.add(scenarioPlayback.targetNodeId);

      if (node.id === scenarioPlayback.sourceNodeId) {
        scenarioState = 'source';
      } else if (activeNodesSet.has(node.id)) {
        scenarioState = 'target';
      } else {
        scenarioState = 'dimmed';
      }
    }

    // 4. Reachability / Dead Code
    const isReachable = isNodeReachable(node, referenceEdges, reachableEdgeIds);
    const isDeadCode = reachabilityMode === 'RUNTIME_ONLY' && !isReachable;

    const isMatchedSearch = Boolean(
      query &&
        (node.name.toLowerCase().includes(query) ||
          node.endpoints?.some((ep) => ep.path.toLowerCase().includes(query)) ||
          node.tables?.some((t) => t.tableName.toLowerCase().includes(query)))
    );

    const dims = NODE_DIMENSIONS[node.type] || { width: 280, height: 120 };

    return {
      id: node.id,
      type: node.type.toLowerCase(),
      position: pos,
      width: dims.width,
      height: dims.height,
      data: {
        rawNode: node,
        blastState,
        traceState,
        scenarioState,
        isDeadCode,
        deadCodeDisplay,
        isMatchedSearch,
        direction,
      },
    };
  });

  const flowEdges: Edge<EdgeData>[] = edges.map((edge) => {
    let blastState: EdgeData['blastState'] = 'normal';
    let traceState: EdgeData['traceState'] = 'none';
    let scenarioState: EdgeData['scenarioState'] = 'none';

    if (blastRadius) {
      blastState = blastRadius.affectedEdgeIds.has(edge.id) ? 'affected' : 'dimmed';
    }

    if (callTrace) {
      traceState = callTrace.affectedEdgeIds.has(edge.id) ? 'active' : 'dimmed';
    }

    if (scenarioPlayback) {
      const activeEdgesSet = new Set<string>(scenarioPlayback.currentStep?.activeEdges || []);
      if (scenarioPlayback.activeEdgeId) activeEdgesSet.add(scenarioPlayback.activeEdgeId);

      const isCurrentStepEdge =
        activeEdgesSet.has(edge.id) ||
        (edge.source === scenarioPlayback.sourceNodeId && edge.target === scenarioPlayback.targetNodeId);
      scenarioState = isCurrentStepEdge ? 'active' : 'dimmed';
    }

    const isDeadCode = reachabilityMode === 'RUNTIME_ONLY' && !isEdgeReachable(edge);

    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: 'custom',
      animated:
        scenarioState === 'active' ||
        traceState === 'active' ||
        edge.relationType === 'MESSAGE_QUEUE' ||
        edge.sourceType === 'ML_PREDICTED',
      data: {
        rawEdge: edge,
        colorMode,
        blastState,
        traceState,
        scenarioState,
        isDeadCode,
        deadCodeDisplay,
      },
    };
  });

  return { flowNodes, flowEdges };
}

