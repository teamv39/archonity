import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  useReactFlow,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import {
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  Info,
  X,
  FileUp,
} from 'lucide-react';

import type {
  CanonicalGraph,
  SourceType,
  RelationType,
  ColorMode,
  DagDirection,
  BlastRadiusResult,
  ReachabilityMode,
  DeadCodeDisplay,
  CallTraceResult,
  EndpointInfo,
} from './types/graph';
import { demoGraph } from './data/demoData';
import { computeLayout } from './layout/layoutEngine';
import {
  filterGraph,
  buildReactFlowElements,
  calculateBlastRadius,
  traceCallPath,
  type NodeData,
  type EdgeData,
} from './adapters/graphAdapter';
import { mergePipelineFiles } from './adapters/dataLoader';
import {
  exportGraphToPng,
  exportGraphToSvg,
  exportGraphToJson,
} from './utils/exportGraph';

import { ServiceNode } from './components/nodes/ServiceNode';
import { DatabaseNode } from './components/nodes/DatabaseNode';
import { QueueNode } from './components/nodes/QueueNode';
import { CustomEdge } from './components/edges/CustomEdge';
import { Toolbar } from './components/toolbar/Toolbar';
import { Inspector } from './components/inspector/Inspector';
import { DataLoaderModal } from './components/modals/DataLoaderModal';
import { FloatingTraceBadge } from './components/trace/FloatingTraceBadge';

import './App.css';

const nodeTypes = {
  service: ServiceNode,
  database: DatabaseNode,
  message_queue: QueueNode,
};

const edgeTypes = {
  custom: CustomEdge,
};

interface ToastState {
  message: string;
  type: 'success' | 'error' | 'warning' | 'info';
}

