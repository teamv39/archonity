import React from 'react';
import {
  X,
  FileCode,
  ShieldCheck,
  AlertTriangle,
  Zap,
  ArrowRight,
  Copy,
  Check,
  Info,
  Server,
  Database,
  Radio,
} from 'lucide-react';
import type {
  CanonicalNode,
  CanonicalEdge,
  BlastRadiusResult,
  CanonicalGraph,
} from '../../types/graph';
import './inspector.css';

interface InspectorProps {
  selectedEdge: CanonicalEdge | null;
  selectedNode: CanonicalNode | null;
  blastRadius: BlastRadiusResult | null;
  onActivateBlastRadius: (nodeId: string) => void;
  onClearBlastRadius: () => void;
  onClose: () => void;
  graph: CanonicalGraph;
}

export const Inspector: React.FC<InspectorProps> = ({
  selectedEdge,
  selectedNode,
  blastRadius,
  onActivateBlastRadius,
  onClearBlastRadius,
  onClose,
  graph,
}) => {
  const [copied, setCopied] = React.useState(false);

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  // 1. Отображение информации о выбранном ребре (Evidence Log)
  if (selectedEdge) {
    const evi = selectedEdge.evidenceDetails;
    const isLLM = selectedEdge.sourceType === 'LLM_JUDGE_VERIFIED';
    const isML = selectedEdge.sourceType === 'ML_PREDICTED';
    const percent = Math.round(selectedEdge.confidence * 100);

    return (
      <div className="inspector-sidebar">
        <div className="inspector-header">
          <div className="inspector-title-group">
            <ShieldCheck size={16} style={{ color: '#38bdf8' }} />
            <span className="inspector-title">Evidence Log Inspector</span>
          </div>
          <button type="button" className="inspector-close-btn" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        <div className="inspector-content">
          {/* Сводка связи */}
          <div className="inspector-card">
            <div className="card-title">Связь</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 600 }}>
              <span className="mono-val" style={{ color: '#38bdf8' }}>{selectedEdge.source}</span>
              <ArrowRight size={14} style={{ color: '#64748b' }} />
              <span className="mono-val" style={{ color: '#a855f7' }}>{selectedEdge.target}</span>
            </div>

            <div className="meta-field" style={{ marginTop: 6 }}>
              <span className="meta-field-label">Тип протокола / Отношение</span>
              <span className="meta-field-value mono-val">{selectedEdge.relationType}</span>
            </div>

            <div className="meta-field">
              <span className="meta-field-label">Источник доказательства</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 2 }}>
                <span className="mono-val" style={{ fontWeight: 600 }}>{selectedEdge.sourceType}</span>
              </div>
            </div>

            <div className="meta-field">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="meta-field-label">Уверенность (Confidence)</span>
                <span className="mono-val" style={{ fontSize: 11, fontWeight: 700, color: '#10b981' }}>
                  {percent}%
                </span>
              </div>
              <div className="confidence-bar-bg">
                <div
                  className="confidence-bar-fill"
                  style={{
                    width: `${percent}%`,
                    backgroundColor: percent >= 85 ? '#10b981' : percent >= 50 ? '#f59e0b' : '#ef4444',
                  }}
                />
              </div>
            </div>
          </div>

          {/* Источник в коде */}
          {evi?.filePath && (
            <div className="inspector-card">
              <div className="card-title">
                <FileCode size={13} />
                <span>Локация в исходном коде</span>
              </div>

              <div className="meta-field">
                <span className="meta-field-label">Файл и строка</span>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
                  <span className="meta-field-value mono-val" style={{ fontSize: 11 }}>
                    {evi.filePath}:{evi.lineNumber}
                  </span>
                  <button
                    type="button"
                    onClick={() => handleCopy(`${evi.filePath}:${evi.lineNumber}`)}
                    style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer' }}
                    title="Скопировать путь"
                  >
                    {copied ? <Check size={14} style={{ color: '#10b981' }} /> : <Copy size={14} />}
                  </button>
                </div>
              </div>

              {evi.caller && (
                <div className="meta-field">
                  <span className="meta-field-label">Метод вызова</span>
                  <span className="meta-field-value mono-val">{evi.caller}</span>
                </div>
              )}

              {evi.matchedEndpoint && (
                <div className="meta-field">
                  <span className="meta-field-label">Целевой эндпоинт</span>
                  <span className="meta-field-value mono-val" style={{ color: '#10b981' }}>
                    {evi.matchedEndpoint}
                  </span>
                </div>
              )}

              {evi.callChain && evi.callChain.length > 0 && (
                <div className="meta-field">
                  <span className="meta-field-label">Цепочка вызовов (Call Chain)</span>
                  <div className="call-chain-list" style={{ marginTop: 4 }}>
                    {evi.callChain.map((step) => (
                      <div key={step} className="call-chain-item">
                        {step}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {evi.codeSnippet && (
                <div className="meta-field">
                  <span className="meta-field-label">Сниппет кода</span>
                  <pre className="code-box">{evi.codeSnippet}</pre>
                </div>
              )}
            </div>
          )}

          {/* LLM-as-a-Judge Арбитраж */}
          {isLLM && evi?.llmVerdict && (
            <div className="inspector-card">
              <div className="card-title">
                <Zap size={13} style={{ color: '#10b981' }} />
                <span>Арбитраж LLM-as-a-Judge</span>
              </div>

              <div className="llm-verdict-box">
                <div className="llm-verdict-header">
                  <span className="llm-badge">{evi.llmVerdict.verdict}</span>
                  <span className="mono-val" style={{ fontSize: 10, color: '#10b981' }}>
                    Score: {Math.round(evi.llmVerdict.confidence * 100)}%
                  </span>
                </div>
                <div className="llm-reasoning">{evi.llmVerdict.reasoning}</div>
              </div>
            </div>
          )}

          {/* Признаки ML-модели */}
          {isML && evi?.topFeatures && (
            <div className="inspector-card">
              <div className="card-title">
                <Zap size={13} style={{ color: '#ec4899' }} />
                <span>Признаки ML (CatBoost Features)</span>
              </div>

              <div className="features-grid">
                {evi.topFeatures.jinaCodeSimilarity !== undefined && (
                  <div className="feature-item">
                    <span className="feature-label">UniXcoder Sim</span>
                    <span className="feature-value">{evi.topFeatures.jinaCodeSimilarity.toFixed(3)}</span>
                  </div>
                )}
                {evi.topFeatures.dtoOverlapJaccard !== undefined && (
                  <div className="feature-item">
                    <span className="feature-label">DTO Jaccard</span>
                    <span className="feature-value">{evi.topFeatures.dtoOverlapJaccard.toFixed(3)}</span>
                  </div>
                )}
                {evi.topFeatures.bm25TokenSimilarity !== undefined && (
                  <div className="feature-item">
                    <span className="feature-label">BM25 Tokens</span>
                    <span className="feature-value">{evi.topFeatures.bm25TokenSimilarity.toFixed(3)}</span>
                  </div>
                )}
                {evi.topFeatures.adamicAdarIndex !== undefined && (
                  <div className="feature-item">
                    <span className="feature-label">Adamic-Adar</span>
                    <span className="feature-value">{evi.topFeatures.adamicAdarIndex.toFixed(3)}</span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  // 2. Отображение информации об узле и Blast Radius
  if (selectedNode) {
    const isRootInBlast = blastRadius?.rootNodeId === selectedNode.id;

    return (
      <div className="inspector-sidebar">
        <div className="inspector-header">
          <div className="inspector-title-group">
            <AlertTriangle size={16} style={{ color: '#f59e0b' }} />
            <span className="inspector-title">Node & Blast Radius</span>
          </div>
          <button type="button" className="inspector-close-btn" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        <div className="inspector-content">
          {/* Инфо об узле */}
          <div className="inspector-card">
            <div className="card-title">
              {selectedNode.type === 'SERVICE' ? (
                <Server size={14} style={{ color: '#38bdf8' }} />
              ) : selectedNode.type === 'DATABASE' ? (
                <Database size={14} style={{ color: '#f59e0b' }} />
              ) : (
                <Radio size={14} style={{ color: '#a855f7' }} />
              )}
              <span>{selectedNode.type}</span>
            </div>

            <div style={{ fontSize: 14, fontWeight: 700, color: '#f8fafc' }}>
              {selectedNode.name}
            </div>

            {selectedNode.description && (
              <div style={{ fontSize: 11, color: '#94a3b8', lineHeight: 1.4 }}>
                {selectedNode.description}
              </div>
            )}

            {selectedNode.serverPort && (
              <div className="meta-field">
                <span className="meta-field-label">Порт</span>
                <span className="meta-value">{selectedNode.serverPort}</span>
              </div>
            )}

            {selectedNode.contextPath && (
              <div className="meta-field">
                <span className="meta-field-label">Базовый путь API</span>
                <span className="meta-value">{selectedNode.contextPath}</span>
              </div>
            )}
          </div>

          {/* Интерактивный расчет Blast Radius */}
          <div className="inspector-card">
            <div className="card-title">
              <Zap size={14} style={{ color: '#ef4444' }} />
              <span>Анализ Blast Radius</span>
            </div>

            {isRootInBlast ? (
              <button
                type="button"
                className="blast-btn blast-btn-reset"
                onClick={onClearBlastRadius}
              >
                Сбросить подсветку графа
              </button>
            ) : (
              <button
                type="button"
                className="blast-btn blast-btn-activate"
                onClick={() => onActivateBlastRadius(selectedNode.id)}
              >
                Рассчитать Blast Radius
              </button>
            )}

            {blastRadius && blastRadius.rootNodeId === selectedNode.id && (
              <>
                <div className="blast-metrics">
                  <div className="metric-box">
                    <div className="metric-val">{blastRadius.allAffectedNodeIds.size - 1}</div>
                    <div className="metric-name">Зависимых узлов</div>
                  </div>
                  <div className="metric-box">
                    <div className="metric-val">{blastRadius.depth}</div>
                    <div className="metric-name">Глубина влияния</div>
                  </div>
                </div>

                {blastRadius.upstreamNodeIds.size > 0 && (
                  <div className="meta-field">
                    <span className="meta-field-label">
                      Upstream (Вызывающие сервисы: {blastRadius.upstreamNodeIds.size})
                    </span>
                    <div className="affected-list">
                      {Array.from(blastRadius.upstreamNodeIds).map((id) => (
                        <div key={id} className="affected-item">
                          {id}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {blastRadius.downstreamNodeIds.size > 0 && (
                  <div className="meta-field">
                    <span className="meta-field-label">
                      Downstream (Прямые вызовы: {blastRadius.downstreamNodeIds.size})
                    </span>
                    <div className="affected-list">
                      {Array.from(blastRadius.downstreamNodeIds).map((id) => (
                        <div key={id} className="affected-item downstream">
                          {id}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {blastRadius.transitiveNodeIds.size > 0 && (
                  <div className="meta-field">
                    <span className="meta-field-label">
                      Транзитивные сервисы ({blastRadius.transitiveNodeIds.size})
                    </span>
                    <div className="affected-list">
                      {Array.from(blastRadius.transitiveNodeIds).map((id) => (
                        <div key={id} className="affected-item transitive">
                          {id}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    );
  }

  // 3. Пустое состояние (общая сводка графа)
  const serviceCount = graph.nodes.filter((n) => n.type === 'SERVICE').length;
  const dbCount = graph.nodes.filter((n) => n.type === 'DATABASE').length;
  const queueCount = graph.nodes.filter((n) => n.type === 'MESSAGE_QUEUE').length;

  return (
    <div className="inspector-sidebar">
      <div className="inspector-header">
        <div className="inspector-title-group">
          <Info size={16} style={{ color: '#94a3b8' }} />
          <span className="inspector-title">Сводка архитектурного графа</span>
        </div>
      </div>

      <div className="inspector-content">
        <div className="inspector-card">
          <div className="card-title">Топология</div>
          <div className="blast-metrics">
            <div className="metric-box">
              <div className="metric-val">{serviceCount}</div>
              <div className="metric-name">Микросервисов</div>
            </div>
            <div className="metric-box">
              <div className="metric-val">{graph.edges.length}</div>
              <div className="metric-name">Всего связей</div>
            </div>
          </div>
          <div className="blast-metrics">
            <div className="metric-box">
              <div className="metric-val" style={{ color: '#f59e0b' }}>{dbCount}</div>
              <div className="metric-name">Баз данных</div>
            </div>
            <div className="metric-box">
              <div className="metric-val" style={{ color: '#a855f7' }}>{queueCount}</div>
              <div className="metric-name">Очередей MQ</div>
            </div>
          </div>
        </div>

        <div className="empty-state">
          <Info size={32} className="empty-icon" />
          <div className="empty-text">
            Кликните на любое <strong>ребро</strong> на холсте, чтобы увидеть запись из <strong>Evidence Log</strong> (файл, строка, сниппет кода, вердикт арбитра).
            <br /><br />
            Или выберите <strong>узел сервиса</strong> для расчета и интерактивной подсветки <strong>Blast Radius</strong>.
          </div>
        </div>
      </div>
    </div>
  );
};
