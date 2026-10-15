import type {
  CanonicalGraph,
  CanonicalNode,
  CanonicalEdge,
  NodeType,
  RelationType,
  SourceType,
  EndpointInfo,
  DbTableInfo,
  QueueDestinationInfo,
  EvidenceDetails,
} from '../types/graph';

export interface LoadResult {
  graph: CanonicalGraph;
  summary: string;
  sourceFile: string;
  warnings: string[];
}

/**
 * Нормализация значений строковых перечислений
 */
function normalizeNodeType(val?: string): NodeType {
  if (!val) return 'SERVICE';
  const upper = val.toUpperCase();
  if (upper.includes('DATA') || upper.includes('DB') || upper.includes('MYSQL') || upper.includes('POSTGRES') || upper.includes('MONGO')) {
    return 'DATABASE';
  }
  if (upper.includes('QUEUE') || upper.includes('MQ') || upper.includes('RABBIT') || upper.includes('KAFKA')) {
    return 'MESSAGE_QUEUE';
  }
  return 'SERVICE';
}

function normalizeRelationType(val?: string): RelationType {
  if (!val) return 'REST_HTTP';
  const upper = val.toUpperCase();
  if (upper.includes('DATA') || upper.includes('DB') || upper.includes('SQL')) return 'DATABASE';
  if (upper.includes('QUEUE') || upper.includes('MQ') || upper.includes('MSG') || upper.includes('MESSAGE')) return 'MESSAGE_QUEUE';
  if (upper.includes('TRANS')) return 'TRANSITIVE';
  return 'REST_HTTP';
}

function normalizeSourceType(val?: string): SourceType {
  if (!val) return 'AST_EXACT';
  const upper = val.toUpperCase();
  if (upper.includes('ML') || upper.includes('CATBOOST') || upper.includes('PREDICT')) return 'ML_PREDICTED';
  if (upper.includes('CONFIG') || upper.includes('YAML') || upper.includes('COMPOSE')) return 'CONFIG';
  if (upper.includes('TRANS')) return 'TRANSITIVE';
  if (upper.includes('LLM') || upper.includes('JUDGE')) return 'LLM_JUDGE_VERIFIED';
  return 'AST_EXACT';
}

function normalizeEvidenceDetails(raw: any): EvidenceDetails | undefined {
  if (!raw || typeof raw !== 'object') return undefined;

  const topFeaturesRaw = raw.top_features || raw.topFeatures;
  let topFeatures: EvidenceDetails['topFeatures'] | undefined;
  if (topFeaturesRaw && typeof topFeaturesRaw === 'object') {
    topFeatures = {
      jinaCodeSimilarity: topFeaturesRaw.jina_code_similarity ?? topFeaturesRaw.jinaCodeSimilarity,
      dtoOverlapJaccard: topFeaturesRaw.dto_overlap_jaccard ?? topFeaturesRaw.dtoFieldOverlapJaccard ?? topFeaturesRaw.dtoOverlapJaccard,
      bm25TokenSimilarity: topFeaturesRaw.bm25_token_similarity ?? topFeaturesRaw.bm25TokenSimilarity,
      adamicAdarIndex: topFeaturesRaw.adamic_adar_index ?? topFeaturesRaw.adamicAdarIndex ?? topFeaturesRaw.hitsProduct,
      ...topFeaturesRaw,
    };
  }

  const llmRaw = raw.llm_verdict || raw.llmVerdict;
  let llmVerdict: EvidenceDetails['llmVerdict'] | undefined;
  if (llmRaw && typeof llmRaw === 'object') {
    llmVerdict = {
      verdict: (llmRaw.verdict === 'REJECT' ? 'REJECT' : 'ACCEPT'),
      confidence: Number(llmRaw.confidence ?? 1.0),
      reasoning: String(llmRaw.reasoning ?? ''),
    };
  }

  return {
    filePath: raw.file_path ?? raw.filePath,
    lineNumber: raw.line_number ?? raw.lineNumber,
    caller: raw.caller ?? raw.caller_method ?? raw.callerMethod,
    matchedEndpoint: raw.matched_endpoint ?? raw.matchedEndpoint,
    callChain: raw.call_chain ?? raw.callChain,
    codeSnippet: raw.code_snippet ?? raw.codeSnippet,
    isReachable: raw.is_reachable ?? raw.isReachable,
    modelName: raw.model_name ?? raw.modelName,
    threshold: raw.threshold != null ? Number(raw.threshold) : undefined,
    topFeatures,
    llmVerdict,
  };
}

