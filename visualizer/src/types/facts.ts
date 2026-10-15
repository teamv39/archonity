export interface ServiceMetadata {
  server_port?: number;
  context_path?: string;
  env_vars?: Record<string, string>;
}

export interface InboundEndpointFact {
  id: string;
  path: string;
  http_method: string;
  handler_class: string;
  handler_method: string;
  file_path: string;
  line_number: number;
  request_dto?: {
    class_name: string;
    fields: Array<{ name: string; type: string }>;
  };
  response_dto?: {
    class_name: string;
    fields: Array<{ name: string; type: string }>;
  };
}

export interface OutboundCallFact {
  id: string;
  client_type: string;
  target_service_hint?: string;
  target_url_template?: string;
  raw_expression?: string;
  http_method?: string;
  caller_class: string;
  caller_method: string;
  file_path: string;
  line_number: number;
  is_reachable: boolean;
  call_chain: string[];
  code_snippet?: string;
}

export interface DbAccessFact {
  id: string;
  table_name: string;
  db_type: string;
  operation: string;
  entity_class?: string;
  caller_class: string;
  caller_method: string;
  file_path: string;
  line_number: number;
  is_reachable: boolean;
  call_chain: string[];
}

export interface MessagingFact {
  id: string;
  broker: string;
  role: string;
  destination: string;
  routing_key?: string;
  caller_class: string;
  caller_method: string;
  file_path: string;
  line_number: number;
  is_reachable: boolean;
  call_chain: string[];
}

export interface ServiceFacts {
  service_name: string;
  language: string;
  framework: string;
  repo_path?: string;
  service_metadata?: ServiceMetadata;
  inbound_endpoints?: InboundEndpointFact[];
  outbound_calls?: OutboundCallFact[];
  db_access?: DbAccessFact[];
  messaging?: MessagingFact[];
}
