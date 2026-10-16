import React, { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { Table, AlertTriangle } from 'lucide-react';
import type { NodeProps } from '@xyflow/react';
import type { NodeData } from '../../adapters/graphAdapter';
import './nodes.css';

export const DatabaseNode: React.FC<NodeProps> = memo((props) => {
  const data = props.data as unknown as NodeData;
  const node = data.rawNode;

  let blastClass = '';
  if (data.blastState === 'root') blastClass = 'blast-root';
  else if (data.blastState === 'upstream') blastClass = 'blast-upstream';
  else if (data.blastState === 'downstream') blastClass = 'blast-downstream';
  else if (data.blastState === 'dimmed') blastClass = 'blast-dimmed';

  let traceClass = '';
  if (data.traceState === 'sink' || data.traceState === 'hop') traceClass = 'trace-sink';
  else if (data.traceState === 'dimmed') traceClass = 'trace-dimmed';

  let scenarioClass = '';
  if (data.scenarioState === 'target' || data.scenarioState === 'source') {
    scenarioClass = 'scenario-active-target';
  } else if (data.scenarioState === 'dimmed') {
    scenarioClass = 'scenario-dimmed';
  }

  const deadCodeClass = data.isDeadCode ? `node-dead-code ${data.deadCodeDisplay.toLowerCase()}` : '';
  const searchClass = data.isMatchedSearch ? 'search-matched' : '';

  const isDown = data.direction === 'DOWN';
  const targetPos = isDown ? Position.Top : Position.Left;
  const sourcePos = isDown ? Position.Bottom : Position.Right;

  const isShared = Boolean(node.sharedWith && node.sharedWith.length > 1);

  return (
    <div className={`custom-node database-node ${blastClass} ${traceClass} ${scenarioClass} ${deadCodeClass} ${searchClass}`}>
      <Handle type="target" position={targetPos} className="custom-handle" />

      <div className="node-header">
        <div className="node-title-group">
          <span className="node-type-prefix">[DB]</span>
          <span className="node-title" title={node.name}>
            {node.name}
          </span>
        </div>
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          {(data.traceState === 'sink' || data.traceState === 'hop') && (
            <span className="node-badge badge-trace sink">[SINK/DB]</span>
          )}
          {data.isDeadCode && (
            <span className="node-badge badge-dead-code" title="Таблица не используется в активных вызовах">
              DEAD
            </span>
          )}
          <span
            className="node-badge badge-terminal-sink"
            title="Терминальный сток: узел данных исключен из транзитивного замыкания (ADR-003 п. 7.3)"
          >
            SINK
          </span>
          {isShared && (
            <span
              className="node-badge badge-shared-persistence"
              title={`Разделяемая база данных между: ${node.sharedWith?.join(', ')} (Shared Database Anti-Pattern)`}
            >
              SHARED ({node.sharedWith?.length})
            </span>
          )}
          <span className="node-badge badge-db">DB</span>
        </div>
      </div>

      <div className="node-body">
        {node.framework && (
          <div className="node-meta-row">
            <span className="meta-label">Engine:</span>
            <span className="meta-value">{node.framework}</span>
          </div>
        )}

        {isShared && (
          <div
            className="node-shared-row"
            title={`Прямой доступ к общей БД без REST: ${node.sharedWith?.join(', ')}`}
          >
            <AlertTriangle size={10} style={{ flexShrink: 0 }} />
            <span>Shared: {node.sharedWith?.join(', ')}</span>
          </div>
        )}

        {node.tables && node.tables.length > 0 && (
          <div className="node-tags">
            {node.tables.map((t, idx) => (
              <span key={`${t.tableName}-${idx}`} className="tag-pill" title={`Table: ${t.tableName}`}>
                <Table size={10} style={{ display: 'inline', marginRight: 3, verticalAlign: 'middle' }} />
                {t.tableName}
              </span>
            ))}
          </div>
        )}
      </div>

      <Handle type="source" position={sourcePos} className="custom-handle" />
    </div>
  );
});

DatabaseNode.displayName = 'DatabaseNode';
