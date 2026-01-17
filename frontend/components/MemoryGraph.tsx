"use client";
import React, { useEffect, useRef, useState } from 'react';
import { API_URL } from '@/lib/api';
import { Loader2, ZoomIn, ZoomOut, RefreshCw } from 'lucide-react';

interface GraphNode {
    id: string;
    label: string;
    full_text: string;
    timestamp: string;
    source: string;
    x?: number;
    y?: number;
    vx?: number;
    vy?: number;
}

interface GraphEdge {
    source: string;
    target: string;
    weight: number;
}

interface GraphData {
    nodes: GraphNode[];
    edges: GraphEdge[];
    error?: string;
}

export default function MemoryGraph() {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const [data, setData] = useState<GraphData | null>(null);
    const [loading, setLoading] = useState(true);
    const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
    const [zoom, setZoom] = useState(1);
    const [threshold, setThreshold] = useState(0.7);
    const nodesRef = useRef<GraphNode[]>([]);

    const fetchData = async () => {
        setLoading(true);
        try {
            const res = await fetch(`${API_URL}/stats/memory_graph?threshold=${threshold}&limit=100`);
            if (res.ok) {
                const graphData = await res.json();
                // ランダムな初期位置を設定
                graphData.nodes.forEach((node: GraphNode) => {
                    node.x = Math.random() * 600 + 100;
                    node.y = Math.random() * 400 + 100;
                    node.vx = 0;
                    node.vy = 0;
                });
                setData(graphData);
                nodesRef.current = graphData.nodes;
            }
        } catch (e) {
            console.error('Failed to fetch graph:', e);
        }
        setLoading(false);
    };

    useEffect(() => {
        fetchData();
    }, [threshold]);

    // Force-directed simulation
    useEffect(() => {
        if (!data || data.nodes.length === 0) return;

        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const nodes = nodesRef.current;
        const edges = data.edges;

        let animationId: number;

        const simulate = () => {
            // Force simulation
            const k = 50; // Ideal spring length
            const gravity = 0.1;
            const centerX = canvas.width / 2;
            const centerY = canvas.height / 2;

            // Apply forces
            nodes.forEach((node, i) => {
                // Center gravity
                node.vx! += (centerX - node.x!) * gravity * 0.01;
                node.vy! += (centerY - node.y!) * gravity * 0.01;

                // Repulsion between all nodes
                nodes.forEach((other, j) => {
                    if (i === j) return;
                    const dx = node.x! - other.x!;
                    const dy = node.y! - other.y!;
                    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
                    const force = (k * k) / dist;
                    node.vx! += (dx / dist) * force * 0.01;
                    node.vy! += (dy / dist) * force * 0.01;
                });
            });

            // Attraction along edges
            edges.forEach(edge => {
                const source = nodes.find(n => n.id === edge.source);
                const target = nodes.find(n => n.id === edge.target);
                if (!source || !target) return;

                const dx = target.x! - source.x!;
                const dy = target.y! - source.y!;
                const dist = Math.sqrt(dx * dx + dy * dy) || 1;
                const force = (dist - k) * edge.weight * 0.01;

                source.vx! += (dx / dist) * force;
                source.vy! += (dy / dist) * force;
                target.vx! -= (dx / dist) * force;
                target.vy! -= (dy / dist) * force;
            });

            // Update positions with damping
            nodes.forEach(node => {
                node.vx! *= 0.9;
                node.vy! *= 0.9;
                node.x! += node.vx!;
                node.y! += node.vy!;
                // Boundary
                node.x = Math.max(50, Math.min(canvas.width - 50, node.x!));
                node.y = Math.max(50, Math.min(canvas.height - 50, node.y!));
            });

            // Draw
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.save();
            ctx.scale(zoom, zoom);

            // Draw edges
            edges.forEach(edge => {
                const source = nodes.find(n => n.id === edge.source);
                const target = nodes.find(n => n.id === edge.target);
                if (!source || !target) return;

                ctx.beginPath();
                ctx.moveTo(source.x!, source.y!);
                ctx.lineTo(target.x!, target.y!);
                ctx.strokeStyle = `rgba(100, 180, 255, ${edge.weight * 0.5})`;
                ctx.lineWidth = edge.weight * 2;
                ctx.stroke();
            });

            // Draw nodes
            nodes.forEach(node => {
                ctx.beginPath();
                ctx.arc(node.x!, node.y!, 8, 0, Math.PI * 2);
                ctx.fillStyle = node === selectedNode ? '#60a5fa' : '#3b82f6';
                ctx.fill();
                ctx.strokeStyle = '#1d4ed8';
                ctx.lineWidth = 2;
                ctx.stroke();
            });

            ctx.restore();
            animationId = requestAnimationFrame(simulate);
        };

        simulate();

        return () => cancelAnimationFrame(animationId);
    }, [data, zoom, selectedNode]);

    // Handle click
    const handleCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
        const canvas = canvasRef.current;
        if (!canvas) return;

        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) / zoom;
        const y = (e.clientY - rect.top) / zoom;

        const nodes = nodesRef.current;
        const clicked = nodes.find(node => {
            const dx = node.x! - x;
            const dy = node.y! - y;
            return Math.sqrt(dx * dx + dy * dy) < 15;
        });

        setSelectedNode(clicked || null);
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <Loader2 className="w-8 h-8 animate-spin text-blue-400" />
            </div>
        );
    }

    if (!data || data.nodes.length === 0) {
        return (
            <div className="flex items-center justify-center h-64 text-gray-500">
                記憶データがありません
            </div>
        );
    }

    return (
        <div className="flex flex-col h-full">
            {/* Controls */}
            <div className="flex items-center gap-4 p-4 border-b border-white/10">
                <div className="flex items-center gap-2">
                    <button onClick={() => setZoom(z => Math.max(0.5, z - 0.1))} className="p-2 glass rounded-lg hover:bg-white/10">
                        <ZoomOut className="w-4 h-4" />
                    </button>
                    <span className="text-sm text-gray-400">{Math.round(zoom * 100)}%</span>
                    <button onClick={() => setZoom(z => Math.min(2, z + 0.1))} className="p-2 glass rounded-lg hover:bg-white/10">
                        <ZoomIn className="w-4 h-4" />
                    </button>
                </div>
                <div className="flex items-center gap-2">
                    <span className="text-sm text-gray-400">類似度閾値:</span>
                    <input
                        type="range"
                        min="0.5"
                        max="0.95"
                        step="0.05"
                        value={threshold}
                        onChange={(e) => setThreshold(parseFloat(e.target.value))}
                        className="w-24"
                    />
                    <span className="text-sm text-blue-400">{threshold.toFixed(2)}</span>
                </div>
                <button onClick={fetchData} className="p-2 glass rounded-lg hover:bg-white/10">
                    <RefreshCw className="w-4 h-4" />
                </button>
                <div className="text-sm text-gray-500 ml-auto">
                    {data.nodes.length} nodes / {data.edges.length} edges
                </div>
            </div>

            {/* Canvas */}
            <div className="flex-1 relative">
                <canvas
                    ref={canvasRef}
                    width={800}
                    height={500}
                    onClick={handleCanvasClick}
                    className="w-full h-full bg-black/30 rounded-lg cursor-crosshair"
                />
            </div>

            {/* Selected node info */}
            {selectedNode && (
                <div className="p-4 border-t border-white/10 bg-black/30">
                    <h4 className="font-semibold text-blue-300 mb-2">選択された記憶</h4>
                    <p className="text-sm text-gray-300">{selectedNode.full_text}</p>
                    <p className="text-xs text-gray-500 mt-2">
                        Source: {selectedNode.source} | {selectedNode.timestamp}
                    </p>
                </div>
            )}
        </div>
    );
}
