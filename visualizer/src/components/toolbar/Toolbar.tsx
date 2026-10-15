import React, { useState, useRef, useEffect } from 'react';
import {
  Search,
  RotateCcw,
  Palette,
  ArrowRight,
  ArrowDown,
  X,
  Upload,
  Download,
  ChevronDown,
  Image,
  Code,
  FileCode,
  Activity,
  Eye,
  EyeOff,
  Route,
} from 'lucide-react';
import type {
  SourceType,
  ColorMode,
  DagDirection,
  ReachabilityMode,
  DeadCodeDisplay,
  CallTraceResult,
} from '../../types/graph';
import './toolbar.css';

interface ToolbarProps {
  confidenceThreshold: number;
  onThresholdChange: (val: number) => void;
  activeSources: Record<SourceType, boolean>;
  onToggleSource: (src: SourceType) => void;
  colorMode: ColorMode;
  onToggleColorMode: () => void;
  direction: DagDirection;
  onToggleDirection: () => void;
  searchQuery: string;
  onSearchChange: (q: string) => void;
  onResetAll: () => void;
  totalEdgesCount: number;
  visibleEdgesCount: number;
  nodesCount: number;
  transitiveEdgesCount: number;

  // Датасет и интеграция
  datasetName: string;
  isCustomDataset: boolean;
  onOpenDataLoader: () => void;

  // Экспорт
  onExportPng: () => void;
  onExportSvg: () => void;
  onExportJson: () => void;
  isExporting: boolean;

  // Reachability & Dead Code
  reachabilityMode: ReachabilityMode;
  onToggleReachabilityMode: () => void;
  deadCodeDisplay: DeadCodeDisplay;
  onToggleDeadCodeDisplay: () => void;
  unreachableEdgesCount: number;

  // Call Path Tracing
  callTrace: CallTraceResult | null;
  onClearCallTrace: () => void;
}