const VisualizerCanvas: React.FC = () => {
  const { fitView } = useReactFlow();

  // Исходный граф (по умолчанию — эталонный демо-срез Train Ticket)
  const [graph, setGraph] = useState<CanonicalGraph>(demoGraph);
  const [datasetName, setDatasetName] = useState<string>('ДЕМО (Train Ticket)');
  const [isCustomDataset, setIsCustomDataset] = useState<boolean>(false);
  const [isDataLoaderOpen, setIsDataLoaderOpen] = useState<boolean>(false);

  // Drag & drop состояние для холста
  const [isDragOverCanvas, setIsDragOverCanvas] = useState<boolean>(false);

  // Статус экспорта
  const [isExporting, setIsExporting] = useState<boolean>(false);

  // Всплывающие уведомления (Toast)
  const [toast, setToast] = useState<ToastState | null>(null);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => {
      setToast(null);
    }, 4500);
    return () => clearTimeout(timer);
  }, [toast]);

  // Фильтры и параметры визуализации
  const [confidenceThreshold, setConfidenceThreshold] = useState<number>(0.35);
  const [activeSources, setActiveSources] = useState<Record<SourceType, boolean>>({
    AST_EXACT: true,
    CONFIG: true,
    ML_PREDICTED: true,
    LLM_JUDGE_VERIFIED: true,
    TRANSITIVE: false,
  });
  const [allowedRelations] = useState<Set<RelationType>>(
    new Set(['REST_HTTP', 'DATABASE', 'MESSAGE_QUEUE', 'TRANSITIVE'])
  );
  const [colorMode, setColorMode] = useState<ColorMode>('by_source');
  const [direction, setDirection] = useState<DagDirection>('RIGHT');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Выбранные сущности и Blast Radius
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [blastRadius, setBlastRadius] = useState<BlastRadiusResult | null>(null);

  // Reachability & Dead Code
  const [reachabilityMode, setReachabilityMode] = useState<ReachabilityMode>('RUNTIME_ONLY');
  const [deadCodeDisplay, setDeadCodeDisplay] = useState<DeadCodeDisplay>('DIM');

  // Cross-Service Call Path Tracing
  const [callTrace, setCallTrace] = useState<CallTraceResult | null>(null);

  // Базовая стабильная раскладка графа
  const [positions, setPositions] = useState<Map<string, { x: number; y: number }>>(new Map());
  const [isLoadingLayout, setIsLoadingLayout] = useState<boolean>(false);
  const lastDirectionRef = React.useRef(direction);

  // Изменение ширины правого сайдбара (Splitter)
  const [sidebarWidth, setSidebarWidth] = useState<number>(() => {
    return Math.max(340, Math.min(600, Math.round(window.innerWidth * 0.35)));
  });
  const [isDragging, setIsDragging] = useState<boolean>(false);

  const handleMouseDownResize = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleResetSidebarWidth = useCallback(() => {
    setSidebarWidth(Math.round(window.innerWidth * 0.35));
  }, []);

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      const newWidth = window.innerWidth - e.clientX;
      const minW = 280;
      const maxW = Math.round(window.innerWidth * 0.65);
      if (newWidth >= minW && newWidth <= maxW) {
        setSidebarWidth(newWidth);
      }
    };

    const handleMouseUp = () => {
      setIsDragging(false);
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging]);

  // React Flow узлы и ребра
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<NodeData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge<EdgeData>>([]);

  // Стабильная топологическая раскладка: пересчитывается ТОЛЬКО при смене графа или направления (LR/TB)
  useEffect(() => {
    let isCancelled = false;

    computeLayout(graph.nodes, graph.edges, direction)
      .then((newPositions) => {
        if (!isCancelled) {
          setPositions(newPositions);
          setIsLoadingLayout(false);
        }
      })
      .catch((err) => {
        if (!isCancelled) {
          console.error('Ошибка вычисления раскладки ELK:', err);
          setIsLoadingLayout(false);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [graph, direction]);

  // Фильтрация ребер (мгновенно и синхронно при изменении фильтров)
  const { filteredNodes, filteredEdges, unreachableEdgesCount } = useMemo(() => {
    return filterGraph(graph, {
      confidenceThreshold,
      activeSources,
      allowedRelations,
      searchQuery,
      colorMode,
      reachabilityMode,
      deadCodeDisplay,
    });
  }, [
    graph,
    confidenceThreshold,
    activeSources,
    allowedRelations,
    searchQuery,
    colorMode,
    reachabilityMode,
    deadCodeDisplay,
  ]);

  // Синхронизация элементов React Flow с сохранением стабильных позиций
  useEffect(() => {
    if (positions.size === 0) return;

    const { flowNodes, flowEdges } = buildReactFlowElements(
      filteredNodes,
      filteredEdges,
      positions,
      blastRadius,
      callTrace,
      colorMode,
      searchQuery,
      reachabilityMode,
      deadCodeDisplay,
      direction,
      graph
    );

    const isDirectionChanged = lastDirectionRef.current !== direction;
    lastDirectionRef.current = direction;

    setNodes((currentNodes) => {
      if (isDirectionChanged || currentNodes.length === 0) {
        return flowNodes;
      }
      const currentPosMap = new Map(currentNodes.map((n) => [n.id, n.position]));
      return flowNodes.map((n) => {
        const existingPos = currentPosMap.get(n.id);
        return existingPos ? { ...n, position: existingPos } : n;
      });
    });

    setEdges(flowEdges);
  }, [
    filteredNodes,
    filteredEdges,
    positions,
    blastRadius,
    callTrace,
    colorMode,
    searchQuery,
    reachabilityMode,
    deadCodeDisplay,
    direction,
    graph,
    setNodes,
    setEdges,
  ]);

  // Автоматический зум и центрирование при готовности позиций
  useEffect(() => {
    if (!isLoadingLayout && positions.size > 0) {
      const timer = setTimeout(() => {
        fitView({ padding: 0.25, duration: 300 });
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [isLoadingLayout, positions, direction, fitView]);

  // Обработчик загрузки нового графа (из модалки или dropzone)
  const handleLoadGraph = useCallback(
    (newGraph: CanonicalGraph, summary: string, sourceName: string) => {
      setIsLoadingLayout(true);
      setGraph(newGraph);
      setDatasetName(sourceName);
      setIsCustomDataset(sourceName !== 'ДЕМО (Train Ticket)');
      setSelectedNodeId(null);
      setSelectedEdgeId(null);
      setBlastRadius(null);
      setCallTrace(null);
      setToast({
        type: 'success',
        message: `Датасет "${sourceName}" загружен: ${summary}`,
      });
    },
    []
  );

  // Drag & drop файлов на холст
  const handleCanvasDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    if (!e.dataTransfer.types.includes('Files')) return;
    setIsDragOverCanvas(true);
  }, []);

  const handleCanvasDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOverCanvas(false);
  }, []);

  const handleCanvasDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOverCanvas(false);

      const files = e.dataTransfer.files;
      if (!files || files.length === 0) return;

      try {
        const loadedFiles: { name: string; content: any }[] = [];
        for (let i = 0; i < files.length; i++) {
          const file = files[i];
          const text = await file.text();
          try {
            const json = JSON.parse(text);
            loadedFiles.push({ name: file.name, content: json });
          } catch (jsonErr: any) {
            throw new Error(`Файл ${file.name} не является корректным JSON (${jsonErr.message})`);
          }
        }

        const res = mergePipelineFiles(loadedFiles);
        handleLoadGraph(res.graph, res.summary, res.sourceFile);
      } catch (err: any) {
        setToast({
          type: 'error',
          message: err.message || 'Ошибка обработки перетащенных файлов',
        });
      }
    },
    [handleLoadGraph]
  );

  // Экспорт графа
  const handleExportPng = useCallback(async () => {
    setIsExporting(true);
    try {
      await exportGraphToPng(`archonity-${datasetName.replace(/[^a-z0-9_-]/gi, '_')}.png`);
      setToast({
        type: 'success',
        message: 'Граф успешно экспортирован в PNG (2x Retina)',
      });
    } catch (err: any) {
      setToast({
        type: 'error',
        message: `Ошибка экспорта в PNG: ${err.message}`,
      });
    } finally {
      setIsExporting(false);
    }
  }, [datasetName]);

  const handleExportSvg = useCallback(async () => {
    setIsExporting(true);
    try {
      await exportGraphToSvg(`archonity-${datasetName.replace(/[^a-z0-9_-]/gi, '_')}.svg`);
      setToast({
        type: 'success',
        message: 'Граф успешно экспортирован в векторный SVG',
      });
    } catch (err: any) {
      setToast({
        type: 'error',
        message: `Ошибка экспорта в SVG: ${err.message}`,
      });
    } finally {
      setIsExporting(false);
    }
  }, [datasetName]);

  const handleExportJson = useCallback(() => {
    try {
      exportGraphToJson(graph, 'canonical_graph.json');
      setToast({
        type: 'success',
        message: 'Канонический граф сохранен в canonical_graph.json',
      });
    } catch (err: any) {
      setToast({
        type: 'error',
        message: `Ошибка сохранения JSON: ${err.message}`,
      });
    }
  }, [graph]);

  // Обработчики кликов
  const handleNodeClick = useCallback((_event: React.MouseEvent, node: Node) => {
    setSelectedNodeId(node.id);
    setSelectedEdgeId(null);
  }, []);

  const handleEdgeClick = useCallback((_event: React.MouseEvent, edge: Edge) => {
    setSelectedEdgeId(edge.id);
    setSelectedNodeId(null);
  }, []);

  const handlePaneClick = useCallback(() => {
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
  }, []);

  const handleToggleSource = useCallback((src: SourceType) => {
    setActiveSources((prev) => ({
      ...prev,
      [src]: !prev[src],
    }));
  }, []);

  const handleToggleColorMode = useCallback(() => {
    setColorMode((prev) => (prev === 'by_source' ? 'by_protocol' : 'by_source'));
  }, []);

  const handleToggleDirection = useCallback(() => {
    setIsLoadingLayout(true);
    setDirection((prev) => (prev === 'RIGHT' ? 'DOWN' : 'RIGHT'));
  }, []);

  const handleActivateBlastRadius = useCallback(
    (nodeId: string) => {
      const res = calculateBlastRadius(graph, nodeId);
      setBlastRadius(res);
      setCallTrace(null);
    },
    [graph]
  );

  const handleClearBlastRadius = useCallback(() => {
    setBlastRadius(null);
  }, []);

  const handleToggleReachabilityMode = useCallback(() => {
    setReachabilityMode((prev) => (prev === 'RUNTIME_ONLY' ? 'ALL' : 'RUNTIME_ONLY'));
  }, []);

  const handleToggleDeadCodeDisplay = useCallback(() => {
    setDeadCodeDisplay((prev) => (prev === 'DIM' ? 'HIDE' : 'DIM'));
  }, []);

  const handleActivateCallTrace = useCallback(
    (serviceId: string, endpoint: EndpointInfo) => {
      const res = traceCallPath(graph, serviceId, endpoint);
      setCallTrace(res);
      setBlastRadius(null);
    },
    [graph]
  );

  const handleClearCallTrace = useCallback(() => {
    setCallTrace(null);
  }, []);

  const handleCloseInspector = useCallback(() => {
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
  }, []);

  // Поиск выбранных объектов для сайдбара
  const selectedNode = useMemo(
    () => graph.nodes.find((n) => n.id === selectedNodeId) || null,
    [graph.nodes, selectedNodeId]
  );

  const selectedEdge = useMemo(
    () => graph.edges.find((e) => e.id === selectedEdgeId) || null,
    [graph.edges, selectedEdgeId]
  );

  const transitiveEdgesCount = useMemo(
    () => graph.edges.filter((e) => e.sourceType === 'TRANSITIVE').length,
    [graph.edges]
  );

  const handleSelectEdgeFromTable = useCallback((edgeId: string) => {
    setSelectedEdgeId(edgeId);
    setSelectedNodeId(null);
  }, []);

  const handleResetAll = useCallback(() => {
    fitView({ padding: 0.25, duration: 300 });
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
    setBlastRadius(null);
    setCallTrace(null);
    setReachabilityMode('RUNTIME_ONLY');
    setDeadCodeDisplay('DIM');
    setSearchQuery('');
    setConfidenceThreshold(0.35);
    setActiveSources({
      AST_EXACT: true,
      CONFIG: true,
      ML_PREDICTED: true,
      LLM_JUDGE_VERIFIED: true,
      TRANSITIVE: false,
    });
    setColorMode('by_source');
    setDirection('RIGHT');
  }, [fitView]);

  // Сброс трейса или выделения по Escape
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (callTrace) {
          handleClearCallTrace();
        } else if (selectedEdgeId || selectedNodeId) {
          setSelectedEdgeId(null);
          setSelectedNodeId(null);
          setBlastRadius(null);
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [callTrace, selectedEdgeId, selectedNodeId, handleClearCallTrace]);

  return (
    <div className="visualizer-container">
      <Toolbar
        confidenceThreshold={confidenceThreshold}
        onThresholdChange={setConfidenceThreshold}
        activeSources={activeSources}
        onToggleSource={handleToggleSource}
        colorMode={colorMode}
        onToggleColorMode={handleToggleColorMode}
        direction={direction}
        onToggleDirection={handleToggleDirection}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        onResetAll={handleResetAll}
        totalEdgesCount={graph.edges.length}
        visibleEdgesCount={filteredEdges.length}
        nodesCount={graph.nodes.length}
        transitiveEdgesCount={transitiveEdgesCount}
        datasetName={datasetName}
        isCustomDataset={isCustomDataset}
        onOpenDataLoader={() => setIsDataLoaderOpen(true)}
        onExportPng={handleExportPng}
        onExportSvg={handleExportSvg}
        onExportJson={handleExportJson}
        isExporting={isExporting}
        reachabilityMode={reachabilityMode}
        onToggleReachabilityMode={handleToggleReachabilityMode}
        deadCodeDisplay={deadCodeDisplay}
        onToggleDeadCodeDisplay={handleToggleDeadCodeDisplay}
        unreachableEdgesCount={unreachableEdgesCount}
      />

      <div className="visualizer-body" style={{ userSelect: isDragging ? 'none' : 'auto' }}>
        <div
          className="canvas-wrapper"
          style={{ width: `calc(100vw - ${sidebarWidth}px - 5px)` }}
          onDragOver={handleCanvasDragOver}
          onDragLeave={handleCanvasDragLeave}
          onDrop={handleCanvasDrop}
        >
          {/* Плавающий CAD-бейдж активного сквозного трейса над холстом */}
          <FloatingTraceBadge
            callTrace={callTrace}
            onClearCallTrace={handleClearCallTrace}
          />

          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={handleNodeClick}
            onEdgeClick={handleEdgeClick}
            onPaneClick={handlePaneClick}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            fitView
            fitViewOptions={{ padding: 0.25 }}
            minZoom={0.15}
            maxZoom={2.0}
          >
            <Background color="#D6D3CD" gap={16} size={1.5} />
            <Controls showInteractive={false} />
            <MiniMap
              nodeColor={(n) => {
                if (n.type === 'service') return '#18181B';
                if (n.type === 'database') return '#0369A1';
                return '#18181B';
              }}
              maskColor="rgba(247, 246, 242, 0.75)"
            />
          </ReactFlow>

          {/* Индикатор перетаскивания файлов */}
          {isDragOverCanvas && (
            <div className="canvas-drop-overlay">
              <FileUp size={36} color="#0969DA" />
              <div className="canvas-drop-title">БРОСЬТЕ JSON ФАЙЛЫ ДЛЯ АНАЛИЗА В ARCHONITY</div>
              <div className="canvas-drop-subtitle">
                canonical_graph.json, confirmed_edges.json, evidence.json, facts.json
              </div>
            </div>
          )}

          {isLoadingLayout && (
            <div className="layout-loading-indicator">
              <div className="spinner" />
              <span>ELK.js Layout...</span>
            </div>
          )}
        </div>

        <div
          className={`resize-handle ${isDragging ? 'dragging' : ''}`}
          onMouseDown={handleMouseDownResize}
          onDoubleClick={handleResetSidebarWidth}
          title="Потяните для изменения ширины сайдбара (двойной клик для сброса)"
        />

        <div style={{ width: `${sidebarWidth}px`, height: '100%', flexShrink: 0, display: 'flex' }}>
          <Inspector
            selectedEdge={selectedEdge}
            selectedNode={selectedNode}
            blastRadius={blastRadius}
            onActivateBlastRadius={handleActivateBlastRadius}
            onClearBlastRadius={handleClearBlastRadius}
            onClose={handleCloseInspector}
            graph={graph}
            filteredEdges={filteredEdges}
            onSelectEdge={handleSelectEdgeFromTable}
            callTrace={callTrace}
            onActivateCallTrace={handleActivateCallTrace}
            onClearCallTrace={handleClearCallTrace}
          />
        </div>
      </div>

      {/* Модальное окно загрузки данных */}
      <DataLoaderModal
        isOpen={isDataLoaderOpen}
        onClose={() => setIsDataLoaderOpen(false)}
        onLoadGraph={handleLoadGraph}
      />

      {/* Всплывающие уведомления (Toast) */}
      {toast && (
        <div className={`toast-banner ${toast.type}`}>
          {toast.type === 'success' && <CheckCircle2 size={14} color="#10B981" />}
          {toast.type === 'error' && <AlertCircle size={14} color="#EF4444" />}
          {toast.type === 'warning' && <AlertTriangle size={14} color="#F59E0B" />}
          {toast.type === 'info' && <Info size={14} color="#3B82F6" />}
          <span>{toast.message}</span>
          <button
            type="button"
            className="toast-close-btn"
            onClick={() => setToast(null)}
            title="Закрыть"
          >
            <X size={12} />
          </button>
        </div>
      )}
    </div>
  );
};

export default function App() {
  return (
    <ReactFlowProvider>
      <VisualizerCanvas />
    </ReactFlowProvider>
  );
}
