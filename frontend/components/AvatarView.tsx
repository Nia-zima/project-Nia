"use client";
import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils, VRM } from '@pixiv/three-vrm';

// ── Gesture System Types ─────────────────────────────────────────

interface GestureKeyframe {
    bone: string;
    axis: 'x' | 'y' | 'z';
    target: number;
    duration: number;     // ms for this keyframe
    delay?: number;       // ms delay before this keyframe starts
}

interface GesturePreset {
    name: string;
    keyframes: GestureKeyframe[];
    totalDuration: number;
    returnDuration: number;
}

interface ActiveGesture {
    preset: GesturePreset;
    startTime: number;
    phase: 'play' | 'return';
    boneStates: Map<string, { axis: string; from: number; target: number }>;
}

// ── Built-in Gesture Presets ─────────────────────────────────────

const GESTURE_PRESETS: Record<string, GesturePreset> = {
    nod: {
        name: 'nod',
        keyframes: [
            { bone: 'head', axis: 'x', target: -0.18, duration: 200 },
            { bone: 'head', axis: 'x', target: 0.0, duration: 200 },
        ],
        totalDuration: 400,
        returnDuration: 200,
    },
    wave: {
        name: 'wave',
        keyframes: [
            { bone: 'rightUpperArm', axis: 'z', target: 0.3, duration: 300 },
            { bone: 'rightLowerArm', axis: 'z', target: -0.8, duration: 200, delay: 100 },
            { bone: 'rightLowerArm', axis: 'z', target: -1.2, duration: 200, delay: 300 },
            { bone: 'rightLowerArm', axis: 'z', target: -0.8, duration: 200, delay: 500 },
        ],
        totalDuration: 800,
        returnDuration: 400,
    },
    shrug: {
        name: 'shrug',
        keyframes: [
            { bone: 'leftUpperArm', axis: 'z', target: -1.0, duration: 350 },
            { bone: 'rightUpperArm', axis: 'z', target: 1.0, duration: 350 },
            { bone: 'head', axis: 'x', target: -0.08, duration: 300 },
            { bone: 'head', axis: 'z', target: 0.1, duration: 300 },
        ],
        totalDuration: 600,
        returnDuration: 400,
    },
    tilt_head: {
        name: 'tilt_head',
        keyframes: [
            { bone: 'head', axis: 'z', target: 0.18, duration: 400 },
            { bone: 'head', axis: 'x', target: -0.05, duration: 300 },
        ],
        totalDuration: 500,
        returnDuration: 400,
    },
    bow: {
        name: 'bow',
        keyframes: [
            { bone: 'spine', axis: 'x', target: -0.2, duration: 500 },
            { bone: 'head', axis: 'x', target: -0.15, duration: 400, delay: 100 },
        ],
        totalDuration: 700,
        returnDuration: 500,
    },
    point: {
        name: 'point',
        keyframes: [
            { bone: 'rightUpperArm', axis: 'z', target: 0.2, duration: 300 },
            { bone: 'rightLowerArm', axis: 'z', target: -0.3, duration: 250, delay: 100 },
        ],
        totalDuration: 500,
        returnDuration: 350,
    },
    fist_pump: {
        name: 'fist_pump',
        keyframes: [
            { bone: 'rightUpperArm', axis: 'z', target: 0.5, duration: 250 },
            { bone: 'rightLowerArm', axis: 'z', target: -1.5, duration: 200, delay: 100 },
            { bone: 'rightUpperArm', axis: 'z', target: 0.3, duration: 200, delay: 300 },
            { bone: 'rightUpperArm', axis: 'z', target: 0.5, duration: 200, delay: 500 },
        ],
        totalDuration: 700,
        returnDuration: 350,
    },
    clap: {
        name: 'clap',
        keyframes: [
            { bone: 'leftUpperArm', axis: 'z', target: -0.8, duration: 200 },
            { bone: 'rightUpperArm', axis: 'z', target: 0.8, duration: 200 },
            { bone: 'leftUpperArm', axis: 'z', target: -1.0, duration: 150, delay: 200 },
            { bone: 'rightUpperArm', axis: 'z', target: 1.0, duration: 150, delay: 200 },
            { bone: 'leftUpperArm', axis: 'z', target: -0.8, duration: 150, delay: 350 },
            { bone: 'rightUpperArm', axis: 'z', target: 0.8, duration: 150, delay: 350 },
        ],
        totalDuration: 600,
        returnDuration: 350,
    },
};