/**
 * Нормализация CanonicalGraph (поддержка camelCase и snake_case из Pydantic)
 */
export function normalizeCanonicalGraph(raw: any): CanonicalGraph {
  const nodesRaw = Array.isArray(raw?.nodes) ? raw.nodes : [];
  const edgesRaw = Array.isArray(raw?.edges) ? raw.edges : [];

  const nodes: CanonicalNode[] = nodesRaw.map((n: any, idx: number) => {
    const id = String(n.id || n.name || `node-${idx}`);
    const name = String(n.name || n.service_name || n.id || id);
    const type = normalizeNodeType(n.type);

    const endpoints: EndpointInfo[] | undefined = Array.isArray(n.endpoints || n.inbound_endpoints)
      ? (n.endpoints || n.inbound_endpoints).map((ep: any, epIdx: number) => ({
          id: ep.id || `ep-${id}-${epIdx}`,
          path: ep.path || '/',
          httpMethod: (ep.http_method || ep.httpMethod || 'GET').toUpperCase(),
          handlerClass: ep.handler_class || ep.handlerClass,
          handlerMethod: ep.handler_method || ep.handlerMethod,
          requestDto: typeof ep.request_dto === 'string' ? ep.request_dto : ep.request_dto?.class_name,
          responseDto: typeof ep.response_dto === 'string' ? ep.response_dto : ep.response_dto?.class_name,
          isReachable: ep.is_reachable ?? ep.isReachable,
        }))
      : undefined;

    const tables: DbTableInfo[] | undefined = Array.isArray(n.tables || n.db_access)
      ? (n.tables || n.db_access).map((t: any) => ({
          tableName: t.table_name || t.tableName || 'table',
          dbType: (t.db_type || t.dbType || 'MYSQL').toUpperCase(),
          operation: (t.operation || 'READ_WRITE').toUpperCase(),
          entityClass: t.entity_class || t.entityClass,
        }))
      : undefined;

    const destinations: QueueDestinationInfo[] | undefined = Array.isArray(n.destinations || n.messaging)
      ? (n.destinations || n.messaging).map((q: any) => ({
          broker: (q.broker || 'RABBITMQ').toUpperCase(),
          destination: q.destination || 'queue',
          role: (q.role || 'PRODUCER').toUpperCase(),
          routingKey: q.routing_key || q.routingKey,
        }))
      : undefined;

    return {
      id,
      name,
      type,
      framework: n.framework,
      language: n.language,
      serverPort: n.server_port ?? n.serverPort,
      contextPath: n.context_path ?? n.contextPath,
      description: n.description,
      endpoints,
      tables,
      destinations,
    };
  });

  const edges: CanonicalEdge[] = edgesRaw.map((e: any) => {
    const source = String(e.source || e.src || e.from || '');
    const target = String(e.target || e.dst || e.to || '');
    const relationType = normalizeRelationType(e.relation_type || e.relationType || e.type);
    const id = String(e.id || `${source}->${target}:${relationType}`);
    const sourceType = normalizeSourceType(e.source_type || e.sourceType);
    const confidence = typeof e.confidence === 'number' ? e.confidence : 1.0;
    const evidenceDetails = normalizeEvidenceDetails(e.evidence_details || e.evidenceDetails);
    const isReachable = e.is_reachable ?? e.isReachable ?? evidenceDetails?.isReachable;

    return {
      id,
      source,
      target,
      relationType,
      sourceType,
      confidence,
      isReachable,
      evidenceDetails,
    };
  });

  return {
    metadata: {
      generatedAt: raw.metadata?.generated_at ?? raw.metadata?.generatedAt ?? new Date().toISOString(),
      version: raw.metadata?.version ?? '1.0.0-loaded',
      totalServices: nodes.filter((n) => n.type === 'SERVICE').length,
      totalEdges: edges.length,
    },
    nodes,
    edges,
  };
}

