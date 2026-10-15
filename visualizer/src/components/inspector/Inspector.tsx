import React, { useState } from 'react';
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
  Route,
} from 'lucide-react';
import type {
  CanonicalNode,
  CanonicalEdge,
  BlastRadiusResult,
  CanonicalGraph,
  CallTraceResult,
  EndpointInfo,
} from '../../types/graph';
import { EdgeRegistryTable } from './EdgeRegistryTable';
import './inspector.css';

interface InspectorProps {
  selectedEdge: CanonicalEdge | null;
  selectedNode: CanonicalNode | null;
  blastRadius: BlastRadiusResult | null;
  onActivateBlastRadius: (nodeId: string) => void;
  onClearBlastRadius: () => void;
  onClose: () => void;
  graph: CanonicalGraph;
  filteredEdges: CanonicalEdge[];
  onSelectEdge: (edgeId: string) => void;

  // Call Path Tracing
  callTrace: CallTraceResult | null;
  onActivateCallTrace: (serviceId: string, endpoint: EndpointInfo) => void;
  onClearCallTrace: () => void;
}

export const CallTraceCard: React.FC<{
  callTrace: CallTraceResult;
  onClearCallTrace: () => void;
}> = ({ callTrace, onClearCallTrace }) => {
  return (
    <div className="cad-card call-trace-card">
      <div className="card-section-title">
        <Route size={12} style={{ color: '#0969DA' }} />
        <span>СКВОЗНАЯ ТРАССИРОВКА ВЫЗОВА (CALL CHAIN)</span>
      </div>

      <div className="trace-header-info">
        <span className={`method-badge ${callTrace.rootHttpMethod.toLowerCase()}`}>
          {callTrace.rootHttpMethod}
        </span>
        <span className="trace-root-path">{callTrace.rootEndpointPath}</span>
      </div>

      <div className="cad-grid-row" style={{ marginTop: 6, marginBottom: 8 }}>
        <div className="metric-box-cad">
          <span className="metric-val" style={{ color: '#0969DA' }}>
            {callTrace.affectedNodeIds.size}
          </span>
          <span className="metric-lbl">УЗЛОВ В ЦЕПОЧКЕ</span>
        </div>
        <div className="metric-box-cad">
          <span className="metric-val" style={{ color: '#0369A1' }}>
            {callTrace.targetDatabases.length}
          </span>
          <span className="metric-lbl">ТАБЛИЦ БД</span>
        </div>
      </div>

      {/* Пошаговое дерево шагов вызова */}
      <div className="trace-steps-timeline">
        {callTrace.orderedSteps.map((step) => (
          <div
            key={step.stepIndex}
            className={`trace-step-item ${
              step.isDbAccess
                ? 'db-sink'
                : step.isMqPublish
                ? 'mq-sink'
                : step.stepIndex === 1
                ? 'controller-root'
                : 'service-hop'
            }`}
          >
            <div className="step-marker">
              <span className="marker-number">[{step.stepIndex}]</span>
            </div>
            <div className="step-content">
              <div className="step-title-row">
                <span className="step-service-name">{step.serviceName}</span>
                {step.targetRelation && (
                  <span className="step-protocol-badge">{step.targetRelation}</span>
                )}
              </div>
              {step.caller && (
                <div className="step-caller-text">{step.caller}</div>
              )}
              {step.targetServiceId && (
                <div className="step-target-row">
                  <ArrowRight size={10} className="step-arrow" />
                  <span className="step-target-name">{step.targetServiceId}</span>
                  {step.targetTable && (
                    <span className="step-table-badge">таблица: {step.targetTable}</span>
                  )}
                  {step.targetEndpoint && (
                    <span className="step-ep-text">{step.targetEndpoint}</span>
                  )}
                </div>
              )}
              {step.codeSnippet && (
                <pre className="trace-code-snippet">{step.codeSnippet}</pre>
              )}
            </div>
          </div>
        ))}
      </div>

      <button
        type="button"
        className="cad-action-btn blast-reset"
        onClick={onClearCallTrace}
        style={{ marginTop: 8 }}
      >
        СБРОСИТЬ ТРАССИРОВКУ ВЫЗОВА
      </button>
    </div>
  );
};

