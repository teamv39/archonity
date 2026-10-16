import type { RelationType, SourceType, EvidenceDetails } from './graph';

export interface EvidenceRecord {
  edge_id: string;
  source: string;
  target: string;
  relation_type: RelationType;
  source_type: SourceType;
  confidence: number;
  evidence_details: EvidenceDetails;
}

export type EvidenceLog = Record<string, EvidenceRecord> | EvidenceRecord[];
