"use client";

import React, { useEffect, useRef, useCallback } from "react";

// ── Types ────────────────────────────────────────────────────────

interface AvatarProps {
  isTalking: boolean;
  emotion: string;
  isThinking?: boolean;
  stateTag?: string;
  gesture?: string;
  gestureTick?: number;
  audioVolume?: number;
}

// ── Emotion → Live2D parameter presets ───────────────────────────

interface EmotionParams {
  ParamEyeLSmile: number;
  ParamEyeRSmile: number;
  ParamMouthForm: number;
  ParamBrowLY: number;
  ParamBrowRY: number;
  ParamBrowLAngle: number;
  ParamBrowRAngle: number;
  ParamCheek: number;
}

const EMOTION_PRESETS: Record<string, Partial<EmotionParams>> = {
  happy: {
    ParamEyeLSmile: 1,
    ParamEyeRSmile: 1,
    ParamMouthForm: 1,
    ParamBrowLY: 0.3,
    ParamBrowRY: 0.3,
    ParamCheek: 0.6,
  },
  sad: {
    ParamEyeLSmile: 0,
    ParamEyeRSmile: 0,
    ParamMouthForm: -0.6,
    ParamBrowLY: -0.5,
    ParamBrowRY: -0.5,
    ParamBrowLAngle: -0.5,
    ParamBrowRAngle: -0.5,
  },
  angry: {
    ParamEyeLSmile: 0,
    ParamEyeRSmile: 0,
    ParamMouthForm: -0.3,
    ParamBrowLY: 0.3,
    ParamBrowRY: 0.3,
    ParamBrowLAngle: 0.8,
    ParamBrowRAngle: 0.8,
  },
  surprised: {
    ParamEyeLSmile: 0,
    ParamEyeRSmile: 0,
    ParamMouthForm: 0.2,
    ParamBrowLY: 0.8,
    ParamBrowRY: 0.8,
    ParamBrowLAngle: -0.3,
    ParamBrowRAngle: -0.3,
  },
  relaxed: {
    ParamEyeLSmile: 0.5,
    ParamEyeRSmile: 0.5,
    ParamMouthForm: 0.3,
    ParamBrowLY: -0.1,
    ParamBrowRY: -0.1,
  },
  shy: {
    ParamEyeLSmile: 0.7,
    ParamEyeRSmile: 0.7,
    ParamMouthForm: 0.2,
    ParamCheek: 1,
    ParamBrowLY: -0.2,
    ParamBrowRY: -0.2,
  },
  neutral: {},
  consent: {
    ParamEyeLSmile: 0.3,
    ParamEyeRSmile: 0.3,
    ParamMouthForm: 0.4,
  },
  dissonance: {
    ParamMouthForm: -0.4,
    ParamBrowLAngle: 0.5,
    ParamBrowRAngle: 0.5,
    ParamBrowLY: -0.2,
    ParamBrowRY: -0.2,
  },
  pondering: {
    ParamEyeLSmile: 0,
    ParamEyeRSmile: 0,
    ParamBrowLY: 0.2,
    ParamBrowRY: -0.1,
  },
};

const DEFAULT_EMOTION_PARAMS: EmotionParams = {
  ParamEyeLSmile: 0,
  ParamEyeRSmile: 0,
  ParamMouthForm: 0,
  ParamBrowLY: 0,
  ParamBrowRY: 0,
  ParamBrowLAngle: 0,
  ParamBrowRAngle: 0,
  ParamCheek: 0,
};

// ── Gesture definitions (parameter-based animations) ─────────────

interface GestureKeyframe {
  param: string;
  target: number;
  duration: number;
  delay?: number;
}

interface GestureDef {
  keyframes: GestureKeyframe[];
  totalDuration: number;
}

