import React, { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { Layers } from 'lucide-react';
import type { NodeProps } from '@xyflow/react';
import type { NodeData } from '../../adapters/graphAdapter';
import './nodes.css';

export const QueueNode: React.FC<NodeProps> = memo((props) => {
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

  const deadCodeClass = data.isDeadCode ? `node-dead-code ${data.deadCodeDisplay.toLowerCase()}` : '';
  const searchClass = data.isMatchedSearch ? 'search-matched' : '';

  const isDown = data.direction === 'DOWN';
  const targetPos = isDown ? Position.Top : Position.Left;
  const sourcePos = isDown ? Position.Bottom : Position.Right;

  return (
    <div className={`custom-node queue-node ${blastClass} ${traceClass} ${deadCodeClass} ${searchClass}`}>
      <Handle type="target" position={targetPos} className="custom-handle" />

      <div className="node-header">
        <div className="node-title-group">
          <span className="node-type-prefix">[MQ]</span>
          <span className="node-title" title={node.name}>
            {node.name}
          </span>
        </div>
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          {(data.traceState === 'sink' || data.traceState === 'hop') && (
            <span className="node-badge badge-trace sink">[MQ/BROKER]</span>
          )}
          {data.isDeadCode && (
            <span className="node-badge badge-dead-code" title="Очередь не слушается активными потребителями">
              DEAD
            </span>
          )}
          <span className="node-badge badge-queue">MQ</span>
        </div>
      </div>

      <div className="node-body">
        {node.framework && (
          <div className="node-meta-row">
            <span className="meta-label">Broker:</span>
            <span className="meta-value">{node.framework}</span>
          </div>
        )}

        {node.destinations && node.destinations.length > 0 && (
          <div className="node-tags">
            {node.destinations.map((d) => (
              <span key={d.destination} className="tag-pill" title={`Routing: ${d.routingKey || d.destination}`}>
                <Layers size={10} style={{ display: 'inline', marginRight: 3, verticalAlign: 'middle' }} />
                {d.destination}
              </span>
            ))}
          </div>
        )}
      </div>

      <Handle type="source" position={sourcePos} className="custom-handle" />
    </div>
  );
});

QueueNode.displayName = 'QueueNode';
