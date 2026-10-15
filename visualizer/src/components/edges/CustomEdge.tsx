import React, { memo } from 'react';
import {
  getBezierPath,
  EdgeLabelRenderer,
  type EdgeProps,
} from '@xyflow/react';
import type { EdgeData } from '../../adapters/graphAdapter';
import type { SourceType, RelationType } from '../../types/graph';
import './edges.css';

const SOURCE_COLORS: Record<SourceType, string> = {
  AST_EXACT: '#38bdf8',
  CONFIG: '#f59e0b',
  ML_PREDICTED: '#ec4899',
  LLM_JUDGE_VERIFIED: '#10b981',
  TRANSITIVE: '#94a3b8',
};

const PROTOCOL_COLORS: Record<RelationType, string> = {
  REST_HTTP: '#38bdf8',
  DATABASE: '#f59e0b',
  MESSAGE_QUEUE: '#a855f7',
  TRANSITIVE: '#94a3b8',
};

export const CustomEdge: React.FC<EdgeProps> = memo((props) => {
  const {
    id,
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    data,
    selected,
  } = props;

  const edgeData = data as unknown as EdgeData;
  const rawEdge = edgeData?.rawEdge;

  if (
    sourceX === undefined ||
    sourceY === undefined ||
    targetX === undefined ||
    targetY === undefined ||
    isNaN(sourceX) ||
    isNaN(sourceY) ||
    isNaN(targetX) ||
    isNaN(targetY)
  ) {
    return null;
  }

  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  if (!rawEdge) {
    return <path id={id} className="react-flow__edge-path" d={edgePath} />;
  }

  // Определение цвета ребра в зависимости от выбранного режима
  const color =
    edgeData.colorMode === 'by_protocol'
      ? PROTOCOL_COLORS[rawEdge.relationType] || '#94a3b8'
      : SOURCE_COLORS[rawEdge.sourceType] || '#94a3b8';

  // Стиль линии
  let strokeDasharray = 'none';
  if (rawEdge.sourceType === 'CONFIG') {
    strokeDasharray = '6 4';
  } else if (rawEdge.sourceType === 'ML_PREDICTED') {
    strokeDasharray = '4 3';
  } else if (rawEdge.sourceType === 'TRANSITIVE') {
    strokeDasharray = '2 3';
  }

  // Blast radius классы
  let blastClass = '';
  if (edgeData.blastState === 'affected') {
    blastClass = 'edge-blast-affected';
  } else if (edgeData.blastState === 'dimmed') {
    blastClass = 'edge-blast-dimmed';
  }

  const strokeWidth = selected ? 3.5 : 1.8;

  let labelBadgeClass = 'label-source-ast';
  if (rawEdge.sourceType === 'CONFIG') labelBadgeClass = 'label-source-config';
  else if (rawEdge.sourceType === 'ML_PREDICTED') labelBadgeClass = 'label-source-ml';
  else if (rawEdge.sourceType === 'LLM_JUDGE_VERIFIED') labelBadgeClass = 'label-source-llm';
  else if (rawEdge.sourceType === 'TRANSITIVE') labelBadgeClass = 'label-source-transitive';

  const showLabel =
    rawEdge.sourceType === 'ML_PREDICTED' ||
    rawEdge.sourceType === 'LLM_JUDGE_VERIFIED' ||
    selected;

  return (
    <>
      {/* Прозрачный толстый путь для легкого клика мышью */}
      <path
        d={edgePath}
        className="custom-edge-interaction"
      />

      <path
        id={id}
        d={edgePath}
        className={`react-flow__edge-path custom-edge-path ${blastClass}`}
        stroke={color}
        strokeWidth={strokeWidth}
        strokeDasharray={strokeDasharray}
        style={{ color }}
      />

      {showLabel && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            }}
            className={`edge-label-container ${labelBadgeClass}`}
            title={`Источник: ${rawEdge.sourceType}, уверенность: ${(rawEdge.confidence * 100).toFixed(0)}%`}
          >
            {rawEdge.sourceType === 'LLM_JUDGE_VERIFIED' ? (
              <span>LLM {(rawEdge.confidence * 100).toFixed(0)}%</span>
            ) : rawEdge.sourceType === 'ML_PREDICTED' ? (
              <span>ML {(rawEdge.confidence * 100).toFixed(0)}%</span>
            ) : (
              <span>{(rawEdge.confidence * 100).toFixed(0)}%</span>
            )}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
});

CustomEdge.displayName = 'CustomEdge';
