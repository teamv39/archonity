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
    TRANSITIVE: true,
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

  const handleFitView = useCallback(() => {
    fitView({ padding: 0.25, duration: 300 });
  }, [fitView]);

  // Поиск выбранных объектов для сайдбара
  const selectedNode = useMemo(
    () => graph.nodes.find((n) => n.id === selectedNodeId) || null,
    [graph.nodes, selectedNodeId]
  );

  const selectedEdge = useMemo(
    () => graph.edges.find((e) => e.id === selectedEdgeId) || null,
    [graph.edges, selectedEdgeId]
  );

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
        onFitView={handleFitView}
        totalEdgesCount={graph.edges.length}
        visibleEdgesCount={filteredEdges.length}
      />

      <div className="canvas-wrapper">
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
          <Background color="#1e293b" gap={24} size={1.2} />
          <Controls showInteractive={false} />
          <MiniMap
            nodeColor={(n) => {
              if (n.type === 'service') return '#38bdf8';
              if (n.type === 'database') return '#f59e0b';
              return '#a855f7';
            }}
            maskColor="rgba(15, 23, 42, 0.7)"
          />
        </ReactFlow>
      </div>

      {isLoadingLayout && (
        <div className="layout-loading-indicator">
          <div className="spinner" />
          <span>Раскладка ELK.js...</span>
        </div>
      )}

      <Inspector
        selectedEdge={selectedEdge}
        selectedNode={selectedNode}
        blastRadius={blastRadius}
        onActivateBlastRadius={handleActivateBlastRadius}
        onClearBlastRadius={handleClearBlastRadius}
        onClose={handleCloseInspector}
        graph={graph}
      />
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