const GESTURE_DEFS: Record<string, GestureDef> = {
  nod: {
    keyframes: [
      { param: "ParamAngleX", target: -15, duration: 200 },
      { param: "ParamAngleX", target: 5, duration: 200, delay: 200 },
      { param: "ParamAngleX", target: 0, duration: 150, delay: 400 },
    ],
    totalDuration: 550,
  },
  tilt_head: {
    keyframes: [
      { param: "ParamAngleZ", target: 15, duration: 300 },
      { param: "ParamAngleZ", target: 0, duration: 400, delay: 800 },
    ],
    totalDuration: 1200,
  },
  bow: {
    keyframes: [
      { param: "ParamAngleX", target: -20, duration: 400 },
      { param: "ParamBodyAngleX", target: -5, duration: 400 },
      { param: "ParamAngleX", target: 0, duration: 500, delay: 700 },
      { param: "ParamBodyAngleX", target: 0, duration: 500, delay: 700 },
    ],
    totalDuration: 1200,
  },
  wave: {
    keyframes: [
      { param: "ParamArmRA", target: 1, duration: 300 },
      { param: "ParamHandR", target: 1, duration: 200, delay: 200 },
      { param: "ParamHandR", target: -1, duration: 200, delay: 400 },
      { param: "ParamHandR", target: 1, duration: 200, delay: 600 },
      { param: "ParamHandR", target: 0, duration: 200, delay: 800 },
      { param: "ParamArmRA", target: 0, duration: 300, delay: 900 },
    ],
    totalDuration: 1200,
  },
  shrug: {
    keyframes: [
      { param: "ParamShoulder", target: 1, duration: 300 },
      { param: "ParamAngleZ", target: 5, duration: 200 },
      { param: "ParamShoulder", target: 0, duration: 400, delay: 600 },
      { param: "ParamAngleZ", target: 0, duration: 300, delay: 600 },
    ],
    totalDuration: 1000,
  },
  point: {
    keyframes: [
      { param: "ParamArmRA", target: 1, duration: 300 },
      { param: "ParamHandR", target: 1, duration: 200, delay: 200 },
      { param: "ParamArmRA", target: 0, duration: 400, delay: 800 },
      { param: "ParamHandR", target: 0, duration: 300, delay: 800 },
    ],
    totalDuration: 1200,
  },
  fist_pump: {
    keyframes: [
      { param: "ParamArmRA", target: 1, duration: 250 },
      { param: "ParamArmRA", target: 0.5, duration: 150, delay: 250 },
      { param: "ParamArmRA", target: 1, duration: 150, delay: 400 },
      { param: "ParamArmRA", target: 0, duration: 300, delay: 700 },
    ],
    totalDuration: 1000,
  },
  clap: {
    keyframes: [
      { param: "ParamArmLA", target: 0.8, duration: 200 },
      { param: "ParamArmRA", target: 0.8, duration: 200 },
      { param: "ParamArmLA", target: 0.3, duration: 100, delay: 200 },
      { param: "ParamArmRA", target: 0.3, duration: 100, delay: 200 },
      { param: "ParamArmLA", target: 0.8, duration: 100, delay: 300 },
      { param: "ParamArmRA", target: 0.8, duration: 100, delay: 300 },
      { param: "ParamArmLA", target: 0.3, duration: 100, delay: 400 },
      { param: "ParamArmRA", target: 0.3, duration: 100, delay: 400 },
      { param: "ParamArmLA", target: 0, duration: 300, delay: 500 },
      { param: "ParamArmRA", target: 0, duration: 300, delay: 500 },
    ],
    totalDuration: 800,
  },
};

// ── Easing ───────────────────────────────────────────────────────

