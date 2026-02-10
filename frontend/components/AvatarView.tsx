"use client";
import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils, VRM } from '@pixiv/three-vrm';

interface AvatarProps {
    isTalking: boolean;
    emotion: string;
    isThinking?: boolean;
    stateTag?: string;
}

export default function AvatarView({ isTalking, emotion, isThinking = false, stateTag = "" }: AvatarProps) {
    const containerRef = useRef<HTMLDivElement>(null);
    const vrmRef = useRef<VRM | null>(null);
    const clockRef = useRef(new THREE.Clock());
    const emotionRef = useRef<string>(emotion);
    const stateRef = useRef<string>(stateTag);
    const thinkingRef = useRef<boolean>(isThinking);
    const noiseRef = useRef({
        currentFreq: 1.0,
        targetFreq: 1.0,
        nextUpdateAt: 0,
        phase: 0,
        seed: 42.1337,
    });

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
            (progress) => console.log('Loading VRM...', 100.0 * (progress.loaded / progress.total), '%'),
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
                amplitude = 0.0030;
                damping = 0.14;
                jitter = 0.08;
            }

            if (tag === "dissonance") {
                amplitude = 0.0060;
                baseFrequency = 0.8;
                jitter = 0.35;
                damping = 0.05;
            }

            if (pondering) {
                baseFrequency = 0.5;
                jitter = 0.12;
            }

            return { amplitude, baseFrequency, jitter, damping, pondering };
        };

        const animate = () => {
            requestAnimationFrame(animate);
            const delta = clockRef.current.getDelta();
            const vrm = vrmRef.current;

            if (vrm) {
                const humanoid = vrm.humanoid;
                if (humanoid) {
                    const leftArm = humanoid.getNormalizedBoneNode('leftUpperArm');
                    const rightArm = humanoid.getNormalizedBoneNode('rightUpperArm');
                    if (leftArm) leftArm.rotation.z = -1.3;
                    if (rightArm) rightArm.rotation.z = 1.3;
                }

                vrm.update(delta);

                const t = clockRef.current.elapsedTime;
                const { amplitude, baseFrequency, jitter, damping, pondering } = getMotionParams();

                if (t >= noiseRef.current.nextUpdateAt) {
                    const pseudo = Math.sin(t * 1.731 + noiseRef.current.seed) * 0.5 + 0.5;
                    noiseRef.current.targetFreq = Math.max(0.4, baseFrequency + (pseudo - 0.5) * jitter * 2.0);
                    const interval = 1.5 + (pseudo * 1.5); // 1.5〜3.0秒
                    noiseRef.current.nextUpdateAt = t + interval;
                }

                noiseRef.current.currentFreq += (noiseRef.current.targetFreq - noiseRef.current.currentFreq) * damping;
                noiseRef.current.phase += noiseRef.current.currentFreq * delta * Math.PI * 2.0;

                let amp = amplitude;
                if (pondering) {
                    const slowT = t * (Math.PI * 2.0) * 0.2; // 0.2Hz
                    const wave = 0.5 + 0.5 * Math.sin(slowT);
                    amp = amplitude * (0.3 + 0.7 * wave);
                }

                vrm.scene.rotation.z = Math.sin(noiseRef.current.phase) * amp;

                if (humanoid) {
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

    useEffect(() => {
        let frameId: number;
        const lipLoop = () => {
            const vrm = vrmRef.current;
            if (vrm && vrm.expressionManager) {
                if (isTalking) {
                    const v = 0.2 + 0.4 * Math.sin(Date.now() / 60);
                    vrm.expressionManager.setValue('aa', v);
                } else {
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
