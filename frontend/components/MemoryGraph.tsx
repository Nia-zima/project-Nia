"use client";
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { apiClient } from '@/lib/apiClient';
import { Loader2, ZoomIn, ZoomOut, RefreshCw } from 'lucide-react';

type MemoryCategory = 'memory' | 'policy' | 'identity' | 'public' | 'decision' | 'other';
type TimeRange = 'all' | '7d' | '30d' | '90d';

interface GraphNode {
    id: string;
    label: string;
    full_text: string;
    timestamp: string;
    source: string;
    category?: MemoryCategory;
    degree?: number;
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

const CATEGORY_LABEL: Record<MemoryCategory, string> = {
    memory: '記憶',
    policy: '方針',
    identity: '自己定義',
    public: '公開/配信',
    decision: '判断',
    other: 'その他',
};

const CATEGORY_COLOR: Record<MemoryCategory, string> = {
    memory: '#38bdf8',
    policy: '#f59e0b',
    identity: '#34d399',
    public: '#f97316',
    decision: '#f43f5e',
    other: '#a1a1aa',
};

const categoryKeywords: Array<{ category: MemoryCategory; words: string[] }> = [
    { category: 'memory', words: ['覚えて', '記録', '保存', 'メモ', '忘れない'] },
    { category: 'policy', words: ['設定', 'ルール', '方針', '今後', 'これから'] },
    { category: 'identity', words: ['名前', '呼び方', 'identity', 'origin', 'ニア'] },
    { category: 'public', words: ['配信', '公開', '視聴者', 'sns', '投稿', '拡散'] },
    { category: 'decision', words: ['決めて', '判断', '結論', '最適', 'おすすめ', 'ランキング'] },
];
const SIMULATION_DURATION_MS = 4500;

// ── Barnes-Hut Quad-tree for O(n log n) repulsion ──

interface QuadBody { x: number; y: number; mass: number }

interface QuadNode {
    x: number; y: number;          // center of mass
    mass: number;
    size: number;                   // side length of this cell
    cx: number; cy: number;         // cell center
    body: QuadBody | null;          // leaf body (null for internal)
    nw: QuadNode | null;
    ne: QuadNode | null;
    sw: QuadNode | null;
    se: QuadNode | null;
}

function createQuadNode(cx: number, cy: number, size: number): QuadNode {
    return { x: 0, y: 0, mass: 0, size, cx, cy, body: null, nw: null, ne: null, sw: null, se: null };
}

const MAX_QUAD_DEPTH = 20;

function insertBody(node: QuadNode, body: QuadBody, depth: number = 0): void {
    if (node.mass === 0) {
        // Empty leaf — place body here
        node.body = body;
        node.x = body.x;
        node.y = body.y;
        node.mass = body.mass;
        return;
    }

    // 深さ上限: 同一座標のノードが無限再帰するのを防止
    if (depth >= MAX_QUAD_DEPTH) {
        const totalMass = node.mass + body.mass;
        node.x = (node.x * node.mass + body.x * body.mass) / totalMass;
        node.y = (node.y * node.mass + body.y * body.mass) / totalMass;
        node.mass = totalMass;
        return;
    }

    // If this is a leaf with one body, subdivide
    if (node.body !== null) {
        subdivide(node);
        const old = node.body;
        node.body = null;
        insertIntoChild(node, old, depth);
    }

    // Insert new body into correct child
    insertIntoChild(node, body, depth);

    // Update center of mass
    const totalMass = node.mass + body.mass;
    node.x = (node.x * node.mass + body.x * body.mass) / totalMass;
    node.y = (node.y * node.mass + body.y * body.mass) / totalMass;
    node.mass = totalMass;
}

function subdivide(node: QuadNode): void {
    const hs = node.size / 2;
    const qs = node.size / 4;
    node.nw = createQuadNode(node.cx - qs, node.cy - qs, hs);
    node.ne = createQuadNode(node.cx + qs, node.cy - qs, hs);
    node.sw = createQuadNode(node.cx - qs, node.cy + qs, hs);
    node.se = createQuadNode(node.cx + qs, node.cy + qs, hs);
}

function insertIntoChild(node: QuadNode, body: QuadBody, depth: number = 0): void {
    const west = body.x < node.cx;
    const north = body.y < node.cy;
    const child = north ? (west ? node.nw! : node.ne!) : (west ? node.sw! : node.se!);
    insertBody(child, body, depth + 1);
}

const THETA = 0.8; // Barnes-Hut opening angle

function computeRepulsion(
    node: QuadNode,
    body: QuadBody,
    k: number,
    outFx: { v: number },
    outFy: { v: number },
): void {
    if (node.mass === 0) return;
    const dx = body.x - node.x;
    const dy = body.y - node.y;
    const dist = Math.sqrt(dx * dx + dy * dy) || 1;

    // If leaf with single body and it's the same body, skip
    if (node.body !== null && dx === 0 && dy === 0) return;

    // Barnes-Hut: if cell is far enough, treat as single body
    if (node.body !== null || node.size / dist < THETA) {
        const force = (k * k * node.mass) / dist;
        outFx.v += (dx / dist) * force * 0.01;
        outFy.v += (dy / dist) * force * 0.01;
        return;
    }

    // Otherwise recurse into children
    if (node.nw) computeRepulsion(node.nw, body, k, outFx, outFy);
    if (node.ne) computeRepulsion(node.ne, body, k, outFx, outFy);
    if (node.sw) computeRepulsion(node.sw, body, k, outFx, outFy);
    if (node.se) computeRepulsion(node.se, body, k, outFx, outFy);
}

function inferCategory(node: GraphNode): MemoryCategory {
    const text = `${node.source || ''} ${node.full_text || ''}`.toLowerCase();
    for (const rule of categoryKeywords) {
        if (rule.words.some((w) => text.includes(w.toLowerCase()))) {
            return rule.category;
        }
    }
    return 'other';
}

export default function MemoryGraph() {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const [data, setData] = useState<GraphData | null>(null);
    const [loading, setLoading] = useState(true);
    const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
    const [zoom, setZoom] = useState(1);
    const [threshold, setThreshold] = useState(0.7);
    const [categoryFilter, setCategoryFilter] = useState<'all' | MemoryCategory>('all');
    const [timeRange, setTimeRange] = useState<TimeRange>('30d');
    const [showLabels, setShowLabels] = useState(true);
    const [isSimulating, setIsSimulating] = useState(true);
    const nodesRef = useRef<GraphNode[]>([]);

    const fetchData = async () => {
        setLoading(true);
        try {
            const graphData = await apiClient.fetchMemoryGraph(threshold, 100) as unknown as GraphData;
            {
                const degreeMap: Record<string, number> = {};
                (graphData.edges || []).forEach((edge: GraphEdge) => {
                    degreeMap[edge.source] = (degreeMap[edge.source] || 0) + 1;
                    degreeMap[edge.target] = (degreeMap[edge.target] || 0) + 1;
                });
                // ランダムな初期位置を設定
                graphData.nodes.forEach((node: GraphNode) => {
                    node.x = Math.random() * 600 + 100;
                    node.y = Math.random() * 400 + 100;
                    node.vx = 0;
                    node.vy = 0;
                    node.category = inferCategory(node);
                    node.degree = degreeMap[node.id] || 0;
                });
                setData(graphData);
                nodesRef.current = graphData.nodes;
                setIsSimulating(true);
            }
        } catch (e) {
            console.error('Failed to fetch graph:', e);
        }
        setLoading(false);
    };

    const filteredData = useMemo(() => {
        if (!data) return null;

        let filteredNodes = [...data.nodes];
        if (categoryFilter !== 'all') {
            filteredNodes = filteredNodes.filter((n) => n.category === categoryFilter);
        }

        if (timeRange !== 'all') {
            const nowMs = Date.now();
            const days = timeRange === '7d' ? 7 : timeRange === '30d' ? 30 : 90;
            const cutoffMs = nowMs - days * 24 * 60 * 60 * 1000;
            filteredNodes = filteredNodes.filter((n) => {
                if (!n.timestamp) return false;
                const ts = Date.parse(n.timestamp);
                if (Number.isNaN(ts)) return false;
                return ts >= cutoffMs;
            });
        }

        const nodeSet = new Set(filteredNodes.map((n) => n.id));
        const nodes = data.nodes.filter((n) => nodeSet.has(n.id));
        const edges = data.edges.filter((e) => nodeSet.has(e.source) && nodeSet.has(e.target));
        return { ...data, nodes, edges };
    }, [data, categoryFilter, timeRange]);

    const topNodes = useMemo(() => {
        const nodes = filteredData?.nodes || [];
        return [...nodes].sort((a, b) => (b.degree || 0) - (a.degree || 0)).slice(0, 8);
    }, [filteredData]);

    useEffect(() => {
        fetchData();
    }, [threshold]);

    // Force-directed simulation
    useEffect(() => {
        if (!filteredData || filteredData.nodes.length === 0) return;

        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const nodes = filteredData.nodes;
        const edges = filteredData.edges;
        nodesRef.current = nodes;

        let animationId: number;
        const startedAt = performance.now();

        // Pre-build node lookup map for O(1) edge resolution
        const nodeMap = new Map<string, GraphNode>();
        nodes.forEach(n => nodeMap.set(n.id, n));

        const simulate = () => {
            const k = 50; // Ideal spring length
            const gravity = 0.1;
            const centerX = canvas.width / 2;
            const centerY = canvas.height / 2;

            // Build Quad-tree for Barnes-Hut repulsion (O(n log n))
            const treeSize = Math.max(canvas.width, canvas.height) * 2;
            const root = createQuadNode(centerX, centerY, treeSize);
            nodes.forEach(node => {
                insertBody(root, { x: node.x!, y: node.y!, mass: 1 });
            });

            // Apply forces
            nodes.forEach((node) => {
                // Center gravity
                node.vx! += (centerX - node.x!) * gravity * 0.01;
                node.vy! += (centerY - node.y!) * gravity * 0.01;

                // Repulsion via Quad-tree (Barnes-Hut)
                const fx = { v: 0 };
                const fy = { v: 0 };
                computeRepulsion(root, { x: node.x!, y: node.y!, mass: 1 }, k, fx, fy);
                node.vx! += fx.v;
                node.vy! += fy.v;
            });

            // Attraction along edges (O(E))
            edges.forEach(edge => {
                const source = nodeMap.get(edge.source);
                const target = nodeMap.get(edge.target);
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
                node.x = Math.max(50, Math.min(canvas.width - 50, node.x!));
                node.y = Math.max(50, Math.min(canvas.height - 50, node.y!));
            });

            // Draw
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.save();
            ctx.scale(zoom, zoom);

            // Draw edges
            edges.forEach(edge => {
                const source = nodeMap.get(edge.source);
                const target = nodeMap.get(edge.target);
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
                const category = node.category || 'other';
                const degree = node.degree || 0;
                const radius = 6 + Math.min(7, degree * 0.6);
                ctx.beginPath();
                ctx.arc(node.x!, node.y!, radius, 0, Math.PI * 2);
                ctx.fillStyle = node === selectedNode ? '#93c5fd' : CATEGORY_COLOR[category];
                ctx.fill();
                ctx.strokeStyle = node === selectedNode ? '#1d4ed8' : '#0f172a';
                ctx.lineWidth = node === selectedNode ? 2 : 1.5;
                ctx.stroke();
            });

            if (showLabels) {
                const topNodeIds = new Set(topNodes.map((n) => n.id));
                nodes.forEach((node) => {
                    if (!topNodeIds.has(node.id) && node !== selectedNode) return;
                    ctx.font = '12px sans-serif';
                    ctx.fillStyle = '#e5e7eb';
                    ctx.textAlign = 'center';
                    const label = node.label.length > 20 ? `${node.label.slice(0, 20)}...` : node.label;
                    ctx.fillText(label, node.x!, node.y! - 14);
                });
            }

            ctx.restore();
            if (performance.now() - startedAt >= SIMULATION_DURATION_MS) {
                setIsSimulating(false);
                return;
            }
            animationId = requestAnimationFrame(simulate);
        };

        setIsSimulating(true);
        simulate();

        return () => cancelAnimationFrame(animationId);
    }, [filteredData, zoom, selectedNode, showLabels, topNodes]);

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
            <div className="flex items-center gap-4 p-4 border-b border-white/10 flex-wrap">
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
                <div className="flex items-center gap-2">
                    <span className="text-sm text-gray-400">分類:</span>
                    <select
                        value={categoryFilter}
                        onChange={(e) => setCategoryFilter(e.target.value as 'all' | MemoryCategory)}
                        className="rounded-lg bg-black/30 px-2 py-1 text-xs text-gray-200 border border-white/10"
                    >
                        <option value="all">全て</option>
                        <option value="memory">記憶</option>
                        <option value="policy">方針</option>
                        <option value="identity">自己定義</option>
                        <option value="public">公開/配信</option>
                        <option value="decision">判断</option>
                        <option value="other">その他</option>
                    </select>
                </div>
                <div className="flex items-center gap-2">
                    <span className="text-sm text-gray-400">期間:</span>
                    <select
                        value={timeRange}
                        onChange={(e) => setTimeRange(e.target.value as TimeRange)}
                        className="rounded-lg bg-black/30 px-2 py-1 text-xs text-gray-200 border border-white/10"
                    >
                        <option value="7d">7日</option>
                        <option value="30d">30日</option>
                        <option value="90d">90日</option>
                        <option value="all">全期間</option>
                    </select>
                </div>
                <label className="text-xs text-gray-400 flex items-center gap-2">
                    <input
                        type="checkbox"
                        checked={showLabels}
                        onChange={(e) => setShowLabels(e.target.checked)}
                    />
                    重要ノードにラベル表示
                </label>
                <button onClick={fetchData} className="p-2 glass rounded-lg hover:bg-white/10">
                    <RefreshCw className="w-4 h-4" />
                </button>
                <span className={`text-xs ${isSimulating ? 'text-amber-300' : 'text-emerald-300'}`}>
                    {isSimulating ? '配置を計算中…' : '配置を固定'}
                </span>
                <div className="text-sm text-gray-500 ml-auto">
                    {(filteredData?.nodes.length || 0)} nodes / {(filteredData?.edges.length || 0)} edges
                </div>
            </div>
            <div className="px-4 py-2 text-xs text-gray-400 border-b border-white/10 flex flex-wrap gap-3">
                {(Object.keys(CATEGORY_LABEL) as MemoryCategory[]).map((key) => (
                    <span key={key} className="inline-flex items-center gap-1">
                        <span className="inline-block w-2 h-2 rounded-full" style={{ backgroundColor: CATEGORY_COLOR[key] }} />
                        {CATEGORY_LABEL[key]}
                    </span>
                ))}
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
                        分類: {CATEGORY_LABEL[selectedNode.category || 'other']} | 接続数: {selectedNode.degree || 0}
                    </p>
                    <p className="text-xs text-gray-500 mt-1">
                        Source: {selectedNode.source} | {selectedNode.timestamp}
                    </p>
                </div>
            )}
        </div>
    );
}
