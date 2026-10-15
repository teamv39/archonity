import React from 'react';
import {
  Search,
  Maximize2,
  Palette,
  ArrowRight,
  ArrowDown,
  X,
  Sliders,
} from 'lucide-react';
import type { SourceType, ColorMode, DagDirection } from '../../types/graph';
import './toolbar.css';

interface ToolbarProps {
  confidenceThreshold: number;
  onThresholdChange: (val: number) => void;
  allowedSources: Set<SourceType>;
  onToggleSource: (src: SourceType) => void;
  colorMode: ColorMode;
  onToggleColorMode: () => void;
  direction: DagDirection;
  onToggleDirection: () => void;
  searchQuery: string;
  onSearchChange: (q: string) => void;
  onFitView: () => void;
  showTransitive: boolean;
  onToggleTransitive: () => void;
  totalEdgesCount: number;
  visibleEdgesCount: number;
}

export const Toolbar: React.FC<ToolbarProps> = ({
  confidenceThreshold,
  onThresholdChange,
  allowedSources,
  onToggleSource,
  colorMode,
  onToggleColorMode,
  direction,
  onToggleDirection,
  searchQuery,
  onSearchChange,
  onFitView,
  showTransitive,
  onToggleTransitive,
  totalEdgesCount,
  visibleEdgesCount,
}) => {
  return (
    <div className="floating-toolbar">
      <div className="toolbar-brand">
        <span className="brand-title">Archonity Visualizer</span>
        <span className="brand-badge">Train Ticket</span>
      </div>

      <div className="toolbar-controls">
        {/* ML Confidence Threshold Slider */}
        <div className="slider-group" title="Порог уверенности для отсечения слабых гипотез связей">
          <Sliders size={14} style={{ color: '#ec4899' }} />
          <span className="slider-label">ML Threshold:</span>
          <span className="slider-val">p ≥ {confidenceThreshold.toFixed(2)}</span>
          <input
            type="range"
            min="0.0"
            max="1.0"
            step="0.05"
            value={confidenceThreshold}
            onChange={(e) => onThresholdChange(parseFloat(e.target.value))}
            onInput={(e) => onThresholdChange(parseFloat((e.target as HTMLInputElement).value))}
            className="confidence-slider"
          />
          <span style={{ fontSize: 10, color: '#64748b' }}>
            ({visibleEdgesCount}/{totalEdgesCount})
          </span>
        </div>

        {/* Source Filter Pills */}
        <div className="filter-pills">
          <button
            type="button"
            className={`filter-pill-btn ${allowedSources.has('AST_EXACT') ? 'active' : ''}`}
            onClick={() => onToggleSource('AST_EXACT')}
            title="Детерминированные вызовы из статического анализа Java/AST"
          >
            AST
          </button>
          <button
            type="button"
            className={`filter-pill-btn ${allowedSources.has('CONFIG') ? 'active' : ''}`}
            onClick={() => onToggleSource('CONFIG')}
            title="Связи из конфигураций application.yml / docker-compose"
          >
            Config
          </button>
          <button
            type="button"
            className={`filter-pill-btn pill-ml ${allowedSources.has('ML_PREDICTED') ? 'active' : ''}`}
            onClick={() => onToggleSource('ML_PREDICTED')}
            title="Связи, предсказанные моделью CatBoost"
          >
            ML
          </button>
          <button
            type="button"
            className={`filter-pill-btn pill-llm ${allowedSources.has('LLM_JUDGE_VERIFIED') ? 'active' : ''}`}
            onClick={() => onToggleSource('LLM_JUDGE_VERIFIED')}
            title="Спорные связи, подтвержденные кодовым арбитром Qwen"
          >
            LLM Judge
          </button>
          <button
            type="button"
            className={`filter-pill-btn ${showTransitive ? 'active' : ''}`}
            onClick={onToggleTransitive}
            title="Показать косвенные транзитивные зависимости"
          >
            Transitive
          </button>
        </div>

        {/* Search */}
        <div className="search-box">
          <Search size={14} style={{ color: '#64748b' }} />
          <input
            type="text"
            placeholder="Поиск узла / API..."
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className="search-input"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => onSearchChange('')}
              style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', padding: 0 }}
            >
              <X size={12} />
            </button>
          )}
        </div>

        {/* Actions */}
        <div className="toolbar-actions">
          <button
            type="button"
            className={`action-btn ${colorMode === 'by_protocol' ? 'active' : ''}`}
            onClick={onToggleColorMode}
            title={colorMode === 'by_protocol' ? 'Цвет: по протоколам' : 'Цвет: по источникам'}
          >
            <Palette size={13} />
            <span>{colorMode === 'by_protocol' ? 'Протокол' : 'Источник'}</span>
          </button>

          <button
            type="button"
            className="action-btn"
            onClick={onToggleDirection}
            title={direction === 'RIGHT' ? 'Раскладка: слева направо' : 'Раскладка: сверху вниз'}
          >
            {direction === 'RIGHT' ? <ArrowRight size={13} /> : <ArrowDown size={13} />}
            <span>{direction === 'RIGHT' ? 'LR' : 'TB'}</span>
          </button>

          <button
            type="button"
            className="action-btn"
            onClick={onFitView}
            title="Масштабировать по экрану"
          >
            <Maximize2 size={13} />
            <span>Fit</span>
          </button>
        </div>
      </div>
    </div>
  );
};