export const Inspector: React.FC<InspectorProps> = ({
  selectedEdge,
  selectedNode,
  blastRadius,
  onActivateBlastRadius,
  onClearBlastRadius,
  onClose,
  graph,
  filteredEdges,
  onSelectEdge,
  callTrace,
  onActivateCallTrace,
  onClearCallTrace,
}) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <aside className="inspector-sidebar" aria-label="Инспектор архитектурных доказательств">
      {/* Верхняя прокручиваемая область инспектора (Паспорт / Evidence / Blast Radius) */}
      <div className="inspector-scroll-area">
        {/* 1. Выбрано ребро: Evidence Log View */}
        {selectedEdge && (
          <div className="inspector-pane">
            <div className="inspector-pane-header">
              <div className="pane-title-group">
                <ShieldCheck size={14} style={{ color: 'var(--edge-ast)' }} />
                <span className="pane-title">ПАСПОРТ РЕБРА &bull; EVIDENCE LOG</span>
              </div>
              <button
                type="button"
                className="inspector-close-btn"
                onClick={onClose}
                title="Закрыть выбор"
              >
                <X size={13} />
              </button>
            </div>

            <div className="inspector-pane-body">
              {/* Блок 1: Паспорт выбранного элемента */}
              <div className="cad-card">
                <div className="card-section-title">СВЯЗЬ</div>
                <div className="edge-route-display">
                  <span className="mono-node-id">{selectedEdge.source}</span>
                  <ArrowRight size={12} className="route-arrow" />
                  <span className="mono-node-id">{selectedEdge.target}</span>
                </div>

                {(selectedEdge.isReachable === false || selectedEdge.evidenceDetails?.isReachable === false) && (
                  <div className="dead-code-alert-banner">
                    <AlertTriangle size={12} color="#DC2626" />
                    <span>НЕДОСТИЖИМО ИЗ ТОЧЕК ВХОДА (DEAD CODE)</span>
                  </div>
                )}

                <div className="cad-grid-row">
                  <div className="cad-field">
                    <span className="cad-field-label">ПРОТОКОЛ</span>
                    <span className="cad-field-value mono-val">{selectedEdge.relationType}</span>
                  </div>
                  <div className="cad-field">
                    <span className="cad-field-label">СЛОЙ ИСТОЧНИКА</span>
                    <span className="cad-field-value mono-val" style={{ fontWeight: 600 }}>
                      {selectedEdge.sourceType}
                    </span>
                  </div>
                </div>

                <div className="cad-field">
                  <div className="confidence-label-row">
                    <span className="cad-field-label">УВЕРЕННОСТЬ (CONFIDENCE)</span>
                    <span className="cad-field-value mono-val score-highlight">
                      {selectedEdge.confidence.toFixed(2)} ({Math.round(selectedEdge.confidence * 100)}%)
                    </span>
                  </div>
                  <div className="cad-meter-bar">
                    <div
                      className="cad-meter-fill"
                      style={{
                        width: `${Math.round(selectedEdge.confidence * 100)}%`,
                        backgroundColor:
                          selectedEdge.confidence >= 0.85
                            ? 'var(--edge-ast)'
                            : selectedEdge.confidence >= 0.5
                            ? 'var(--edge-ml)'
                            : 'var(--alert-blast)',
                      }}
                    />
                  </div>
                </div>
              </div>

              {/* Блок 2: Доказательство (Evidence Details) */}
              {selectedEdge.evidenceDetails && (
                <div className="cad-card">
                  <div className="card-section-title">
                    <FileCode size={12} />
                    <span>ДОКАЗАТЕЛЬНАЯ БАЗА (EVIDENCE.JSON)</span>
                  </div>

                  {selectedEdge.evidenceDetails.filePath && (
                    <div className="cad-field">
                      <span className="cad-field-label">ФАЙЛ И СТРОКА</span>
                      <div className="code-location-row">
                        <span className="mono-val location-path">
                          {selectedEdge.evidenceDetails.filePath}:{selectedEdge.evidenceDetails.lineNumber}
                        </span>
                        <button
                          type="button"
                          className="copy-btn"
                          onClick={() =>
                            handleCopy(
                              `${selectedEdge.evidenceDetails?.filePath}:${selectedEdge.evidenceDetails?.lineNumber}`
                            )
                          }
                          title="Скопировать путь к файлу"
                        >
                          {copied ? (
                            <Check size={12} style={{ color: 'var(--edge-ast)' }} />
                          ) : (
                            <Copy size={12} />
                          )}
                        </button>
                      </div>
                    </div>
                  )}

                  {selectedEdge.evidenceDetails.caller && (
                    <div className="cad-field">
                      <span className="cad-field-label">МЕТОД ВЫЗОВА (CALLER)</span>
                      <span className="cad-field-value mono-val">
                        {selectedEdge.evidenceDetails.caller}
                      </span>
                    </div>
                  )}

                  {selectedEdge.evidenceDetails.matchedEndpoint && (
                    <div className="cad-field">
                      <span className="cad-field-label">ЦЕЛЕВОЙ ЭНДПОИНТ / ШАБЛОН</span>
                      <span className="cad-field-value mono-val" style={{ color: 'var(--edge-ast)' }}>
                        {selectedEdge.evidenceDetails.matchedEndpoint}
                      </span>
                    </div>
                  )}

                  {selectedEdge.evidenceDetails.callChain &&
                    selectedEdge.evidenceDetails.callChain.length > 0 && (
                      <div className="cad-field">
                        <span className="cad-field-label">ЦЕПОЧКА ВЫЗОВОВ (CALL CHAIN)</span>
                        <div className="call-chain-cad">
                          {selectedEdge.evidenceDetails.callChain.map((step, idx) => (
                            <div key={step} className="call-chain-node">
                              <span className="step-num">[{idx + 1}]</span>
                              <span className="step-text">{step}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                  {selectedEdge.evidenceDetails.codeSnippet && (
                    <div className="cad-field">
                      <span className="cad-field-label">ФРАГМЕНТ КОДА</span>
                      <pre className="cad-code-snippet">
                        {selectedEdge.evidenceDetails.codeSnippet}
                      </pre>
                    </div>
                  )}

                  {/* Признаки ML-модели */}
                  {selectedEdge.sourceType === 'ML_PREDICTED' &&
                    selectedEdge.evidenceDetails.topFeatures && (
                      <div className="cad-field" style={{ marginTop: 4 }}>
                        <span className="cad-field-label">ML ПРИЗНАКИ (CATBOOST FEATURES)</span>
                        <div className="features-cad-grid">
                          {selectedEdge.evidenceDetails.topFeatures.jinaCodeSimilarity !== undefined && (
                            <div className="feature-cell">
                              <span className="feature-key">UniXcoder Sim</span>
                              <span className="feature-val">
                                {selectedEdge.evidenceDetails.topFeatures.jinaCodeSimilarity.toFixed(3)}
                              </span>
                            </div>
                          )}
                          {selectedEdge.evidenceDetails.topFeatures.dtoOverlapJaccard !== undefined && (
                            <div className="feature-cell">
                              <span className="feature-key">DTO Jaccard</span>
                              <span className="feature-val">
                                {selectedEdge.evidenceDetails.topFeatures.dtoOverlapJaccard.toFixed(3)}
                              </span>
                            </div>
                          )}
                          {selectedEdge.evidenceDetails.topFeatures.bm25TokenSimilarity !== undefined && (
                            <div className="feature-cell">
                              <span className="feature-key">BM25 Tokens</span>
                              <span className="feature-val">
                                {selectedEdge.evidenceDetails.topFeatures.bm25TokenSimilarity.toFixed(3)}
                              </span>
                            </div>
                          )}
                          {selectedEdge.evidenceDetails.topFeatures.adamicAdarIndex !== undefined && (
                            <div className="feature-cell">
                              <span className="feature-key">Adamic-Adar</span>
                              <span className="feature-val">
                                {selectedEdge.evidenceDetails.topFeatures.adamicAdarIndex.toFixed(3)}
                              </span>
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                  {/* Вердикт LLM-Judge */}
                  {selectedEdge.sourceType === 'LLM_JUDGE_VERIFIED' &&
                    selectedEdge.evidenceDetails.llmVerdict && (
                      <div className="llm-cad-verdict">
                        <div className="verdict-header">
                          <span className="verdict-tag">
                            {selectedEdge.evidenceDetails.llmVerdict.verdict}
                          </span>
                          <span className="mono-val" style={{ fontSize: 10, color: '#047857' }}>
                            Score: {Math.round(selectedEdge.evidenceDetails.llmVerdict.confidence * 100)}%
                          </span>
                        </div>
                        <div className="verdict-reasoning">
                          {selectedEdge.evidenceDetails.llmVerdict.reasoning}
                        </div>
                      </div>
                    )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* 2. Выбран узел: Blast Radius & Node Inspector */}
        {!selectedEdge && selectedNode && (
          <div className="inspector-pane">
            <div className="inspector-pane-header">
              <div className="pane-title-group">
                <AlertTriangle size={14} style={{ color: 'var(--alert-blast)' }} />
                <span className="pane-title">ПАСПОРТ УЗЛА &bull; BLAST RADIUS</span>
              </div>
              <button
                type="button"
                className="inspector-close-btn"
                onClick={onClose}
                title="Сбросить выбор"
              >
                <X size={13} />
              </button>
            </div>

            <div className="inspector-pane-body">
              {/* Паспорт узла */}
              <div className="cad-card">
                <div className="card-section-title">
                  {selectedNode.type === 'SERVICE' ? (
                    <Server size={12} />
                  ) : selectedNode.type === 'DATABASE' ? (
                    <Database size={12} />
                  ) : (
                    <Radio size={12} />
                  )}
                  <span>ТИП: {selectedNode.type}</span>
                </div>

                <div className="mono-node-name">{selectedNode.name}</div>

                {selectedNode.description && (
                  <div className="node-description-text">{selectedNode.description}</div>
                )}

                <div className="cad-grid-row">
                  {selectedNode.serverPort && (
                    <div className="cad-field">
                      <span className="cad-field-label">ПОРТ СЕРВЕРА</span>
                      <span className="cad-field-value mono-val">{selectedNode.serverPort}</span>
                    </div>
                  )}
                  {selectedNode.framework && (
                    <div className="cad-field">
                      <span className="cad-field-label">СТЕК / ФРЕЙМВОРК</span>
                      <span className="cad-field-value mono-val">{selectedNode.framework}</span>
                    </div>
                  )}
                </div>

                {selectedNode.contextPath && (
                  <div className="cad-field">
                    <span className="cad-field-label">КОНТЕКСТНЫЙ ПУТЬ API</span>
                    <span className="cad-field-value mono-val">{selectedNode.contextPath}</span>
                  </div>
                )}

                {/* Входящие эндпоинты */}
                {selectedNode.endpoints && selectedNode.endpoints.length > 0 && (
                  <div className="cad-field" style={{ marginTop: 6 }}>
                    <span className="cad-field-label">
                      ВХОДЯЩИЕ ЭНДПОИНТЫ ({selectedNode.endpoints.length})
                    </span>
                    <div className="endpoints-cad-list">
                      {selectedNode.endpoints.map((ep) => {
                        const isDead = ep.isReachable === false;
                        const isCurrentlyTraced = callTrace?.rootEndpointId === ep.id;
                        return (
                          <div
                            key={ep.id}
                            className={`endpoint-cad-item ${isDead ? 'dead-endpoint' : ''} ${isCurrentlyTraced ? 'traced-endpoint' : ''}`}
                            title={ep.handlerClass ? `${ep.handlerClass}.${ep.handlerMethod}` : ep.path}
                          >
                            <span className={`method-badge ${ep.httpMethod.toLowerCase()}`}>
                              {ep.httpMethod}
                            </span>
                            <span className="endpoint-path-text">{ep.path}</span>
                            {ep.handlerMethod && (
                              <span className="endpoint-handler-text">.{ep.handlerMethod}()</span>
                            )}
                            {isDead && (
                              <span className="endpoint-dead-badge">DEAD</span>
                            )}
                            <button
                              type="button"
                              className={`endpoint-trace-btn ${isCurrentlyTraced ? 'active' : ''}`}
                              onClick={(e) => {
                                e.stopPropagation();
                                if (isCurrentlyTraced) {
                                  onClearCallTrace();
                                } else {
                                  onActivateCallTrace(selectedNode.id, ep);
                                }
                              }}
                              title={isCurrentlyTraced ? 'Сбросить трассировку' : 'Трассировать сквозную цепочку вызовов'}
                            >
                              <Route size={10} />
                              <span>{isCurrentlyTraced ? 'СБРОС' : 'ТРЕЙС'}</span>
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Таблицы базы данных */}
                {selectedNode.tables && selectedNode.tables.length > 0 && (
                  <div className="cad-field" style={{ marginTop: 6 }}>
                    <span className="cad-field-label">
                      ТАБЛИЦЫ БД ({selectedNode.tables.length})
                    </span>
                    <div className="endpoints-cad-list">
                      {selectedNode.tables.map((t, idx) => (
                        <div key={idx} className="endpoint-cad-item">
                          <span className="method-badge db">{t.operation}</span>
                          <span className="endpoint-path-text">{t.tableName}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Очереди сообщений */}
                {selectedNode.destinations && selectedNode.destinations.length > 0 && (
                  <div className="cad-field" style={{ marginTop: 6 }}>
                    <span className="cad-field-label">
                      ОЧЕРЕДИ / ТОПИКИ ({selectedNode.destinations.length})
                    </span>
                    <div className="endpoints-cad-list">
                      {selectedNode.destinations.map((q, idx) => (
                        <div key={idx} className="endpoint-cad-item">
                          <span className="method-badge mq">{q.role}</span>
                          <span className="endpoint-path-text">{q.destination}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Панель сквозной трассировки (если активна для этого или смежного узла) */}
              {callTrace && (
                <CallTraceCard callTrace={callTrace} onClearCallTrace={onClearCallTrace} />
              )}

              {/* Анализатор Blast Radius */}
              <div className="cad-card">
                <div className="card-section-title">
                  <Zap size={12} style={{ color: 'var(--alert-blast)' }} />
                  <span>АНАЛИЗАТОР BLAST RADIUS (РАДИУС ПОРАЖЕНИЯ)</span>
                </div>

                {blastRadius?.rootNodeId === selectedNode.id ? (
                  <button
                    type="button"
                    className="cad-action-btn blast-reset"
                    onClick={onClearBlastRadius}
                  >
                    СБРОСИТЬ ПОДСВЕТКУ ГРАФА
                  </button>
                ) : (
                  <button
                    type="button"
                    className="cad-action-btn blast-trigger"
                    onClick={() => onActivateBlastRadius(selectedNode.id)}
                  >
                    РАССЧИТАТЬ BLAST RADIUS
                  </button>
                )}

                {blastRadius && blastRadius.rootNodeId === selectedNode.id && (
                  <div className="blast-report-section">
                    <div className="cad-grid-row">
                      <div className="metric-box-cad">
                        <span className="metric-val">
                          {blastRadius.allAffectedNodeIds.size - 1}
                        </span>
                        <span className="metric-lbl">ЗАВИСИМЫХ УЗЛОВ</span>
                      </div>
                      <div className="metric-box-cad">
                        <span className="metric-val">{blastRadius.depth}</span>
                        <span className="metric-lbl">ГЛУБИНА ЦЕПОЧКИ</span>
                      </div>
                    </div>

                    {blastRadius.upstreamNodeIds.size > 0 && (
                      <div className="cad-field">
                        <span className="cad-field-label">
                          UPSTREAM (КЛИЕНТЫ: {blastRadius.upstreamNodeIds.size})
                        </span>
                        <div className="affected-list-cad">
                          {Array.from(blastRadius.upstreamNodeIds).map((id) => (
                            <div key={id} className="affected-row upstream">
                              &larr; {id}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {blastRadius.downstreamNodeIds.size > 0 && (
                      <div className="cad-field">
                        <span className="cad-field-label">
                          DOWNSTREAM (ПРЯМЫЕ ВЫЗОВЫ: {blastRadius.downstreamNodeIds.size})
                        </span>
                        <div className="affected-list-cad">
                          {Array.from(blastRadius.downstreamNodeIds).map((id) => (
                            <div key={id} className="affected-row downstream">
                              &rarr; {id}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {blastRadius.transitiveNodeIds.size > 0 && (
                      <div className="cad-field">
                        <span className="cad-field-label">
                          ТРАНЗИТИВНЫЕ ЗАВИСИМОСТИ ({blastRadius.transitiveNodeIds.size})
                        </span>
                        <div className="affected-list-cad">
                          {Array.from(blastRadius.transitiveNodeIds).map((id) => (
                            <div key={id} className="affected-row transitive">
                              &hellip; {id}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* 3. Ничего не выбрано: Общая сводка архитектурного графа или активный Трейс */}
        {!selectedEdge && !selectedNode && (
          <div className="inspector-pane">
            <div className="inspector-pane-header">
              <div className="pane-title-group">
                {callTrace ? (
                  <>
                    <Route size={14} style={{ color: '#0969DA' }} />
                    <span className="pane-title">СКВОЗНАЯ ТРАССИРОВКА ВЫЗОВА</span>
                  </>
                ) : (
                  <>
                    <Info size={14} style={{ color: 'var(--text-muted)' }} />
                    <span className="pane-title">СВОДКА ТОПОЛОГИИ ГРАФА</span>
                  </>
                )}
              </div>
              {callTrace && (
                <button
                  type="button"
                  className="inspector-close-btn"
                  onClick={onClearCallTrace}
                  title="Сбросить трассировку"
                >
                  <X size={13} />
                </button>
              )}
            </div>

            <div className="inspector-pane-body">
              {callTrace ? (
                <CallTraceCard callTrace={callTrace} onClearCallTrace={onClearCallTrace} />
              ) : (
                <>
                  <div className="cad-card">
                    <div className="card-section-title">СТАТИСТИКА АРХИТЕКТУРЫ</div>
                <div className="cad-grid-row">
                  <div className="metric-box-cad">
                    <span className="metric-val">
                      {graph.nodes.filter((n) => n.type === 'SERVICE').length}
                    </span>
                    <span className="metric-lbl">СЕРВИСОВ</span>
                  </div>
                  <div className="metric-box-cad">
                    <span className="metric-val">{graph.edges.length}</span>
                    <span className="metric-lbl">ВСЕГО РЁБЕР</span>
                  </div>
                </div>

                <div className="cad-grid-row" style={{ marginTop: 6 }}>
                  <div className="metric-box-cad">
                    <span className="metric-val" style={{ color: 'var(--edge-config)' }}>
                      {graph.nodes.filter((n) => n.type === 'DATABASE').length}
                    </span>
                    <span className="metric-lbl">БАЗ ДАННЫХ</span>
                  </div>
                  <div className="metric-box-cad">
                    <span className="metric-val" style={{ color: 'var(--border-strong)' }}>
                      {graph.nodes.filter((n) => n.type === 'MESSAGE_QUEUE').length}
                    </span>
                    <span className="metric-lbl">ОЧЕРЕДЕЙ MQ</span>
                  </div>
                </div>
              </div>

              <div className="cad-card intro-hint">
                <div className="hint-title">ИНЖЕНЕРНАЯ ОТЛАДКА</div>
                <div className="hint-text">
                  &bull; Кликните на любое <strong>ребро</strong> на графе или строчку в таблице ниже для просмотра записи <code>evidence.json</code> (файл, строка, сниппет вызова).
                  <br /><br />
                  &bull; Выберите <strong>узел сервиса</strong> для активации режима симуляции отказа и подсветки <strong>Blast Radius</strong>.
                </div>
              </div>
            </>
          )}
        </div>
      </div>
        )}
      </div>

      {/* Нижняя область инспектора: Табличный реестр рёбер (Блок 3 DESIGN.md) */}
      <div className="inspector-registry-pane">
        <EdgeRegistryTable
          edges={filteredEdges}
          selectedEdgeId={selectedEdge?.id || null}
          onSelectEdge={onSelectEdge}
        />
      </div>
    </aside>
  );
};