/**
 * Парсинг словаря или списка evidence.json (ADR-001 раздел 5)
 */
export function parseEvidenceJson(raw: any): {
  evidenceMap: Map<string, EvidenceDetails>;
  syntheticEdges: CanonicalEdge[];
} {
  const evidenceMap = new Map<string, EvidenceDetails>();
  const syntheticEdges: CanonicalEdge[] = [];

  const entries: any[] = Array.isArray(raw)
    ? raw
    : typeof raw === 'object' && raw !== null
      ? Object.entries(raw).map(([key, val]) =>
          typeof val === 'object' && val !== null
            ? { ...(val as Record<string, any>), _dictKey: key }
            : { _dictKey: key, value: val }
        )
      : [];

  for (const item of entries) {
    const source = item.source || item.src;
    const target = item.target || item.dst;
    const relType = normalizeRelationType(item.relation_type || item.relationType);
    const edgeId = item.edge_id || item.edgeId || item._dictKey || (source && target ? `${source}->${target}:${relType}` : undefined);
    const confidence = typeof item.confidence === 'number' ? item.confidence : 1.0;
    const sourceType = normalizeSourceType(item.source_type || item.sourceType);
    const details = normalizeEvidenceDetails(item.evidence_details || item.evidenceDetails || item);

    if (edgeId && details) {
      evidenceMap.set(edgeId, details);
    }
    if (source && target) {
      const altKey = `${source}->${target}`;
      if (details) evidenceMap.set(altKey, details);

      syntheticEdges.push({
        id: edgeId || `${source}->${target}:${relType}`,
        source,
        target,
        relationType: relType,
        sourceType,
        confidence,
        evidenceDetails: details,
      });
    }
  }

  return { evidenceMap, syntheticEdges };
}

/**
 * Парсинг confirmed_edges.json / submission.json из archparse или тестовой системы
 */
export function parseConfirmedEdgesJson(raw: any): CanonicalGraph {
  const items: any[] = Array.isArray(raw)
    ? raw
    : Array.isArray(raw?.edges)
      ? raw.edges
      : Array.isArray(raw?.confirmed_edges)
        ? raw.confirmed_edges
        : [];

  const nodeMap = new Map<string, CanonicalNode>();
  const edges: CanonicalEdge[] = [];

  for (let i = 0; i < items.length; i++) {
    const item = items[i];

    // Формат 1: output/confirmed_edges.json от archparse ({ service, httpMethod, path })
    if (item.service && item.path) {
      const serviceName = item.service;
      if (!nodeMap.has(serviceName)) {
        nodeMap.set(serviceName, {
          id: serviceName,
          name: serviceName,
          type: 'SERVICE',
          framework: 'Spring Boot (archparse)',
          language: 'Java',
          endpoints: [],
        });
      }

      // Парсинг аннотации типа @PostMapping(path = "/adminbasic/contacts")
      let cleanPath = item.path;
      const match = cleanPath.match(/"([^"]+)"/);
      if (match) cleanPath = match[1];

      let method: EndpointInfo['httpMethod'] = 'POST';
      if (item.path.includes('GetMapping') || item.httpMethod?.toLowerCase().includes('get')) method = 'GET';
      else if (item.path.includes('DeleteMapping') || item.httpMethod?.toLowerCase().includes('delete')) method = 'DELETE';
      else if (item.path.includes('PutMapping') || item.httpMethod?.toLowerCase().includes('put')) method = 'PUT';

      const node = nodeMap.get(serviceName)!;
      node.endpoints = node.endpoints || [];
      node.endpoints.push({
        id: `ep-${serviceName}-${node.endpoints.length + 1}`,
        path: cleanPath,
        httpMethod: method,
        handlerMethod: item.httpMethod,
        handlerClass: serviceName,
      });
      continue;
    }

    // Формат 2: Прямое ребро { source, target, relationType, confidence }
    const source = item.source || item.from || item.src;
    const target = item.target || item.to || item.dst;
    if (source && target) {
      if (!nodeMap.has(source)) {
        nodeMap.set(source, { id: source, name: source, type: normalizeNodeType(source) });
      }
      if (!nodeMap.has(target)) {
        nodeMap.set(target, { id: target, name: target, type: normalizeNodeType(target) });
      }

      const relType = normalizeRelationType(item.relation_type || item.relationType || item.type);
      edges.push({
        id: item.id || `edge-${source}-${target}-${i}`,
        source,
        target,
        relationType: relType,
        sourceType: normalizeSourceType(item.source_type || item.sourceType),
        confidence: typeof item.confidence === 'number' ? item.confidence : 1.0,
        evidenceDetails: normalizeEvidenceDetails(item.evidence_details || item.evidenceDetails),
      });
    }
  }

  const nodes = Array.from(nodeMap.values());
  return {
    metadata: {
      generatedAt: new Date().toISOString(),
      version: '1.0.0-confirmed-edges',
      totalServices: nodes.filter((n) => n.type === 'SERVICE').length,
      totalEdges: edges.length,
    },
    nodes,
    edges,
  };
}

