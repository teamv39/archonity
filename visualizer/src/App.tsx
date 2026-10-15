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

import type {
  SourceType,
  RelationType,
  ColorMode,
  DagDirection,
  BlastRadiusResult,
} from './types/graph';
import { demoGraph } from './data/demoData';
import { computeLayout } from './layout/layoutEngine';
import {
  filterGraph,
  buildReactFlowElements,
  calculateBlastRadius,
  type NodeData,
  type EdgeData,
} from './adapters/graphAdapter';

import { ServiceNode } from './components/nodes/ServiceNode';
import { DatabaseNode } from './components/nodes/DatabaseNode';
import { QueueNode } from './components/nodes/QueueNode';
import { CustomEdge } from './components/edges/CustomEdge';
import { Toolbar } from './components/toolbar/Toolbar';
import { Inspector } from './components/inspector/Inspector';

import './App.css';

const nodeTypes = {
  service: ServiceNode,
  database: DatabaseNode,
  message_queue: QueueNode,
};

const edgeTypes = {
  custom: CustomEdge,
};

const VisualizerCanvas: React.FC = () => {
  const { fitView } = useReactFlow();

  // Исходный граф (демо-срез Train Ticket)
  const [graph] = useState(demoGraph);

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

  // Базовая стабильная раскладка графа
  const [positions, setPositions] = useState<Map<string, { x: number; y: number }>>(new Map());
  const [isLoadingLayout, setIsLoadingLayout] = useState<boolean>(true);
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
    setIsLoadingLayout(true);

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
  const { filteredNodes, filteredEdges } = useMemo(() => {
    return filterGraph(graph, {
      confidenceThreshold,
      activeSources,
      allowedRelations,
      searchQuery,
      colorMode,
    });
  }, [
    graph,
    confidenceThreshold,
    activeSources,
    allowedRelations,
    searchQuery,
    colorMode,
  ]);

  // Синхронизация элементов React Flow с сохранением стабильных позиций
  useEffect(() => {
    if (positions.size === 0) return;

    const { flowNodes, flowEdges } = buildReactFlowElements(
      filteredNodes,
      filteredEdges,
      positions,
      blastRadius,
      colorMode,
      searchQuery,
      direction
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
    colorMode,
    searchQuery,
    direction,
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
    setDirection((prev) => (prev === 'RIGHT' ? 'DOWN' : 'RIGHT'));
  }, []);

  const handleActivateBlastRadius = useCallback(
    (nodeId: string) => {
      const res = calculateBlastRadius(graph, nodeId);
      setBlastRadius(res);
    },
    [graph]
  );

  const handleClearBlastRadius = useCallback(() => {
    setBlastRadius(null);
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
      />

      <div className="visualizer-body" style={{ userSelect: isDragging ? 'none' : 'auto' }}>
        <div
          className="canvas-wrapper"
          style={{ width: `calc(100vw - ${sidebarWidth}px - 5px)` }}
        >
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
          />
        </div>
      </div>
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
