export type NodeType = 'SERVICE' | 'DATABASE' | 'MESSAGE_QUEUE';

export type RelationType = 'REST_HTTP' | 'DATABASE' | 'MESSAGE_QUEUE' | 'TRANSITIVE';

export type SourceType =
  | 'AST_EXACT'
  | 'CONFIG'
  | 'ML_PREDICTED'
  | 'TRANSITIVE'
  | 'LLM_JUDGE_VERIFIED';

export type ColorMode = 'by_source' | 'by_protocol';

export type DagDirection = 'RIGHT' | 'DOWN';

export interface EndpointInfo {
  id: string;
  path: string;
  httpMethod: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
  handlerClass?: string;
  handlerMethod?: string;
  requestDto?: string;
  responseDto?: string;
}

export interface DbTableInfo {
  tableName: string;
  dbType: 'MYSQL' | 'MONGODB' | 'POSTGRES';
  operation: 'READ' | 'WRITE' | 'READ_WRITE';
  entityClass?: string;
}

export interface QueueDestinationInfo {
  broker: 'RABBITMQ' | 'KAFKA';
  destination: string;
  role: 'PRODUCER' | 'CONSUMER';
  routingKey?: string;
}

export interface CanonicalNode {
  id: string;
  name: string;
  type: NodeType;
  framework?: string;
  language?: string;
  serverPort?: number;
  contextPath?: string;
  endpoints?: EndpointInfo[];
  tables?: DbTableInfo[];
  destinations?: QueueDestinationInfo[];
  description?: string;
}

export interface EvidenceDetails {
  filePath?: string;
  lineNumber?: number;
  caller?: string;
  matchedEndpoint?: string;
  callChain?: string[];
  codeSnippet?: string;
  modelName?: string;
  threshold?: number;
  topFeatures?: {
    jinaCodeSimilarity?: number;
    dtoOverlapJaccard?: number;
    bm25TokenSimilarity?: number;
    adamicAdarIndex?: number;
    [key: string]: number | undefined;
  };
  llmVerdict?: {
    verdict: 'ACCEPT' | 'REJECT';
    confidence: number;
    reasoning: string;
  };
}

export interface CanonicalEdge {
  id: string;
  source: string;
  target: string;
  relationType: RelationType;
  sourceType: SourceType;
  confidence: number;
  evidenceDetails?: EvidenceDetails;
}

export interface CanonicalGraph {
  nodes: CanonicalNode[];
  edges: CanonicalEdge[];
  metadata?: {
    generatedAt?: string;
    version?: string;
    totalServices?: number;
    totalEdges?: number;
  };
}

export interface BlastRadiusResult {
  rootNodeId: string;
  upstreamNodeIds: Set<string>;
  downstreamNodeIds: Set<string>;
  transitiveNodeIds: Set<string>;
  allAffectedNodeIds: Set<string>;
  affectedEdgeIds: Set<string>;
  depth: number;
}