/**
 * Парсинг facts.json или facts/<service>.json (ADR-001 раздел 3)
 */
export function parseFactsJson(raw: any): CanonicalGraph {
  const serviceList: any[] = Array.isArray(raw)
    ? raw
    : raw?.services && typeof raw.services === 'object'
      ? Object.values(raw.services)
      : raw?.service_name || raw?.serviceName
        ? [raw]
        : [];

  const nodeMap = new Map<string, CanonicalNode>();
  const edges: CanonicalEdge[] = [];

  for (const svc of serviceList) {
    const sName = svc.service_name || svc.serviceName || svc.id;
    if (!sName) continue;

    const endpoints: EndpointInfo[] = Array.isArray(svc.inbound_endpoints)
      ? svc.inbound_endpoints.map((ep: any, idx: number) => ({
          id: ep.id || `ep-${sName}-${idx}`,
          path: ep.path || '/',
          httpMethod: (ep.http_method || 'GET').toUpperCase(),
          handlerClass: ep.handler_class,
          handlerMethod: ep.handler_method,
          requestDto: ep.request_dto?.class_name,
          responseDto: ep.response_dto?.class_name,
        }))
      : [];

    nodeMap.set(sName, {
      id: sName,
      name: sName,
      type: 'SERVICE',
      framework: svc.framework || 'Spring Boot',
      language: svc.language || 'Java',
      serverPort: svc.service_metadata?.server_port,
      contextPath: svc.service_metadata?.context_path,
      endpoints,
    });

    // Исходящие вызовы -> ребра
    if (Array.isArray(svc.outbound_calls)) {
      for (let j = 0; j < svc.outbound_calls.length; j++) {
        const call = svc.outbound_calls[j];
        const target = call.target_service_hint || call.target_service;
        if (target) {
          if (!nodeMap.has(target)) {
            nodeMap.set(target, { id: target, name: target, type: 'SERVICE' });
          }
          edges.push({
            id: call.id || `edge-${sName}-${target}-${j}`,
            source: sName,
            target,
            relationType: 'REST_HTTP',
            sourceType: 'AST_EXACT',
            confidence: 1.0,
            isReachable: call.is_reachable ?? true,
            evidenceDetails: {
              filePath: call.file_path,
              lineNumber: call.line_number,
              caller: `${call.caller_class || ''}.${call.caller_method || ''}`.replace(/^\./, ''),
              matchedEndpoint: `${call.http_method || 'POST'} ${call.target_url_template || call.raw_expression || ''}`,
              callChain: call.call_chain,
              codeSnippet: call.code_snippet,
              isReachable: call.is_reachable ?? true,
            },
          });
        }
      }
    }

    // Обращения к БД -> узел таблицы + ребро
    if (Array.isArray(svc.db_access)) {
      for (const db of svc.db_access) {
        const tableName = db.table_name || 'db_table';
        const dbNodeId = `db-${tableName}`;
        if (!nodeMap.has(dbNodeId)) {
          nodeMap.set(dbNodeId, {
            id: dbNodeId,
            name: tableName,
            type: 'DATABASE',
            framework: db.db_type || 'MySQL',
            tables: [
              {
                tableName,
                dbType: (db.db_type || 'MYSQL').toUpperCase(),
                operation: (db.operation || 'READ_WRITE').toUpperCase(),
                entityClass: db.entity_class,
              },
            ],
          });
        }
        edges.push({
          id: db.id || `edge-${sName}-${dbNodeId}`,
          source: sName,
          target: dbNodeId,
          relationType: 'DATABASE',
          sourceType: 'AST_EXACT',
          confidence: 1.0,
          isReachable: db.is_reachable ?? true,
          evidenceDetails: {
            filePath: db.file_path,
            lineNumber: db.line_number,
            caller: `${db.caller_class || ''}.${db.caller_method || ''}`.replace(/^\./, ''),
            callChain: db.call_chain,
            isReachable: db.is_reachable ?? true,
          },
        });
      }
    }

    // Асинхронный обмен через очереди -> узел очереди + ребро
    if (Array.isArray(svc.messaging)) {
      for (const mq of svc.messaging) {
        const qName = mq.destination || 'queue';
        const qNodeId = `mq-${qName}`;
        if (!nodeMap.has(qNodeId)) {
          nodeMap.set(qNodeId, {
            id: qNodeId,
            name: qName,
            type: 'MESSAGE_QUEUE',
            framework: mq.broker || 'RabbitMQ',
            destinations: [
              {
                broker: (mq.broker || 'RABBITMQ').toUpperCase(),
                destination: qName,
                role: (mq.role || 'PRODUCER').toUpperCase(),
                routingKey: mq.routing_key,
              },
            ],
          });
        }
        const isProducer = (mq.role || 'PRODUCER').toUpperCase() === 'PRODUCER';
        edges.push({
          id: mq.id || `edge-${sName}-${qNodeId}`,
          source: isProducer ? sName : qNodeId,
          target: isProducer ? qNodeId : sName,
          relationType: 'MESSAGE_QUEUE',
          sourceType: 'AST_EXACT',
          confidence: 1.0,
          isReachable: mq.is_reachable ?? true,
          evidenceDetails: {
            filePath: mq.file_path,
            lineNumber: mq.line_number,
            caller: `${mq.caller_class || ''}.${mq.caller_method || ''}`.replace(/^\./, ''),
            matchedEndpoint: `${mq.broker || 'RABBITMQ'}: ${qName} (${mq.routing_key || ''})`,
            callChain: mq.call_chain,
            isReachable: mq.is_reachable ?? true,
          },
        });
      }
    }
  }

  const nodes = Array.from(nodeMap.values());
  return {
    metadata: {
      generatedAt: new Date().toISOString(),
      version: '1.0.0-facts',
      totalServices: nodes.filter((n) => n.type === 'SERVICE').length,
      totalEdges: edges.length,
    },
    nodes,
    edges,
  };
}

