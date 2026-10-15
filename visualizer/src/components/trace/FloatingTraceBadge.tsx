import React from 'react';
import { Route, X } from 'lucide-react';
import type { CallTraceResult } from '../../types/graph';
import './floatingTrace.css';

interface FloatingTraceBadgeProps {
  callTrace: CallTraceResult | null;
  onClearCallTrace: () => void;
}

export const FloatingTraceBadge: React.FC<FloatingTraceBadgeProps> = ({
  callTrace,
  onClearCallTrace,
}) => {
  if (!callTrace) return null;

  return (
    <div
      className="floating-trace-pill"
      role="status"
      aria-live="polite"
      aria-label="Активный сквозной трейс вызовов"
    >
      <div className="trace-pill-left">
        <Route size={12} className="trace-pill-icon" />
        <span className="trace-pill-tag">ТРЕЙС</span>
        <span className={`trace-pill-method ${callTrace.rootHttpMethod.toLowerCase()}`}>
          {callTrace.rootHttpMethod}
        </span>
        <span
          className="trace-pill-path"
          title={`Эндпоинт: ${callTrace.rootEndpointPath}\nМетод: ${callTrace.rootHandler || 'н/д'}\nСервис: ${callTrace.rootServiceId}`}
        >
          {callTrace.rootEndpointPath}
        </span>
      </div>

      <div className="trace-pill-divider" />

      <div className="trace-pill-metrics">
        <span className="trace-pill-metric" title="Узлов сервисов и баз в цепочке">
          <strong>{callTrace.affectedNodeIds.size}</strong> узлов
        </span>
        <span className="trace-pill-dot">·</span>
        <span className="trace-pill-metric" title="Задействовано таблиц баз данных">
          <strong>{callTrace.targetDatabases.length}</strong> БД
        </span>
      </div>

      <button
        type="button"
        className="trace-pill-close-btn"
        onClick={onClearCallTrace}
        title="Сбросить трассировку вызовов (Esc)"
      >
        <X size={11} />
        <span>СБРОС</span>
      </button>
    </div>
  );
};
