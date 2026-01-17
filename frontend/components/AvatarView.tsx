
"use client";
import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils, VRM } from '@pixiv/three-vrm';

interface AvatarProps {
    isTalking: boolean;
    emotion: string;
}

export default function AvatarView({ isTalking, emotion }: AvatarProps) {
    const containerRef = useRef<HTMLDivElement>(null);
    // Using Ref for VRM to ensure the animation loop always has the latest instance
    const vrmRef = useRef<VRM | null>(null);
    const clockRef = useRef(new THREE.Clock());

    useEffect(() => {
        if (!containerRef.current) return;

        // Scene Setup
        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x0f0f12);

        // Camera
        const camera = new THREE.PerspectiveCamera(30, containerRef.current.clientWidth / containerRef.current.clientHeight, 0.1, 20.0);
        camera.position.set(0.0, 1.3, 1.4);

        // Renderer
        const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
        renderer.setSize(containerRef.current.clientWidth, containerRef.current.clientHeight);
        renderer.setPixelRatio(window.devicePixelRatio);
        containerRef.current.appendChild(renderer.domElement);

        // Light
        const light = new THREE.DirectionalLight(0xffffff);
        light.position.set(1.0, 1.0, 1.0).normalize();
        scene.add(light);
        const ambient = new THREE.AmbientLight(0x404040);
        scene.add(ambient);

        // Loader
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
                vrmRef.current = vrm; // Set to Ref
                console.log("VRM Charged and Ready");
            },
            (progress) => console.log('Loading VRM...', 100.0 * (progress.loaded / progress.total), '%'),
            (error) => console.error("VRM Load Failed:", error)
        );

        // Animation Loop
        const animate = () => {
            requestAnimationFrame(animate);
            const delta = clockRef.current.getDelta();
            const vrm = vrmRef.current;

            if (vrm) {
                // --- 1. Override Pose (Every frame to beat constraints) ---
                const humanoid = vrm.humanoid;
                if (humanoid) {
                    const leftArm = humanoid.getNormalizedBoneNode('leftUpperArm');
                    const rightArm = humanoid.getNormalizedBoneNode('rightUpperArm');
                    if (leftArm) leftArm.rotation.z = -1.3; // Lower arm
                    if (rightArm) rightArm.rotation.z = 1.3;
                }

                // --- 2. Update VRM ---
                vrm.update(delta);

                // --- 3. Idle Motion (Breathing) ---
                const s = Math.sin(clockRef.current.elapsedTime);
                vrm.scene.rotation.z = s * 0.005;

                // Blink Logic
                if (Math.random() < 0.005) {
                    vrm.expressionManager?.setValue('blink', 1.0);
                    setTimeout(() => vrm.expressionManager?.setValue('blink', 0.0), 100);
                }
            }

            renderer.render(scene, camera);
        };
        animate();

        // Resize Handler
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

    // --- Sync Emotion & Talking State (Runs on props change) ---
    useEffect(() => {
        const vrm = vrmRef.current;
        if (!vrm || !vrm.expressionManager) return;

        // Reset Expressions (Keep current one)
        const list = vrm.expressionManager.expressions;
        list.forEach(e => {
            if (e.expressionName !== 'blink' && e.expressionName !== 'aa') {
                vrm.expressionManager?.setValue(e.expressionName, 0);
            }
        });

        // Set Emotion
        let targetExpression = 'neutral';
        if (emotion === 'happy') targetExpression = 'happy';
        if (emotion === 'sad') targetExpression = 'sad';
        if (emotion === 'angry') targetExpression = 'angry';
        if (emotion === 'surprised') targetExpression = 'surprised';

        if (vrm.expressionManager.getExpression(targetExpression)) {
            vrm.expressionManager.setValue(targetExpression, 1.0);
        } else {
            // Fallback to joy if happy missing
            if (emotion === 'happy') vrm.expressionManager.setValue('joy', 1.0);
            else vrm.expressionManager.setValue('neutral', 1.0);
        }
    }, [emotion]);

    // Lip Sync Animation Loop (Independent)
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
