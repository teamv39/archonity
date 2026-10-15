import React, { useState, useMemo } from 'react';
import { ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react';
import type { CanonicalEdge } from '../../types/graph';

interface EdgeRegistryTableProps {
  edges: CanonicalEdge[];
  selectedEdgeId: string | null;
  onSelectEdge: (edgeId: string) => void;
}

type SortField = 'source' | 'target' | 'relation' | 'sourceType' | 'confidence';
type SortOrder = 'asc' | 'desc';

export const EdgeRegistryTable: React.FC<EdgeRegistryTableProps> = ({
  edges,
  selectedEdgeId,
  onSelectEdge,
}) => {
  const [sortField, setSortField] = useState<SortField>('confidence');
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc');

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortOrder(field === 'confidence' ? 'desc' : 'asc');
    }
  };

  const sortedEdges = useMemo(() => {
    return [...edges].sort((a, b) => {
      let cmp = 0;
      if (sortField === 'confidence') {
        cmp = a.confidence - b.confidence;
      } else if (sortField === 'source') {
        cmp = a.source.localeCompare(b.source);
      } else if (sortField === 'target') {
        cmp = a.target.localeCompare(b.target);
      } else if (sortField === 'relation') {
        cmp = a.relationType.localeCompare(b.relationType);
      } else if (sortField === 'sourceType') {
        cmp = a.sourceType.localeCompare(b.sourceType);
      }
      return sortOrder === 'asc' ? cmp : -cmp;
    });
  }, [edges, sortField, sortOrder]);

  const renderSortIcon = (field: SortField) => {
    if (sortField !== field) {
      return <ArrowUpDown size={10} className="table-sort-icon neutral" />;
    }
    return sortOrder === 'asc' ? (
      <ArrowUp size={10} className="table-sort-icon active" />
    ) : (
      <ArrowDown size={10} className="table-sort-icon active" />
    );
  };

  return (
    <div className="registry-table-container">
      <div className="registry-table-header">
        <div className="registry-title">
          <span>РЕЕСТР РЁБЕР</span>
          <span className="registry-count">[{edges.length}]</span>
        </div>
      </div>

      <div className="registry-table-scroll">
        <table className="registry-table">
          <thead>
            <tr>
              <th onClick={() => handleSort('source')} title="Сортировка по источнику">
                <span>ИСТОЧНИК</span>
                {renderSortIcon('source')}
              </th>
              <th onClick={() => handleSort('target')} title="Сортировка по цели">
                <span>ЦЕЛЬ</span>
                {renderSortIcon('target')}
              </th>
              <th onClick={() => handleSort('relation')} title="Сортировка по протоколу">
                <span>ПРОТОКОЛ</span>
                {renderSortIcon('relation')}
              </th>
              <th onClick={() => handleSort('sourceType')} title="Сортировка по слою">
                <span>СЛОЙ</span>
                {renderSortIcon('sourceType')}
              </th>
              <th onClick={() => handleSort('confidence')} title="Сортировка по уверенности" style={{ textAlign: 'right' }}>
                <span>СКОР</span>
                {renderSortIcon('confidence')}
              </th>
            </tr>
          </thead>
          <tbody>
            {sortedEdges.length === 0 ? (
              <tr>
                <td colSpan={5} className="table-empty-row">
                  Нет активных рёбер (проверьте фильтры слоев и порог ML)
                </td>
              </tr>
            ) : (
              sortedEdges.map((edge) => {
                const isSelected = edge.id === selectedEdgeId;
                const shortRel =
                  edge.relationType === 'REST_HTTP'
                    ? 'HTTP'
                    : edge.relationType === 'DATABASE'
                    ? 'DB'
                    : edge.relationType === 'MESSAGE_QUEUE'
                    ? 'MQ'
                    : 'TRANS';

                let layerClass = 'layer-ast';
                if (edge.sourceType === 'CONFIG') layerClass = 'layer-cfg';
                else if (edge.sourceType === 'ML_PREDICTED') layerClass = 'layer-ml';
                else if (edge.sourceType === 'LLM_JUDGE_VERIFIED') layerClass = 'layer-llm';
                else if (edge.sourceType === 'TRANSITIVE') layerClass = 'layer-trans';

                return (
                  <tr
                    key={edge.id}
                    className={`registry-row ${isSelected ? 'row-selected' : ''}`}
                    onClick={() => onSelectEdge(edge.id)}
                  >
                    <td className="mono-cell cell-source" title={edge.source}>
                      {edge.source}
                    </td>
                    <td className="mono-cell cell-target" title={edge.target}>
                      {edge.target}
                    </td>
                    <td className="cell-proto">
                      <span className="proto-tag">{shortRel}</span>
                    </td>
                    <td className="cell-layer">
                      <span className={`layer-badge ${layerClass}`}>
                        {edge.sourceType === 'AST_EXACT'
                          ? 'AST'
                          : edge.sourceType === 'CONFIG'
                          ? 'CFG'
                          : edge.sourceType === 'ML_PREDICTED'
                          ? 'ML'
                          : edge.sourceType === 'LLM_JUDGE_VERIFIED'
                          ? 'LLM'
                          : 'TRANS'}
                      </span>
                    </td>
                    <td className="mono-cell cell-score" style={{ textAlign: 'right' }}>
                      {edge.confidence.toFixed(2)}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
