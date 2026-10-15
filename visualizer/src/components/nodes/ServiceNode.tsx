import React, { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { Server, Cpu } from 'lucide-react';
import type { NodeProps } from '@xyflow/react';
import type { NodeData } from '../../adapters/graphAdapter';
import './nodes.css';

export const ServiceNode: React.FC<NodeProps> = memo((props) => {
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
    <div className={`custom-node service-node ${blastClass} ${searchClass}`}>
      <Handle type="target" position={targetPos} className="custom-handle" />

      <div className="node-header">
        <div className="node-title-group">
          <div className="node-icon">
            <Server size={16} />
          </div>
          <span className="node-title" title={node.name}>
            {node.name}
          </span>
        </div>
        <span className="node-badge badge-service">
          {node.language || 'Java'}
        </span>
      </div>

      <div className="node-body">
        {node.serverPort && (
          <div className="node-meta-row">
            <span className="meta-label">Port:</span>
            <span className="meta-value">{node.serverPort}</span>
          </div>
        )}
        {node.contextPath && (
          <div className="node-meta-row">
            <span className="meta-label">Path:</span>
            <span className="meta-value" title={node.contextPath}>
              {node.contextPath}
            </span>
          </div>
        )}
        {node.endpoints && node.endpoints.length > 0 && (
          <div className="node-tags">
            <span className="tag-pill">
              <Cpu size={10} style={{ display: 'inline', marginRight: 3, verticalAlign: 'middle' }} />
              {node.endpoints.length} endpoints
            </span>
            {node.framework && (
              <span className="tag-pill">{node.framework}</span>
            )}
          </div>
        )}
      </div>

      <Handle type="source" position={sourcePos} className="custom-handle" />
    </div>
  );
});

ServiceNode.displayName = 'ServiceNode';
