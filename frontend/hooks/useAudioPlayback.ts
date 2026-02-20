/**
 * Custom hook for TTS audio playback with lip-sync volume analysis.
 * Extracted from ChatInterface.tsx.
 */
import { useRef } from 'react';
import { quantizeVolume, shouldEmitVolume } from './audioPlaybackUtils';

export interface UseAudioPlaybackOptions {
    onStateChange: (isTalking: boolean, emotion: string, isThinking?: boolean) => void;
    onVolumeChange?: (volume: number) => void;
    currentEmotionRef: React.MutableRefObject<string>;
    isThinkingRef: React.MutableRefObject<boolean>;
    micVadRef: React.MutableRefObject<any>;
}

export function useAudioPlayback({
    onStateChange,
    onVolumeChange,
    currentEmotionRef,
    isThinkingRef,
    micVadRef,
}: UseAudioPlaybackOptions) {
    const audioQueueRef = useRef<string[]>([]);
    const isPlayingRef = useRef(false);
    const audioRef = useRef<HTMLAudioElement | null>(null);
    const audioCtxRef = useRef<AudioContext | null>(null);
    const volumeLoopRef = useRef<number>(0);
    const lastVolumeEmitMsRef = useRef<number>(0);
    const lastVolumeSentRef = useRef<number>(0);

    const emitVolume = (value: number, force = false) => {
        const now = Date.now();
        const quantized = quantizeVolume(value);
        if (!shouldEmitVolume(now, lastVolumeEmitMsRef.current, quantized, lastVolumeSentRef.current, force)) {
            return;
        }
        onVolumeChange?.(quantized);
        lastVolumeEmitMsRef.current = now;
        lastVolumeSentRef.current = quantized;
    };

    const resumeVadAfterPlayback = () => {
        if (audioQueueRef.current.length === 0) {
            micVadRef.current?.start().catch(() => {});
        }
    };

    const interruptAudioPlayback = () => {
        const audio = audioRef.current;
        if (audio) {
            try {
                audio.pause();
                audio.currentTime = 0;
            } catch {}
        }
        audioQueueRef.current = [];
        isPlayingRef.current = false;
        onStateChange(false, currentEmotionRef.current, isThinkingRef.current);
        micVadRef.current?.start().catch(() => {});
    };

    const processAudioQueue = async () => {
        if (isPlayingRef.current || audioQueueRef.current.length === 0) return;

        isPlayingRef.current = true;
        const audioUrl = audioQueueRef.current.shift();
        if (!audioUrl) {
            isPlayingRef.current = false;
            onStateChange(false, "neutral", isThinkingRef.current);
            emitVolume(0, true);
            resumeVadAfterPlayback();
            return;
        }

        // Pause VAD during TTS playback (echo loop prevention)
        micVadRef.current?.pause().catch(() => {});

        onStateChange(true, "happy", isThinkingRef.current);

        const audio = new Audio(audioUrl);
        audio.crossOrigin = "anonymous";
        audioRef.current = audio;

        // Audio-driven lip sync via AnalyserNode
        let analyser: AnalyserNode | null = null;
        try {
            if (!audioCtxRef.current) {
                audioCtxRef.current = new AudioContext();
            }
            const ctx = audioCtxRef.current;
            if (ctx.state === "suspended") await ctx.resume();
            const source = ctx.createMediaElementSource(audio);
            analyser = ctx.createAnalyser();
            analyser.fftSize = 256;
            source.connect(analyser);
            analyser.connect(ctx.destination);
        } catch (e) {
            console.warn("[AUDIO_ANALYSER] Failed to create analyser, using fallback lip sync", e);
        }

        const dataArray = analyser ? new Uint8Array(analyser.frequencyBinCount) : null;
        const pollVolume = () => {
            if (!isPlayingRef.current || !analyser || !dataArray) return;
            analyser.getByteFrequencyData(dataArray);
            let sum = 0;
            for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
            const avg = sum / dataArray.length / 255;
            emitVolume(avg);
            volumeLoopRef.current = requestAnimationFrame(pollVolume);
        };

        const cleanup = () => {
            cancelAnimationFrame(volumeLoopRef.current);
            emitVolume(0, true);
            isPlayingRef.current = false;
            resumeVadAfterPlayback();
            setTimeout(processAudioQueue, 100);
        };

        audio.onended = cleanup;

        audio.addEventListener("error", () => {
            console.error("[AUDIO ERROR]", audio.error, audioUrl);
            cleanup();
        });

        await audio.play().then(() => {
            if (analyser) pollVolume();
        }).catch((e) => {
            console.error("[PLAY REJECTED]", e, audioUrl);
            cleanup();
        });
    };

    return {
        audioQueueRef,
        isPlayingRef,
        audioRef,
        interruptAudioPlayback,
        processAudioQueue,
    };
}