/**
 * Объединение нескольких файлов (например canonical_graph.json + evidence.json + facts.json)
 */
export function mergePipelineFiles(
  files: { name: string; content: any }[]
): LoadResult {
  const warnings: string[] = [];
  let baseGraph: CanonicalGraph | null = null;
  const allSyntheticEdges: CanonicalEdge[] = [];
  const evidenceMaps: Map<string, EvidenceDetails>[] = [];

  for (const { name, content } of files) {
    if (!content) continue;

    // Проверяем: CanonicalGraph
    if (content.nodes && Array.isArray(content.nodes) && content.edges && Array.isArray(content.edges)) {
      baseGraph = normalizeCanonicalGraph(content);
      continue;
    }

    // Проверяем: facts.json
    if (content.service_name || content.serviceName || (content.services && typeof content.services === 'object')) {
      const g = parseFactsJson(content);
      if (!baseGraph) {
        baseGraph = g;
      } else {
        // объединить узлы и ребра
        const nodeMap = new Map(baseGraph.nodes.map((n) => [n.id, n]));
        for (const n of g.nodes) {
          if (!nodeMap.has(n.id)) {
            nodeMap.set(n.id, n);
          } else {
            const existing = nodeMap.get(n.id)!;
            existing.endpoints = [...(existing.endpoints || []), ...(n.endpoints || [])];
            existing.tables = [...(existing.tables || []), ...(n.tables || [])];
          }
        }
        baseGraph.nodes = Array.from(nodeMap.values());
        baseGraph.edges = [...baseGraph.edges, ...g.edges];
      }
      continue;
    }

    // Проверяем: evidence.json
    if (
      name.toLowerCase().includes('evidence') ||
      (typeof content === 'object' && !Array.isArray(content) && Object.values(content).some((v: any) => v?.source_type || v?.evidence_details))
    ) {
      const { evidenceMap, syntheticEdges } = parseEvidenceJson(content);
      evidenceMaps.push(evidenceMap);
      allSyntheticEdges.push(...syntheticEdges);
      continue;
    }

    // Проверяем: confirmed_edges.json / submission.json
    if (Array.isArray(content) || Array.isArray(content.edges) || Array.isArray(content.confirmed_edges)) {
      const g = parseConfirmedEdgesJson(content);
      if (!baseGraph) {
        baseGraph = g;
      } else {
        const nodeMap = new Map(baseGraph.nodes.map((n) => [n.id, n]));
        for (const n of g.nodes) {
          if (!nodeMap.has(n.id)) nodeMap.set(n.id, n);
        }
        baseGraph.nodes = Array.from(nodeMap.values());
        baseGraph.edges = [...baseGraph.edges, ...g.edges];
      }
      continue;
    }

    warnings.push(`Файл ${name} не распознан как стандартный контракт данных Archonity`);
  }

  // Если базового графа нет, строим из синтетических ребер evidence
  if (!baseGraph) {
    if (allSyntheticEdges.length > 0) {
      const nodeMap = new Map<string, CanonicalNode>();
      for (const e of allSyntheticEdges) {
        if (!nodeMap.has(e.source)) nodeMap.set(e.source, { id: e.source, name: e.source, type: normalizeNodeType(e.source) });
        if (!nodeMap.has(e.target)) nodeMap.set(e.target, { id: e.target, name: e.target, type: normalizeNodeType(e.target) });
      }
      baseGraph = {
        metadata: {
          generatedAt: new Date().toISOString(),
          version: '1.0.0-evidence-derived',
          totalServices: Array.from(nodeMap.values()).filter((n) => n.type === 'SERVICE').length,
          totalEdges: allSyntheticEdges.length,
        },
        nodes: Array.from(nodeMap.values()),
        edges: allSyntheticEdges,
      };
    } else {
      throw new Error('Не удалось распознать структуру графа ни в одном из переданных файлов');
    }
  }

  // Обогащаем ребра графа из всех карт evidence
  if (evidenceMaps.length > 0) {
    for (const e of baseGraph.edges) {
      for (const evMap of evidenceMaps) {
        const details = evMap.get(e.id) || evMap.get(`${e.source}->${e.target}`);
        if (details && !e.evidenceDetails) {
          e.evidenceDetails = details;
        }
      }
    }
  }

  // Удаление дубликатов ребер по (source, target, relationType)
  const edgeKeyMap = new Map<string, CanonicalEdge>();
  for (const e of baseGraph.edges) {
    const key = `${e.source}__${e.target}__${e.relationType}`;
    if (!edgeKeyMap.has(key)) {
      edgeKeyMap.set(key, e);
    } else {
      // объединяем evidenceDetails если у дубликата больше информации
      const existing = edgeKeyMap.get(key)!;
      if (!existing.evidenceDetails && e.evidenceDetails) {
        existing.evidenceDetails = e.evidenceDetails;
      }
    }
  }
  baseGraph.edges = Array.from(edgeKeyMap.values());

  const fileNames = files.map((f) => f.name).join(', ');
  return {
    graph: baseGraph,
    sourceFile: fileNames,
    summary: `Загружено: ${baseGraph.nodes.length} узлов, ${baseGraph.edges.length} рёбер`,
    warnings,
  };
}

/**
 * Чтение и валидация единичного файла (JSON текст)
 */
export function parseGraphFromString(jsonText: string, fileName: string): LoadResult {
  let parsed: any;
  try {
    parsed = JSON.parse(jsonText);
  } catch (err: any) {
    throw new Error(`Ошибка парсинга JSON в файле ${fileName}: ${err.message}`);
  }

  return mergePipelineFiles([{ name: fileName, content: parsed }]);
}
