import React, { useState, useRef } from 'react';
import { Upload, FileUp, Database, FileCode, AlertTriangle, X } from 'lucide-react';
import type { CanonicalGraph } from '../../types/graph';
import { mergePipelineFiles, parseConfirmedEdgesJson } from '../../adapters/dataLoader';
import { demoGraph } from '../../data/demoData';
import './DataLoaderModal.css';

interface DataLoaderModalProps {
  isOpen: boolean;
  onClose: () => void;
  onLoadGraph: (graph: CanonicalGraph, summary: string, sourceName: string) => void;
}

export const DataLoaderModal: React.FC<DataLoaderModalProps> = ({
  isOpen,
  onClose,
  onLoadGraph,
}) => {
  const [isDragActive, setIsDragActive] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  if (!isOpen) return null;

  const handleFiles = async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return;
    setErrorMessage(null);

    try {
      const loadedFiles: { name: string; content: any }[] = [];

      for (let i = 0; i < fileList.length; i++) {
        const file = fileList[i];
        const text = await file.text();
        try {
          const json = JSON.parse(text);
          loadedFiles.push({ name: file.name, content: json });
        } catch (jsonErr: any) {
          throw new Error(`Ошибка парсинга ${file.name}: невалидный JSON (${jsonErr.message})`);
        }
      }

      const res = mergePipelineFiles(loadedFiles);
      onLoadGraph(res.graph, res.summary, res.sourceFile);
      onClose();
    } catch (err: any) {
      setErrorMessage(err.message || 'Ошибка обработки файлов');
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragActive(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragActive(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragActive(false);
    handleFiles(e.dataTransfer.files);
  };

  const handleLoadDemo = () => {
    onLoadGraph(demoGraph, '13 узлов, 14 рёбер (AST + ML + DB)', 'ДЕМО (Train Ticket)');
    onClose();
  };

  const handleLoadArchparseOutput = async () => {
    setErrorMessage(null);
    try {
      const resp = await fetch('/data/confirmed_edges.json');
      if (!resp.ok) {
        throw new Error(`Файл не найден на сервере (status ${resp.status})`);
      }
      const data = await resp.json();
      const g = parseConfirmedEdgesJson(data);
      onLoadGraph(
        g,
        `${g.nodes.length} контроллеров из archparse`,
        'output/confirmed_edges.json'
      );
      onClose();
    } catch (err: any) {
      setErrorMessage(`Ошибка загрузки примера output/confirmed_edges.json: ${err.message}`);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose} role="dialog" aria-modal="true">
      <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title">
            <Upload size={14} />
            <span>ЗАГРУЗКА РЕАЛЬНЫХ ДАННЫХ ПАЙПЛАЙНА</span>
          </div>
          <button
            type="button"
            className="modal-close-btn"
            onClick={onClose}
            title="Закрыть"
          >
            <X size={14} />
          </button>
        </div>

        <div className="modal-body">
          {errorMessage && (
            <div className="modal-error-box">
              <AlertTriangle size={14} />
              <span>{errorMessage}</span>
            </div>
          )}

          {/* Зона Drag & Drop */}
          <div
            className={`modal-dropzone ${isDragActive ? 'drag-active' : ''}`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
          >
            <FileUp size={28} className="dropzone-icon" />
            <div className="dropzone-text">ПЕРЕТАЩИТЕ JSON ФАЙЛЫ В ЭТУ ОБЛАСТЬ</div>
            <div className="dropzone-subtext">
              Поддерживается выбор нескольких файлов одновременно для слияния
            </div>
            <button
              type="button"
              className="dropzone-btn"
              onClick={(e) => {
                e.stopPropagation();
                fileInputRef.current?.click();
              }}
            >
              <Upload size={12} />
              <span>ВЫБРАТЬ ФАЙЛЫ...</span>
            </button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".json"
              style={{ display: 'none' }}
              onChange={(e) => handleFiles(e.target.files)}
            />
          </div>

          {/* Предустановленные наборы */}
          <div className="modal-presets-section">
            <span className="section-label">ГОТОВЫЕ НАБОРЫ ДАННЫХ:</span>
            <div className="preset-buttons">
              <button
                type="button"
                className="preset-btn"
                onClick={handleLoadDemo}
              >
                <div className="preset-name">
                  <Database size={12} style={{ display: 'inline', marginRight: 4 }} />
                  demo_graph.json
                </div>
                <div className="preset-desc">
                  Эталонный Train Ticket: 13 узлов, 14 рёбер, AST, ML, DB, LLM Judge
                </div>
              </button>

              <button
                type="button"
                className="preset-btn"
                onClick={handleLoadArchparseOutput}
              >
                <div className="preset-name">
                  <FileCode size={12} style={{ display: 'inline', marginRight: 4 }} />
                  confirmed_edges.json
                </div>
                <div className="preset-desc">
                  Результат archparse: 35 реальных контроллеров и эндпоинтов
                </div>
              </button>
            </div>
          </div>

          {/* Справочник контрактов данных */}
          <div className="contracts-info">
            <div className="contracts-title">ПОДДЕРЖИВАЕМЫЕ КОНТРАКТЫ (ADR-001):</div>
            <div className="contracts-list">
              <div className="contract-item">
                <code>canonical_graph.json</code> — полный типизированный граф узлов и рёбер
              </div>
              <div className="contract-item">
                <code>confirmed_edges.json</code> — вызовы и эндпоинты, извлеченные archparse
              </div>
              <div className="contract-item">
                <code>evidence.json</code> — журнал доказательств (файлы, строки, веса ML, LLM)
              </div>
              <div className="contract-item">
                <code>facts/*.json</code> — синтаксические факты сервисов (inbound/outbound/db)
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