export const Toolbar: React.FC<ToolbarProps> = ({
  confidenceThreshold,
  onThresholdChange,
  activeSources,
  onToggleSource,
  colorMode,
  onToggleColorMode,
  direction,
  onToggleDirection,
  searchQuery,
  onSearchChange,
  onResetAll,
  totalEdgesCount,
  visibleEdgesCount,
  nodesCount,
  transitiveEdgesCount,
  datasetName,
  isCustomDataset,
  onOpenDataLoader,
  onExportPng,
  onExportSvg,
  onExportJson,
  isExporting,
  reachabilityMode,
  onToggleReachabilityMode,
  deadCodeDisplay,
  onToggleDeadCodeDisplay,
  unreachableEdgesCount,
  callTrace,
  onClearCallTrace,
}) => {
  const filteredCount = totalEdgesCount - visibleEdgesCount;
  const [isExportMenuOpen, setIsExportMenuOpen] = useState(false);
  const exportRef = useRef<HTMLDivElement>(null);

  // Закрытие меню экспорта по клику вне
  useEffect(() => {
    if (!isExportMenuOpen) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (exportRef.current && !exportRef.current.contains(e.target as Node)) {
        setIsExportMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isExportMenuOpen]);

  return (
    <header className="control-bar" role="toolbar" aria-label="Панель управления графом">
      {/* 1. Бренд */}
      <div className="bar-section brand-section">
        <span className="brand-logo">[ARCHONITY]</span>
        <span className="brand-sub">WORKBENCH</span>
      </div>

      <div className="section-divider" />

      {/* 2. Датасет */}
      <div className="bar-section dataset-section">
        <span className="section-caption">ДАТАСЕТ:</span>
        <button
          type="button"
          className={`cad-btn dataset-btn ${isCustomDataset ? 'custom' : ''}`}
          onClick={onOpenDataLoader}
          title="Загрузить файлы пайплайна (Drag & Drop, confirmed_edges.json, evidence.json)"
        >
          <Upload size={11} />
          <span className="dataset-label">{datasetName}</span>
          <ChevronDown size={10} style={{ opacity: 0.6 }} />
        </button>
      </div>

      <div className="section-divider" />

      {/* 3. Переключатели слоев */}
      <div className="bar-section layers-section">
        <span className="section-caption">СЛОИ:</span>
        <div className="layer-checkbox-group">
          <label className={`layer-toggle ${activeSources.AST_EXACT ? 'active ast' : ''}`}>
            <input
              type="checkbox"
              checked={activeSources.AST_EXACT}
              onChange={() => onToggleSource('AST_EXACT')}
            />
            <span>AST</span>
          </label>

          <label className={`layer-toggle ${activeSources.CONFIG ? 'active cfg' : ''}`}>
            <input
              type="checkbox"
              checked={activeSources.CONFIG}
              onChange={() => onToggleSource('CONFIG')}
            />
            <span>CFG</span>
          </label>

          <label className={`layer-toggle ${activeSources.ML_PREDICTED ? 'active ml' : ''}`}>
            <input
              type="checkbox"
              checked={activeSources.ML_PREDICTED}
              onChange={() => onToggleSource('ML_PREDICTED')}
            />
            <span>ML</span>
          </label>

          <label className={`layer-toggle ${activeSources.LLM_JUDGE_VERIFIED ? 'active llm' : ''}`}>
            <input
              type="checkbox"
              checked={activeSources.LLM_JUDGE_VERIFIED}
              onChange={() => onToggleSource('LLM_JUDGE_VERIFIED')}
            />
            <span>LLM</span>
          </label>

          <label className={`layer-toggle ${activeSources.TRANSITIVE ? 'active trans' : ''}`}>
            <input
              type="checkbox"
              checked={activeSources.TRANSITIVE}
              onChange={() => onToggleSource('TRANSITIVE')}
            />
            <span>TRANS</span>
          </label>
        </div>
      </div>

      <div className="section-divider" />

      {/* 4. Порог ML */}
      <div className="bar-section threshold-section">
        <span className="section-caption">ПОРОГ ML:</span>
        <span className="mono-badge">p &ge; {confidenceThreshold.toFixed(2)}</span>
        <input
          id="confidence-threshold"
          name="confidence-threshold"
          aria-label="Порог вероятности ML"
          type="range"
          min="0.0"
          max="1.0"
          step="0.05"
          value={confidenceThreshold}
          onChange={(e) => onThresholdChange(parseFloat(e.target.value))}
          className="threshold-slider"
        />
      </div>

      <div className="section-divider" />

      {/* 5. Счётчики графа */}
      <div className="bar-section counters-section">
        <div className="counter-item" title="Всего узлов на графе">
          <span className="counter-label">NODES</span>
          <span className="counter-value">{nodesCount}</span>
        </div>
        <div className="counter-item" title="Активные прямые рёбра">
          <span className="counter-label">EDGES</span>
          <span className="counter-value">{visibleEdgesCount}</span>
        </div>
        <div className="counter-item optional" title="Транзитивные рёбра">
          <span className="counter-label">TRANS</span>
          <span className="counter-value">{transitiveEdgesCount}</span>
        </div>
        <div
          className={`counter-item optional ${unreachableEdgesCount > 0 ? 'highlight-dead' : ''}`}
          title="Недостижимые рёбра / мертвый код"
        >
          <span className="counter-label">DEAD</span>
          <span className="counter-value">{unreachableEdgesCount}</span>
        </div>
        <div className="counter-item optional" title="Отсечено фильтрами">
          <span className="counter-label">FILTERED</span>
          <span className="counter-value">{filteredCount}</span>
        </div>
      </div>

      <div className="section-divider" />

      {/* 5.5. Reachability & Dead Code Visualizer */}
      <div className="bar-section reachability-section">
        <button
          type="button"
          className={`cad-btn reachability-btn ${reachabilityMode === 'RUNTIME_ONLY' ? 'active' : ''}`}
          onClick={onToggleReachabilityMode}
          title={
            reachabilityMode === 'RUNTIME_ONLY'
              ? 'Режим: Только рантайм (отсекать мертвый код)'
              : 'Режим: Весь код (включая недостижимый)'
          }
        >
          <Activity size={11} />
          <span>{reachabilityMode === 'RUNTIME_ONLY' ? 'РАНТАЙМ' : 'ВЕСЬ КОД'}</span>
        </button>

        {reachabilityMode === 'RUNTIME_ONLY' && (
          <button
            type="button"
            className="cad-btn sub-toggle-btn"
            onClick={onToggleDeadCodeDisplay}
            title={
              deadCodeDisplay === 'DIM'
                ? 'Мертвый код: затемнение (клик для полного скрытия)'
                : 'Мертвый код: скрыто (клик для затемнения)'
            }
          >
            {deadCodeDisplay === 'DIM' ? <EyeOff size={11} /> : <Eye size={11} />}
            <span style={{ fontSize: 9 }}>{deadCodeDisplay === 'DIM' ? 'ЗАТУХАНИЕ' : 'СКРЫТО'}</span>
          </button>
        )}
      </div>

      {/* 5.6. Индикатор активного сквозного трейса */}
      {callTrace && (
        <>
          <div className="section-divider" />
          <div className="bar-section trace-banner-section">
            <div className="trace-banner-tag" title={callTrace.rootHandler || callTrace.rootEndpointPath}>
              <Route size={11} />
              <span className="trace-method-badge">{callTrace.rootHttpMethod}</span>
              <span className="trace-path-label">{callTrace.rootEndpointPath}</span>
            </div>
            <button
              type="button"
              className="cad-btn trace-clear-btn"
              onClick={onClearCallTrace}
              title="Сбросить трассировку"
            >
              <X size={10} />
              <span>СБРОС ТРЕЙСА</span>
            </button>
          </div>
        </>
      )}

      <div className="section-divider" />

      {/* 6. Поиск */}
      <div className="bar-section search-section">
        <div className="search-wrapper">
          <Search size={12} className="search-icon" />
          <input
            id="graph-search-input"
            name="graphSearch"
            aria-label="Поиск по node_id или URL-шаблону"
            type="text"
            placeholder="node_id / URL..."
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className="search-input"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => onSearchChange('')}
              className="search-clear-btn"
              title="Очистить поиск"
            >
              <X size={11} />
            </button>
          )}
        </div>
      </div>

      {/* 7. Кнопки управления CAD */}
      <div className="bar-section actions-section">
        <button
          type="button"
          className={`cad-btn ${colorMode === 'by_protocol' ? 'active' : ''}`}
          onClick={onToggleColorMode}
          title={colorMode === 'by_protocol' ? 'Раскраска: по протоколам связи' : 'Раскраска: по слоям источников'}
        >
          <Palette size={12} />
          <span>{colorMode === 'by_protocol' ? 'ПРОТОКОЛ' : 'ИСТОЧНИК'}</span>
        </button>

        <button
          type="button"
          className="cad-btn"
          onClick={onToggleDirection}
          title={direction === 'RIGHT' ? 'Ориентация DAG: слева направо (LR)' : 'Ориентация DAG: сверху вниз (TB)'}
        >
          {direction === 'RIGHT' ? <ArrowRight size={12} /> : <ArrowDown size={12} />}
          <span>{direction === 'RIGHT' ? 'LR' : 'TB'}</span>
        </button>

        {/* Экспорт */}
        <div className="export-dropdown-wrapper" ref={exportRef}>
          <button
            type="button"
            className={`cad-btn export-btn ${isExportMenuOpen ? 'active' : ''}`}
            onClick={() => setIsExportMenuOpen((prev) => !prev)}
            disabled={isExporting}
            title="Экспорт графа в PNG (2x Retina), SVG или JSON"
          >
            <Download size={11} />
            <span>{isExporting ? 'ЭКСПОРТ...' : 'ЭКСПОРТ'}</span>
            <ChevronDown size={10} />
          </button>

          {isExportMenuOpen && (
            <div className="export-menu">
              <button
                type="button"
                className="export-menu-item"
                onClick={() => {
                  setIsExportMenuOpen(false);
                  onExportPng();
                }}
              >
                <Image size={12} />
                <span>PNG (2x Retina)</span>
              </button>
              <button
                type="button"
                className="export-menu-item"
                onClick={() => {
                  setIsExportMenuOpen(false);
                  onExportSvg();
                }}
              >
                <Code size={12} />
                <span>SVG (Вектор)</span>
              </button>
              <button
                type="button"
                className="export-menu-item"
                onClick={() => {
                  setIsExportMenuOpen(false);
                  onExportJson();
                }}
              >
                <FileCode size={12} />
                <span>JSON (Канонический)</span>
              </button>
            </div>
          )}
        </div>

        <button
          type="button"
          className="cad-btn reset-btn"
          onClick={onResetAll}
          title="Сбросить карту, зум, фильтры, слои, поиск и выделение"
        >
          <RotateCcw size={12} />
          <span>СБРОС</span>
        </button>
      </div>
    </header>
  );
};
