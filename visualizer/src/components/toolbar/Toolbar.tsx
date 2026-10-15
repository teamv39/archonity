import React from 'react';
import {
  Search,
  RotateCcw,
  Palette,
  ArrowRight,
  ArrowDown,
  X,
} from 'lucide-react';
import type { SourceType, ColorMode, DagDirection } from '../../types/graph';
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
}) => {
  const filteredCount = totalEdgesCount - visibleEdgesCount;

  return (
    <header className="control-bar" role="toolbar" aria-label="Панель управления графом">
      {/* 1. Бренд */}
      <div className="bar-section brand-section">
        <span className="brand-logo">[ARCHONITY]</span>
        <span className="brand-sub">WORKBENCH</span>
      </div>

      <div className="section-divider" />

      {/* 2. Переключатели слоев */}
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

      {/* 3. Порог ML */}
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

      {/* 4. Счётчики графа */}
      <div className="bar-section counters-section">
        <div className="counter-item" title="Всего узлов на графе">
          <span className="counter-label">NODES</span>
          <span className="counter-value">{nodesCount}</span>
        </div>
        <div className="counter-item" title="Активные прямые рёбра">
          <span className="counter-label">EDGES</span>
          <span className="counter-value">{visibleEdgesCount}</span>
        </div>
        <div className="counter-item" title="Транзитивные рёбра">
          <span className="counter-label">TRANS</span>
          <span className="counter-value">{transitiveEdgesCount}</span>
        </div>
        <div className="counter-item" title="Отсечено фильтрами / Dead Code">
          <span className="counter-label">FILTERED</span>
          <span className="counter-value">{filteredCount}</span>
        </div>
      </div>

      <div className="section-divider" />

      {/* 5. Поиск */}
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

      {/* 6. Кнопки управления CAD */}
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
