import React, { memo } from 'react';
import {
  getBezierPath,
  EdgeLabelRenderer,
  type EdgeProps,
} from '@xyflow/react';
import type { EdgeData } from '../../adapters/graphAdapter';
import type { SourceType, RelationType } from '../../types/graph';
import './edges.css';

// Цветовые токены строго по разделу 3 и 6.2 DESIGN.md
const SOURCE_COLORS: Record<SourceType, string> = {
  AST_EXACT: '#15803D',
  CONFIG: '#0369A1',
  ML_PREDICTED: '#B45309',
  LLM_JUDGE_VERIFIED: '#047857',
  TRANSITIVE: '#71717A',
};

const PROTOCOL_COLORS: Record<RelationType, string> = {
  REST_HTTP: '#15803D',
  DATABASE: '#0369A1',
  MESSAGE_QUEUE: '#18181B',
  TRANSITIVE: '#71717A',
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

  // Определение цвета ребра: по протоколу или по слою происхождения
  let color =
    edgeData.colorMode === 'by_protocol'
      ? PROTOCOL_COLORS[rawEdge.relationType] || '#71717A'
      : SOURCE_COLORS[rawEdge.sourceType] || '#71717A';

  // Стиль линии и толщина по DESIGN.md
  let strokeDasharray = 'none';
  let strokeWidth = 1.5;

  if (rawEdge.sourceType === 'ML_PREDICTED') {
    strokeDasharray = '4 2';
    strokeWidth = 1.5;
  } else if (rawEdge.sourceType === 'TRANSITIVE') {
    strokeDasharray = '2 3';
    strokeWidth = 1.0;
  } else {
    // AST_EXACT и CONFIG - сплошная 1.5px
    strokeDasharray = 'none';
    strokeWidth = 1.5;
  }

  // Состояния Blast Radius
  let blastClass = '';
  if (edgeData.blastState === 'affected') {
    blastClass = 'edge-blast-affected';
    color = '#B91C1C';
    strokeWidth = 2.0;
  } else if (edgeData.blastState === 'dimmed') {
    blastClass = 'edge-blast-dimmed';
  }

  // Состояния Call Path Trace
  if (edgeData.traceState === 'active') {
    blastClass += ' edge-trace-active';
    color = '#0969DA';
    strokeWidth = 2.5;
  } else if (edgeData.traceState === 'dimmed') {
    blastClass += ' edge-trace-dimmed';
  }

  // Состояния Dead Code
  if (edgeData.isDeadCode) {
    blastClass += ' edge-dead-code';
    if (edgeData.deadCodeDisplay === 'DIM') {
      strokeDasharray = '3 3';
    }
  }

  if (selected) {
    strokeWidth = 2.5;
    if (edgeData.blastState !== 'affected' && edgeData.traceState !== 'active') {
      color = '#18181B';
    }
  }

  // Отображение бейджа с вероятностью на изломе для ML / LLM или при выборе
  const isMlOrLlm =
    rawEdge.sourceType === 'ML_PREDICTED' || rawEdge.sourceType === 'LLM_JUDGE_VERIFIED';
  const showLabel = isMlOrLlm || selected;

  return (
    <>
      {/* Прозрачный путь для удобного клика мышью */}
      <path
        d={edgePath}
        className="custom-edge-interaction"
      />

      <path
        id={id}
        d={edgePath}
        className={`react-flow__edge-path custom-edge-path ${blastClass} ${selected ? 'edge-selected' : ''}`}
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
            className={`edge-cad-badge ${rawEdge.sourceType.toLowerCase()}`}
            title={`Источник: ${rawEdge.sourceType}, уверенность: ${rawEdge.confidence.toFixed(2)}`}
          >
            {rawEdge.confidence.toFixed(2)}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
});

CustomEdge.displayName = 'CustomEdge';
