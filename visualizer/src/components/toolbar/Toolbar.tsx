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
  Compass,
  Layers,
  Sparkles,
} from 'lucide-react';
import type {
  SourceType,
  ColorMode,
  DagDirection,
  ReachabilityMode,
  DeadCodeDisplay,
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
  onLoadBenchmarkSlice?: () => void;
  onLoadStandardDemo?: () => void;

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

  // Инфраструктурные хабы (ADR-003)
  excludeHubs: boolean;
  onToggleExcludeHubs: () => void;

  // Сценарный плеер
  isScenarioActive: boolean;
  onToggleScenarioPlayer: () => void;
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
  excludeHubs,
  onToggleExcludeHubs,
  isScenarioActive,
  onToggleScenarioPlayer,
  onLoadBenchmarkSlice,
  onLoadStandardDemo,
}) => {
  const filteredCount = totalEdgesCount - visibleEdgesCount;
  const [isExportMenuOpen, setIsExportMenuOpen] = useState(false);
  const [exportCoords, setExportCoords] = useState<{ top: number; right: number } | null>(null);
  const exportRef = useRef<HTMLDivElement>(null);

  const handleToggleExportMenu = () => {
    if (!isExportMenuOpen && exportRef.current) {
      const rect = exportRef.current.getBoundingClientRect();
      setExportCoords({
        top: rect.bottom + 4,
        right: Math.max(8, window.innerWidth - rect.right),
      });
    }
    setIsExportMenuOpen((prev) => !prev);
  };

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
        <button
          type="button"
          className={`cad-btn dataset-btn ${isCustomDataset ? 'custom' : ''}`}
          onClick={onOpenDataLoader}
          title={`Датасет: ${datasetName} (клик для загрузки файлов pipeline)`}
        >
          <Upload size={11} />
          <span className="dataset-label">{datasetName}</span>
          <ChevronDown size={10} style={{ opacity: 0.6 }} />
        </button>

        {onLoadBenchmarkSlice && !datasetName.includes('Slice') && !datasetName.includes('Benchmark') && (
          <button
            type="button"
            className="cad-btn preset-pill-btn"
            onClick={onLoadBenchmarkSlice}
            title="Быстро загрузить полный эталонный Train Ticket Benchmark Slice (19 узлов, 27 рёбер)"
          >
            <Sparkles size={11} color="#0969DA" />
            <span>TT 19N</span>
          </button>
        )}

        {onLoadStandardDemo && (datasetName.includes('Slice') || datasetName.includes('Benchmark') || isCustomDataset) && (
          <button
            type="button"
            className="cad-btn preset-pill-btn"
            onClick={onLoadStandardDemo}
            title="Переключиться на компактный демо-срез бронирования (9 узлов)"
          >
            <span>ДЕМО 9N</span>
          </button>
        )}
      </div>

      <div className="section-divider" />

      {/* 3. Переключатели слоев */}
      <div className="bar-section layers-section">
        <div className="layer-checkbox-group">
          <label
            className={`layer-toggle ${activeSources.AST_EXACT ? 'active ast' : ''}`}
            title="Слой AST_EXACT (синтаксический анализ)"
          >
            <input
              type="checkbox"
              checked={activeSources.AST_EXACT}
              onChange={() => onToggleSource('AST_EXACT')}
            />
            <span>AST</span>
          </label>

          <label
            className={`layer-toggle ${activeSources.CONFIG ? 'active cfg' : ''}`}
            title="Слой CONFIG (конфигурации application.yml)"
          >
            <input
              type="checkbox"
              checked={activeSources.CONFIG}
              onChange={() => onToggleSource('CONFIG')}
            />
            <span>CFG</span>
          </label>

          <label
            className={`layer-toggle ${activeSources.ML_PREDICTED ? 'active ml' : ''}`}
            title="Слой ML_PREDICTED (гипотезы CatBoost/CodeBERT)"
          >
            <input
              type="checkbox"
              checked={activeSources.ML_PREDICTED}
              onChange={() => onToggleSource('ML_PREDICTED')}
            />
            <span>ML</span>
          </label>

          <label
            className={`layer-toggle ${activeSources.LLM_JUDGE_VERIFIED ? 'active llm' : ''}`}
            title="Слой LLM_JUDGE_VERIFIED (арбитраж вердиктов)"
          >
            <input
              type="checkbox"
              checked={activeSources.LLM_JUDGE_VERIFIED}
              onChange={() => onToggleSource('LLM_JUDGE_VERIFIED')}
            />
            <span>LLM</span>
          </label>

          <label
            className={`layer-toggle ${activeSources.TRANSITIVE ? 'active trans' : ''}`}
            title="Слой TRANSITIVE (транзитивное замыкание)"
          >
            <input
              type="checkbox"
              checked={activeSources.TRANSITIVE}
              onChange={() => onToggleSource('TRANSITIVE')}
            />
            <span>TR</span>
          </label>
        </div>
      </div>

      <div className="section-divider" />

      {/* 4. Порог ML */}
      <div className="bar-section threshold-section">
        <span className="mono-badge" title={`Порог ML: p >= ${confidenceThreshold.toFixed(2)}`}>
          p &ge; {confidenceThreshold.toFixed(2)}
        </span>
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
          title={`Порог ML: ${confidenceThreshold.toFixed(2)}`}
        />
      </div>

      <div className="section-divider" />

      {/* 5. Компактный HUD-чип счетчиков графа */}
      <div className="bar-section counters-section">
        <div
          className="cad-hud-chip"
          title={`Сводка графа:\n• Узлов (Nodes): ${nodesCount}\n• Активных рёбер (Edges): ${visibleEdgesCount}\n• Транзитивных: ${transitiveEdgesCount}\n• Мертвый код (Dead): ${unreachableEdgesCount}\n• Отсечено фильтрами: ${filteredCount}`}
        >
          <span className="hud-metric" title="Узлы (Nodes)">
            {nodesCount}
            <span className="hud-sub">N</span>
          </span>
          <span className="hud-dot">·</span>
          <span className="hud-metric" title="Активные прямые рёбра (Edges)">
            {visibleEdgesCount}
            <span className="hud-sub">E</span>
          </span>
          {transitiveEdgesCount > 0 && (
            <>
              <span className="hud-dot">·</span>
              <span className="hud-metric" title="Транзитивные рёбра">
                {transitiveEdgesCount}
                <span className="hud-sub">T</span>
              </span>
            </>
          )}
          <span className="hud-dot">·</span>
          <span
            className={`hud-metric ${unreachableEdgesCount > 0 ? 'hud-dead' : ''}`}
            title="Мертвый код / Недостижимые рёбра"
          >
            {unreachableEdgesCount}
            <span className="hud-sub">D</span>
          </span>
          {filteredCount > 0 && (
            <>
              <span className="hud-dot">·</span>
              <span className="hud-metric" title="Отсечено фильтрами">
                {filteredCount}
                <span className="hud-sub">F</span>
              </span>
            </>
          )}
        </div>
      </div>

      <div className="section-divider" />

      {/* 6. Reachability & Dead Code Visualizer */}
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
          <span className="btn-text">{reachabilityMode === 'RUNTIME_ONLY' ? 'РАНТАЙМ' : 'ВЕСЬ КОД'}</span>
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
            <span className="btn-text" style={{ fontSize: 9 }}>
              {deadCodeDisplay === 'DIM' ? 'ЗАТУХАНИЕ' : 'СКРЫТО'}
            </span>
          </button>
        )}
      </div>

      <div className="section-divider" />

      {/* 7. Инфраструктурные хабы (ADR-003 п. 5.1) */}
      <div className="bar-section hubs-section">
        <button
          type="button"
          className={`cad-btn ${excludeHubs ? 'active' : ''}`}
          onClick={onToggleExcludeHubs}
          title={
            excludeHubs
              ? 'Инфра-хабы скрыты (Eureka, Gateway, RabbitMQ исключены)'
              : 'Инфра-хабы отображаются (клик для исключения)'
          }
        >
          <Layers size={11} />
          <span className="btn-text">{excludeHubs ? 'ХАБЫ: ИСКЛ' : 'ХАБЫ: ВКЛ'}</span>
        </button>
      </div>

      <div className="section-divider" />

      {/* 8. Интерактивные сценарии (Сценарный плеер) */}
      <div className="bar-section scenario-section">
        <button
          type="button"
          className={`cad-btn ${isScenarioActive ? 'active' : ''}`}
          onClick={onToggleScenarioPlayer}
          title="Сценарный плеер эталонных цепочек Train Ticket (Preservation, Payment, Cancellation, Route Planning)"
        >
          <Compass size={12} style={{ color: isScenarioActive ? '#0969DA' : 'inherit' }} />
          <span className="btn-text">СЦЕНАРИИ</span>
        </button>
      </div>

      <div className="section-divider" />

      {/* 9. Поиск */}
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

      {/* 10. Кнопки управления CAD */}
      <div className="bar-section actions-section">
        <button
          type="button"
          className={`cad-btn ${colorMode === 'by_protocol' ? 'active' : ''}`}
          onClick={onToggleColorMode}
          title={colorMode === 'by_protocol' ? 'Раскраска: по протоколам связи' : 'Раскраска: по слоям источников'}
        >
          <Palette size={12} />
          <span className="btn-text">{colorMode === 'by_protocol' ? 'ПРОТОКОЛ' : 'ИСТОЧНИК'}</span>
        </button>

        <button
          type="button"
          className="cad-btn"
          onClick={onToggleDirection}
          title={direction === 'RIGHT' ? 'Ориентация DAG: слева направо (LR)' : 'Ориентация DAG: сверху вниз (TB)'}
        >
          {direction === 'RIGHT' ? <ArrowRight size={12} /> : <ArrowDown size={12} />}
          <span className="btn-text">{direction === 'RIGHT' ? 'LR' : 'TB'}</span>
        </button>

        {/* Экспорт */}
        <div className="export-dropdown-wrapper" ref={exportRef}>
          <button
            type="button"
            className={`cad-btn export-btn ${isExportMenuOpen ? 'active' : ''}`}
            onClick={handleToggleExportMenu}
            disabled={isExporting}
            title="Экспорт графа в PNG (2x Retina), SVG или JSON"
          >
            <Download size={11} />
            <span className="btn-text">{isExporting ? 'ЭКСПОРТ...' : 'ЭКСПОРТ'}</span>
            <ChevronDown size={10} />
          </button>

          {isExportMenuOpen && (
            <div
              className="export-menu"
              style={{
                position: 'fixed',
                top: exportCoords?.top ?? 44,
                right: exportCoords?.right ?? 8,
                zIndex: 9999,
              }}
            >
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
          <span className="btn-text">СБРОС</span>
        </button>
      </div>
    </header>
  );
};
