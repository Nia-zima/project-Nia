import { create } from 'zustand';

interface AvatarStore {
  isTalking: boolean;
  emotion: string;
  isThinking: boolean;
  agentState: string;
  gesture: string;
  gestureTick: number;
  audioVolume: number;

  setTalking: (v: boolean) => void;
  setEmotion: (e: string) => void;
  setThinking: (v: boolean) => void;
  setAgentState: (s: string) => void;
  triggerGesture: (g: string) => void;
  setAudioVolume: (v: number) => void;

  /** ChatInterface から呼ばれる一括更新 */
  updateState: (talking: boolean, emotion: string, thinking?: boolean) => void;
}

export const useAvatarStore = create<AvatarStore>((set) => ({
  isTalking: false,
  emotion: 'neutral',
  isThinking: false,
  agentState: '',
  gesture: '',
  gestureTick: 0,
  audioVolume: 0,

  setTalking: (v) => set({ isTalking: v }),
  setEmotion: (e) => set({ emotion: e }),
  setThinking: (v) => set({ isThinking: v }),
  setAgentState: (s) => set({ agentState: s }),
  triggerGesture: (g) => set((s) => ({ gesture: g, gestureTick: s.gestureTick + 1 })),
  setAudioVolume: (v) => set({ audioVolume: v }),
  updateState: (talking, emotion, thinking) =>
    set({
      isTalking: talking,
      emotion,
      ...(typeof thinking === 'boolean' ? { isThinking: thinking } : {}),
    }),
}));