// ── Rest pose (default bone rotations) ───────────────────────────

const REST_POSE: Record<string, Record<string, number>> = {
    leftUpperArm:  { x: 0, y: 0, z: -1.3 },
    rightUpperArm: { x: 0, y: 0, z: 1.3 },
    leftLowerArm:  { x: 0, y: 0, z: 0 },
    rightLowerArm: { x: 0, y: 0, z: 0 },
    head:          { x: 0, y: 0, z: 0 },
    spine:         { x: 0, y: 0, z: 0 },
};

// ── Easing ────────────────────────────────────────────────────────

function easeInOut(t: number): number {
    return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
}

// ── Component ─────────────────────────────────────────────────────

interface AvatarProps {
    isTalking: boolean;
    emotion: string;
    isThinking?: boolean;
    stateTag?: string;
    gesture?: string;
    gestureTick?: number;
    audioVolume?: number;
}

export default function AvatarView({
    isTalking, emotion, isThinking = false, stateTag = "", gesture = "", gestureTick = 0, audioVolume,
}: AvatarProps) {
    const containerRef = useRef<HTMLDivElement>(null);
    const vrmRef = useRef<VRM | null>(null);
    const clockRef = useRef(new THREE.Clock());
    const emotionRef = useRef<string>(emotion);
    const stateRef = useRef<string>(stateTag);
    const thinkingRef = useRef<boolean>(isThinking);
    const audioVolumeRef = useRef<number>(0);
    const activeGestureRef = useRef<ActiveGesture | null>(null);
    const gestureQueueRef = useRef<string>("");
    const noiseRef = useRef({
        currentFreq: 1.0,
        targetFreq: 1.0,
        nextUpdateAt: 0,
        phase: 0,
        seed: 42.1337,
    });

    // ── Gesture trigger ──────────────────────────────────────────
    useEffect(() => {
        if (gesture) {
            gestureQueueRef.current = gesture;
        }
    }, [gesture, gestureTick]);

    useEffect(() => {
        emotionRef.current = emotion;
    }, [emotion]);

    useEffect(() => {
        stateRef.current = stateTag;
    }, [stateTag]);

    useEffect(() => {
        thinkingRef.current = isThinking;
    }, [isThinking]);

    useEffect(() => {
        audioVolumeRef.current = audioVolume ?? 0;
    }, [audioVolume]);

    // ── Main scene setup + animation loop ────────────────────────
    useEffect(() => {
        if (!containerRef.current) return;

        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x0f0f12);

        const camera = new THREE.PerspectiveCamera(30, containerRef.current.clientWidth / containerRef.current.clientHeight, 0.1, 20.0);
        camera.position.set(0.0, 1.3, 1.4);

        const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
        renderer.setSize(containerRef.current.clientWidth, containerRef.current.clientHeight);
        renderer.setPixelRatio(window.devicePixelRatio);
        containerRef.current.appendChild(renderer.domElement);

        const light = new THREE.DirectionalLight(0xffffff);
        light.position.set(1.0, 1.0, 1.0).normalize();
        scene.add(light);
        const ambient = new THREE.AmbientLight(0x404040);
        scene.add(ambient);

        const loader = new GLTFLoader();
        loader.register((parser) => new VRMLoaderPlugin(parser));

        loader.load(
            '/avatar.vrm',
            (gltf) => {
                const vrm = gltf.userData.vrm;
                VRMUtils.removeUnnecessaryVertices(gltf.scene);
                VRMUtils.combineSkeletons(gltf.scene);
                vrm.scene.rotation.y = 0;
                scene.add(vrm.scene);
                vrmRef.current = vrm;
            },
            () => { /* progress silenced */ },
            (error) => console.error("VRM Load Failed:", error)
        );

        const getMotionParams = () => {
            const state = (stateRef.current || "").toLowerCase();
            const emotionTag = (emotionRef.current || "").toLowerCase();
            const tag = state || emotionTag;
            const pondering = Boolean(thinkingRef.current) || tag === "pondering";

            let amplitude = 0.0045;
            let baseFrequency = 0.55;
            let jitter = 0.18;
            let damping = 0.08;

            if (tag === "consent") {
                amplitude = 0.0030; damping = 0.14; jitter = 0.08;
            }
            if (tag === "dissonance") {
                amplitude = 0.0060; baseFrequency = 0.8; jitter = 0.35; damping = 0.05;
            }
            if (pondering) {
                baseFrequency = 0.5; jitter = 0.12;
            }

            return { amplitude, baseFrequency, jitter, damping, pondering };
        };

        // ── Helper: get bone rest rotation for an axis ───────────
        const getRestValue = (boneName: string, axis: string): number => {
            return REST_POSE[boneName]?.[axis] ?? 0;
        };

        // ── Helper: get current bone rotation ────────────────────
        const getBoneRotation = (humanoid: any, boneName: string, axis: string): number => {
            const bone = humanoid.getNormalizedBoneNode(boneName);
            if (!bone) return getRestValue(boneName, axis);
            return (bone.rotation as any)[axis] as number;
        };

        // ── Helper: set bone rotation ────────────────────────────
        const setBoneRotation = (humanoid: any, boneName: string, axis: string, value: number) => {
            const bone = humanoid.getNormalizedBoneNode(boneName);
            if (bone) {
                (bone.rotation as any)[axis] = value;
            }
        };

        // ── Gesture update per frame ─────────────────────────────
        const updateGesture = (humanoid: any, now: number) => {
            // Check for new gesture in queue
            if (gestureQueueRef.current && !activeGestureRef.current) {
                const presetName = gestureQueueRef.current.toLowerCase();
                gestureQueueRef.current = "";
                const preset = GESTURE_PRESETS[presetName];
                if (preset) {
                    const boneStates = new Map<string, { axis: string; from: number; target: number }>();
                    for (const kf of preset.keyframes) {
                        const key = `${kf.bone}_${kf.axis}`;
                        if (!boneStates.has(key)) {
                            boneStates.set(key, {
                                axis: kf.axis,
                                from: getBoneRotation(humanoid, kf.bone, kf.axis),
                                target: kf.target,
                            });
                        }
                    }
                    activeGestureRef.current = {
                        preset,
                        startTime: now,
                        phase: 'play',
                        boneStates,
                    };
                }
            }

            const ag = activeGestureRef.current;
            if (!ag) return;

            const elapsed = (now - ag.startTime) * 1000; // ms

            if (ag.phase === 'play') {
                // Apply each keyframe
                for (const kf of ag.preset.keyframes) {
                    const delay = kf.delay ?? 0;
                    const kfStart = delay;
                    const kfEnd = delay + kf.duration;

                    const key = `${kf.bone}_${kf.axis}`;
                    const state = ag.boneStates.get(key);
                    if (!state) continue;

                    if (elapsed < kfStart) {
                        // Not started yet
                    } else if (elapsed >= kfEnd) {
                        setBoneRotation(humanoid, kf.bone, kf.axis, kf.target);
                        // Update last known target for this bone
                        state.target = kf.target;
                    } else {
                        const progress = easeInOut((elapsed - kfStart) / kf.duration);
                        const value = state.from + (kf.target - state.from) * progress;
                        setBoneRotation(humanoid, kf.bone, kf.axis, value);
                    }
                }

                // Transition to return phase
                if (elapsed >= ag.preset.totalDuration) {
                    ag.phase = 'return';
                    ag.startTime = now;
                    // Capture current bone positions as "from" for return
                    for (const kf of ag.preset.keyframes) {
                        const key = `${kf.bone}_${kf.axis}`;
                        const state = ag.boneStates.get(key);
                        if (state) {
                            state.from = getBoneRotation(humanoid, kf.bone, kf.axis);
                            state.target = getRestValue(kf.bone, kf.axis);
                        }
                    }
                }
            } else if (ag.phase === 'return') {
                const returnElapsed = (now - ag.startTime) * 1000;
                const returnDur = ag.preset.returnDuration;

                if (returnElapsed >= returnDur) {
                    // Done - restore rest pose for affected bones
                    for (const kf of ag.preset.keyframes) {
                        setBoneRotation(humanoid, kf.bone, kf.axis, getRestValue(kf.bone, kf.axis));
                    }
                    activeGestureRef.current = null;
                } else {
                    const progress = easeInOut(returnElapsed / returnDur);
                    const seen = new Set<string>();
                    for (const kf of ag.preset.keyframes) {
                        const key = `${kf.bone}_${kf.axis}`;
                        if (seen.has(key)) continue;
                        seen.add(key);
                        const state = ag.boneStates.get(key);
                        if (state) {
                            const value = state.from + (state.target - state.from) * progress;
                            setBoneRotation(humanoid, kf.bone, kf.axis, value);
                        }
                    }
                }
            }
        };

        // ── Set of bones currently controlled by gesture ─────────
        const isGestureControlling = (boneName: string, axis: string): boolean => {
            const ag = activeGestureRef.current;
            if (!ag) return false;
            return ag.boneStates.has(`${boneName}_${axis}`);
        };

        // ── Main animation loop ──────────────────────────────────
        const animate = () => {
            requestAnimationFrame(animate);
            const delta = clockRef.current.getDelta();
            const vrm = vrmRef.current;

            if (vrm) {
                const humanoid = vrm.humanoid;

                // Apply rest pose for non-gesture-controlled bones
                if (humanoid) {
                    if (!isGestureControlling('leftUpperArm', 'z')) {
                        const leftArm = humanoid.getNormalizedBoneNode('leftUpperArm');
                        if (leftArm) leftArm.rotation.z = -1.3;
                    }
                    if (!isGestureControlling('rightUpperArm', 'z')) {
                        const rightArm = humanoid.getNormalizedBoneNode('rightUpperArm');
                        if (rightArm) rightArm.rotation.z = 1.3;
                    }
                }

                vrm.update(delta);

                const t = clockRef.current.elapsedTime;
                const { amplitude, baseFrequency, jitter, damping, pondering } = getMotionParams();

                // Noise-based body sway
                if (t >= noiseRef.current.nextUpdateAt) {
                    const pseudo = Math.sin(t * 1.731 + noiseRef.current.seed) * 0.5 + 0.5;
                    noiseRef.current.targetFreq = Math.max(0.4, baseFrequency + (pseudo - 0.5) * jitter * 2.0);
                    const interval = 1.5 + (pseudo * 1.5);
                    noiseRef.current.nextUpdateAt = t + interval;
                }

                noiseRef.current.currentFreq += (noiseRef.current.targetFreq - noiseRef.current.currentFreq) * damping;
                noiseRef.current.phase += noiseRef.current.currentFreq * delta * Math.PI * 2.0;

                let amp = amplitude;
                if (pondering) {
                    const slowT = t * (Math.PI * 2.0) * 0.2;
                    const wave = 0.5 + 0.5 * Math.sin(slowT);
                    amp = amplitude * (0.3 + 0.7 * wave);
                }

                vrm.scene.rotation.z = Math.sin(noiseRef.current.phase) * amp;

                // Head motion (thinking) - only if gesture not controlling head
                if (humanoid) {
                    const headControlled = isGestureControlling('head', 'x') ||
                                           isGestureControlling('head', 'y') ||
                                           isGestureControlling('head', 'z');
                    if (!headControlled) {
                        const head = humanoid.getNormalizedBoneNode('head');
                        if (head) {
                            if (thinkingRef.current) {
                                head.rotation.y = Math.sin(t * 0.7) * 0.15;
                                head.rotation.x = -0.06 + Math.sin(t * 0.9) * 0.03;
                            } else {
                                head.rotation.x = 0;
                                head.rotation.y = 0;
                            }
                        }
                    }

                    // Gesture animation update
                    updateGesture(humanoid, t);
                }

                // Auto blink
                if (Math.random() < 0.005) {
                    vrm.expressionManager?.setValue('blink', 1.0);
                    setTimeout(() => vrm.expressionManager?.setValue('blink', 0.0), 100);
                }
            }

            renderer.render(scene, camera);
        };
        animate();

        const handleResize = () => {
            if (!containerRef.current) return;
            camera.aspect = containerRef.current.clientWidth / containerRef.current.clientHeight;
            camera.updateProjectionMatrix();
            renderer.setSize(containerRef.current.clientWidth, containerRef.current.clientHeight);
        };
        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            renderer.dispose();
            if (containerRef.current?.contains(renderer.domElement)) {
                containerRef.current.removeChild(renderer.domElement);
            }
        };
    }, []);

    // ── Expression control ───────────────────────────────────────
    useEffect(() => {
        const vrm = vrmRef.current;
        if (!vrm || !vrm.expressionManager) return;

        const list = vrm.expressionManager.expressions;
        list.forEach(e => {
            if (e.expressionName !== 'blink' && e.expressionName !== 'aa') {
                vrm.expressionManager?.setValue(e.expressionName, 0);
            }
        });

        let targetExpression = 'neutral';
        if (emotion === 'happy') targetExpression = 'happy';
        if (emotion === 'sad') targetExpression = 'sad';
        if (emotion === 'angry') targetExpression = 'angry';
        if (emotion === 'surprised') targetExpression = 'surprised';
        if (emotion === 'consent') targetExpression = 'neutral';
        if (emotion === 'dissonance') targetExpression = 'neutral';
        if (emotion === 'pondering') targetExpression = 'neutral';

        if (vrm.expressionManager.getExpression(targetExpression)) {
            vrm.expressionManager.setValue(targetExpression, 1.0);
        } else {
            if (emotion === 'happy') vrm.expressionManager.setValue('joy', 1.0);
            else vrm.expressionManager.setValue('neutral', 1.0);
        }
    }, [emotion]);

    // ── Lip sync ─────────────────────────────────────────────────
    useEffect(() => {
        let frameId: number;
        let prevSmoothed = 0;
        const lipLoop = () => {
            const vrm = vrmRef.current;
            if (vrm && vrm.expressionManager) {
                const vol = audioVolumeRef.current;
                if (vol > 0.01) {
                    // Audio-driven lip sync
                    prevSmoothed += (vol - prevSmoothed) * 0.3;
                    vrm.expressionManager.setValue('aa', Math.min(prevSmoothed * 1.5, 1.0));
                } else if (isTalking) {
                    // Fallback: sin wave
                    prevSmoothed = 0;
                    const v = 0.2 + 0.4 * Math.sin(Date.now() / 60);
                    vrm.expressionManager.setValue('aa', v);
                } else {
                    prevSmoothed = 0;
                    vrm.expressionManager.setValue('aa', 0);
                }
            }
            frameId = requestAnimationFrame(lipLoop);
        };
        lipLoop();
        return () => cancelAnimationFrame(frameId);
    }, [isTalking]);

    return (
        <div className="w-full h-full glass-panel relative overflow-hidden rounded-2xl">
            <div ref={containerRef} className="w-full h-full" />
        </div>
    );
}
