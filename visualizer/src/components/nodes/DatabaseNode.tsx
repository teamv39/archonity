import React, { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { Database, Table } from 'lucide-react';
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

  const searchClass = data.isMatchedSearch ? 'search-matched' : '';

  const isDown = data.direction === 'DOWN';
  const targetPos = isDown ? Position.Top : Position.Left;
  const sourcePos = isDown ? Position.Bottom : Position.Right;

  return (
    <div className={`custom-node database-node ${blastClass} ${searchClass}`}>
      <Handle type="target" position={targetPos} className="custom-handle" />

      <div className="node-header">
        <div className="node-title-group">
          <div className="node-icon">
            <Database size={16} />
          </div>
          <span className="node-title" title={node.name}>
            {node.name}
          </span>
        </div>
        <span className="node-badge badge-db">DB</span>
      </div>

      <div className="node-body">
        {node.framework && (
          <div className="node-meta-row">
            <span className="meta-label">Engine:</span>
            <span className="meta-value">{node.framework}</span>
          </div>
        )}

        {node.tables && node.tables.length > 0 && (
          <div className="node-tags">
            {node.tables.map((t) => (
              <span key={t.tableName} className="tag-pill" title={`Table: ${t.tableName}`}>
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