function easeInOut(t: number): number {
  return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

// ── Component ────────────────────────────────────────────────────

export default function Live2DView({
  isTalking,
  emotion,
  isThinking = false,
  stateTag = "",
  gesture = "",
  gestureTick = 0,
  audioVolume,
}: AvatarProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const appRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const modelRef = useRef<any>(null);
  const emotionRef = useRef(emotion);
  const isTalkingRef = useRef(isTalking);
  const audioVolumeRef = useRef(0);
  const isThinkingRef = useRef(isThinking);
  const stateRef = useRef(stateTag);
  const animFrameRef = useRef(0);
  const gestureQueueRef = useRef("");
  const gestureActiveRef = useRef(false);
  const initRef = useRef(false);

  // Current & target emotion params for smooth interpolation
  const currentParamsRef = useRef<EmotionParams>({ ...DEFAULT_EMOTION_PARAMS });
  const targetParamsRef = useRef<EmotionParams>({ ...DEFAULT_EMOTION_PARAMS });

  // Sync refs
  useEffect(() => { emotionRef.current = emotion; }, [emotion]);
  useEffect(() => { isTalkingRef.current = isTalking; }, [isTalking]);
  useEffect(() => { isThinkingRef.current = isThinking; }, [isThinking]);
  useEffect(() => { stateRef.current = stateTag; }, [stateTag]);
  useEffect(() => {
    if (audioVolume !== undefined) audioVolumeRef.current = audioVolume;
  }, [audioVolume]);

  // Update target emotion params when emotion or stateTag changes
  useEffect(() => {
    const key = stateTag?.toLowerCase() || emotion?.toLowerCase() || "neutral";
    const preset = EMOTION_PRESETS[key] || EMOTION_PRESETS.neutral;
    targetParamsRef.current = { ...DEFAULT_EMOTION_PARAMS, ...preset };
  }, [emotion, stateTag]);

  // Queue gesture
  useEffect(() => {
    if (gesture) gestureQueueRef.current = gesture;
  }, [gesture, gestureTick]);

  // ── Play a gesture animation via parameter tweening ──
  const playGesture = useCallback((gestureName: string) => {
    const model = modelRef.current;
    const def = GESTURE_DEFS[gestureName];
    if (!model || !def) return;

    gestureActiveRef.current = true;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const coreModel = (model.internalModel as any)?.coreModel as any;
    if (!coreModel) return;

    const startTime = performance.now();
    const kfStates = def.keyframes.map((kf) => ({
      ...kf,
      started: false,
      done: false,
      from: 0 as number,
    }));

    const tick = () => {
      const elapsed = performance.now() - startTime;
      let allDone = true;

      for (const kf of kfStates) {
        const kfStart = kf.delay || 0;
        if (elapsed < kfStart) {
          allDone = false;
          continue;
        }
        if (!kf.started) {
          kf.started = true;
          try {
            kf.from = coreModel.getParameterValueById(kf.param) ?? 0;
          } catch {
            kf.from = 0;
          }
        }
        const kfElapsed = elapsed - kfStart;
        if (kfElapsed >= kf.duration) {
          try { coreModel.setParameterValueById(kf.param, kf.target); } catch { /* ignore */ }
          kf.done = true;
        } else {
          allDone = false;
          const t = easeInOut(kfElapsed / kf.duration);
          const val = lerp(kf.from, kf.target, t);
          try { coreModel.setParameterValueById(kf.param, val); } catch { /* ignore */ }
        }
      }

      if (!allDone) {
        requestAnimationFrame(tick);
      } else {
        gestureActiveRef.current = false;
      }
    };
    requestAnimationFrame(tick);
  }, []);

  // ── Main init & animation loop ─────────────────────────────────
  useEffect(() => {
    if (initRef.current) return;
    initRef.current = true;

    const container = containerRef.current;
    if (!container) return;

    let destroyed = false;

    const init = async () => {
      // Dynamic imports to avoid SSR issues
      const PIXI = await import("pixi.js");
      const { Live2DModel } = await import("@naari3/pixi-live2d-display");

      if (destroyed) return;

      const app = new PIXI.Application();
      await app.init({
        resizeTo: container,
        backgroundAlpha: 0,
        antialias: true,
      });

      if (destroyed) { app.destroy(); return; }

      container.appendChild(app.canvas);
      appRef.current = app;

      // Load model
      const model = await Live2DModel.from(
        "/live2d/hiyori/Hiyori.model3.json",
        { autoInteract: false }
      );

      if (destroyed) { app.destroy(); return; }

      modelRef.current = model;
      app.stage.addChild(model);

      // Fit model to container
      const fitModel = () => {
        const w = container.clientWidth;
        const h = container.clientHeight;
        const scale = Math.min(w / model.width, h / model.height) * 0.8;
        model.scale.set(scale);
        model.x = w / 2;
        model.y = h * 0.9;
        model.anchor.set(0.5, 1);
      };
      fitModel();

      const resizeObserver = new ResizeObserver(fitModel);
      resizeObserver.observe(container);

      // Start idle motion
      try {
        const { MotionPriority } = await import("@naari3/pixi-live2d-display");
        model.motion("Idle", 0, MotionPriority.IDLE);
      } catch { /* no idle motion available */ }

      // ── Animation loop ──
      let lastTime = performance.now();

      const animate = () => {
        if (destroyed) return;
        const now = performance.now();
        const dt = (now - lastTime) / 1000;
        lastTime = now;

        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const coreModel = (model.internalModel as any)?.coreModel as any;
        if (!coreModel) {
          animFrameRef.current = requestAnimationFrame(animate);
          return;
        }

        // 1. Lip sync
        if (isTalkingRef.current) {
          const vol = audioVolumeRef.current;
          const mouthOpen = Math.min(1, vol * 1.5);
          try { coreModel.setParameterValueById("ParamMouthOpenY", mouthOpen); } catch { /* ignore */ }
        }

        // 2. Smooth emotion interpolation (blend toward target)
        const blendSpeed = 3.0 * dt;
        const cur = currentParamsRef.current;
        const tgt = targetParamsRef.current;
        for (const key of Object.keys(DEFAULT_EMOTION_PARAMS) as (keyof EmotionParams)[]) {
          cur[key] = lerp(cur[key], tgt[key], Math.min(1, blendSpeed));
          try { coreModel.setParameterValueById(key, cur[key]); } catch { /* ignore */ }
        }

        // 3. Thinking: subtle eye/head movement
        if (isThinkingRef.current) {
          const t = now / 1000;
          try {
            coreModel.setParameterValueById("ParamEyeBallX", Math.sin(t * 1.5) * 0.3);
            coreModel.setParameterValueById("ParamEyeBallY", Math.cos(t * 1.1) * 0.15);
            coreModel.setParameterValueById("ParamAngleZ", Math.sin(t * 0.8) * 3);
          } catch { /* ignore */ }
        }

        // 4. Process gesture queue
        if (gestureQueueRef.current && !gestureActiveRef.current) {
          const g = gestureQueueRef.current;
          gestureQueueRef.current = "";
          playGesture(g);
        }

        animFrameRef.current = requestAnimationFrame(animate);
      };

      animFrameRef.current = requestAnimationFrame(animate);
    };

    init().catch(console.error);

    return () => {
      destroyed = true;
      cancelAnimationFrame(animFrameRef.current);
      if (appRef.current) {
        appRef.current.destroy(true);
        appRef.current = null;
      }
      modelRef.current = null;
    };
  }, [playGesture]);

  return (
    <div
      ref={containerRef}
      className="w-full h-full relative"
      style={{ minHeight: 200 }}
    />
  );
}
