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

  // Исходный граф (по умолчанию демо-срез Train Ticket)
  const [graph] = useState(demoGraph);

  // Состояния фильтров
  const [confidenceThreshold, setConfidenceThreshold] = useState<number>(0.35);
  const [allowedSources, setAllowedSources] = useState<Set<SourceType>>(
    new Set(['AST_EXACT', 'CONFIG', 'ML_PREDICTED', 'LLM_JUDGE_VERIFIED', 'TRANSITIVE'])
  );
  const [allowedRelations] = useState<Set<RelationType>>(
    new Set(['REST_HTTP', 'DATABASE', 'MESSAGE_QUEUE', 'TRANSITIVE'])
  );
  const [showTransitive, setShowTransitive] = useState<boolean>(true);
  const [colorMode, setColorMode] = useState<ColorMode>('by_source');
  const [direction, setDirection] = useState<DagDirection>('RIGHT');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Выбранные сущности и Blast Radius
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [blastRadius, setBlastRadius] = useState<BlastRadiusResult | null>(null);

  // ELK.js раскладка
  const [positions, setPositions] = useState<Map<string, { x: number; y: number }>>(new Map());
  const [isLoadingLayout, setIsLoadingLayout] = useState<boolean>(true);

  // React Flow узлы и ребра
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<NodeData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge<EdgeData>>([]);

  // Фильтрация графа
  const { filteredNodes, filteredEdges } = useMemo(() => {
    return filterGraph(graph, {
      confidenceThreshold,
      allowedSources,
      allowedRelations,
      searchQuery,
      colorMode,
      showTransitive,
    });
  }, [
    graph,
    confidenceThreshold,
    allowedSources,
    allowedRelations,
    searchQuery,
    colorMode,
    showTransitive,
  ]);

  // Запуск раскладки при изменении состава узлов или направления
  useEffect(() => {
    let isCancelled = false;
    setIsLoadingLayout(true);

    computeLayout(filteredNodes, filteredEdges, direction)
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
  }, [filteredNodes, filteredEdges, direction]);

  // Синхронизация с React Flow элементами
  useEffect(() => {
    const { flowNodes, flowEdges } = buildReactFlowElements(
      filteredNodes,
      filteredEdges,
      positions,
      blastRadius,
      colorMode,
      searchQuery
    );

    setNodes(flowNodes);
    setEdges(flowEdges);
  }, [
    filteredNodes,
    filteredEdges,
    positions,
    blastRadius,
    colorMode,
    searchQuery,
    setNodes,
    setEdges,
  ]);

  // Автоматический зум и центрирование при обновлении раскладки позиций
  useEffect(() => {
    if (!isLoadingLayout && positions.size > 0) {
      const timer = setTimeout(() => {
        fitView({ padding: 0.25, duration: 300 });
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [isLoadingLayout, positions, fitView]);

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
    setAllowedSources((prev) => {
      const next = new Set(prev);
      if (next.has(src)) {
        if (next.size > 1) next.delete(src);
      } else {
        next.add(src);
      }
      return next;
    });
  }, []);

  const handleToggleColorMode = useCallback(() => {
    setColorMode((prev) => (prev === 'by_source' ? 'by_protocol' : 'by_source'));
  }, []);

  const handleToggleDirection = useCallback(() => {
    setDirection((prev) => (prev === 'RIGHT' ? 'DOWN' : 'RIGHT'));
  }, []);

  const handleToggleTransitive = useCallback(() => {
    setShowTransitive((prev) => !prev);
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
    fitView({ padding: 0.2, duration: 300 });
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
        allowedSources={allowedSources}
        onToggleSource={handleToggleSource}
        colorMode={colorMode}
        onToggleColorMode={handleToggleColorMode}
        direction={direction}
        onToggleDirection={handleToggleDirection}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        onFitView={handleFitView}
        showTransitive={showTransitive}
        onToggleTransitive={handleToggleTransitive}
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
