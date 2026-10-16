import React, { useState } from 'react';
import {
  Compass,
  Play,
  Pause,
  ChevronLeft,
  ChevronRight,
  X,
  Code,
  ArrowRight,
} from 'lucide-react';
import type { RuntimeScenario, ScenarioPlaybackState } from '../../types/graph';
import './ScenarioPlayer.css';

interface ScenarioPlayerProps {
  scenarios: RuntimeScenario[];
  activeScenarioId: string | null;
  currentStepIndex: number;
  isPlaying: boolean;
  onSelectScenario: (scenarioId: string) => void;
  onNextStep: () => void;
  onPrevStep: () => void;
  onTogglePlay: () => void;
  onClose: () => void;
  playbackState: ScenarioPlaybackState | null;
}

export const ScenarioPlayer: React.FC<ScenarioPlayerProps> = ({
  scenarios,
  activeScenarioId,
  currentStepIndex,
  isPlaying,
  onSelectScenario,
  onNextStep,
  onPrevStep,
  onTogglePlay,
  onClose,
  playbackState,
}) => {
  const [showCodeDetails, setShowCodeDetails] = useState<boolean>(false);

  if (!activeScenarioId || !playbackState) return null;

  const currentScenario = scenarios.find((s) => s.id === activeScenarioId);
  if (!currentScenario) return null;

  const currentStep = playbackState.currentStep;
  const progressPercent = Math.round(
    ((currentStepIndex + 1) / currentScenario.steps.length) * 100
  );

  const methodClass =
    currentStep.relationType === 'DATABASE'
      ? 'db'
      : currentStep.relationType === 'MESSAGE_QUEUE'
      ? 'mq'
      : (currentStep.httpMethod || 'GET').toLowerCase();

  return (
    <div
      className="scenario-player-dock"
      role="region"
      aria-label="Сценарный плеер архитектурных зависимостей"
    >
      {/* 1. Верхняя полоса управления */}
      <div className="scenario-player-header">
        <div className="scenario-header-left">
          <Compass size={14} className="scenario-player-icon" />
          <span className="scenario-tag">СЦЕНАРИЙ</span>
          <select
            className="scenario-select"
            value={activeScenarioId}
            onChange={(e) => onSelectScenario(e.target.value)}
            title="Выберите эталонный сценарий выполнения Train Ticket"
          >
            {scenarios.map((sc) => (
              <option key={sc.id} value={sc.id}>
                {sc.name} ({sc.steps.length} ш.)
              </option>
            ))}
          </select>
        </div>

        <div className="scenario-header-right">
          <span className="scenario-step-pill">
            ШАГ {currentStepIndex + 1} / {currentScenario.steps.length}
          </span>

          <button
            type="button"
            className="scenario-ctrl-btn"
            onClick={onPrevStep}
            disabled={currentStepIndex === 0}
            title="Предыдущий шаг сценария (Left Arrow)"
          >
            <ChevronLeft size={13} />
            <span>НАЗАД</span>
          </button>

          <button
            type="button"
            className={`scenario-ctrl-btn ${isPlaying ? 'active-play' : ''}`}
            onClick={onTogglePlay}
            title={isPlaying ? 'Приостановить авто-проигрывание' : 'Запустить авто-шаг (интервал 2.5с)'}
          >
            {isPlaying ? <Pause size={12} /> : <Play size={12} />}
            <span>{isPlaying ? 'ПАУЗА' : 'АВТО'}</span>
          </button>

          <button
            type="button"
            className="scenario-ctrl-btn"
            onClick={onNextStep}
            disabled={currentStepIndex === currentScenario.steps.length - 1}
            title="Следующий шаг сценария (Right Arrow)"
          >
            <span>ВПЕРЕД</span>
            <ChevronRight size={13} />
          </button>

          <button
            type="button"
            className="scenario-close-btn"
            onClick={onClose}
            title="Закрыть режим сценария (Esc)"
          >
            <X size={12} />
          </button>
        </div>
      </div>

      {/* 2. Индикатор прогресса */}
      <div className="scenario-progress-bar">
        <div
          className="scenario-progress-fill"
          style={{ width: `${progressPercent}%` }}
        />
      </div>

      {/* 3. Описание текущего шага */}
      <div className="scenario-step-body">
        <div className="scenario-route-row">
          <div className="scenario-endpoints-flow">
            <span className="scenario-node-name">{currentStep.source}</span>
            <ArrowRight size={12} className="scenario-arrow" />
            <span className="scenario-node-name">{currentStep.target}</span>
          </div>

          <div className="scenario-meta-badges">
            <span className={`scenario-method-badge ${methodClass}`}>
              {currentStep.httpMethod || currentStep.relationType}
            </span>
            {currentStep.endpoint && (
              <span className="tag-pill" style={{ fontSize: 9 }}>
                {currentStep.endpoint}
              </span>
            )}
          </div>
        </div>

        <div className="scenario-action-desc">
          <strong>Действие:</strong> {currentStep.action}
        </div>

        {currentStep.codeSnippet && (
          <div>
            <button
              type="button"
              className="scenario-details-toggle"
              onClick={() => setShowCodeDetails((prev) => !prev)}
            >
              <Code size={10} style={{ display: 'inline', marginRight: 4, verticalAlign: 'middle' }} />
              {showCodeDetails ? 'Скрыть фрагмент кода' : 'Показать фрагмент кода вызова'}
            </button>

            {showCodeDetails && (
              <pre className="scenario-code-box">{currentStep.codeSnippet}</pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
