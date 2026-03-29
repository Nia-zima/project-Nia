import { create } from 'zustand';

interface UIStore {
  agentMode: string;
  avatarRenderer: 'vrm' | 'live2d';
  mobileMenuOpen: boolean;

  setAgentMode: (mode: string) => void;
  setAvatarRenderer: (r: 'vrm' | 'live2d') => void;
  setMobileMenuOpen: (v: boolean) => void;
}

export const useUIStore = create<UIStore>((set) => ({
  agentMode: 'normal',
  avatarRenderer: 'vrm',
  mobileMenuOpen: false,

  setAgentMode: (mode) => {
    localStorage.setItem('agent_mode', mode);
    set({ agentMode: mode });
  },
  setAvatarRenderer: (r) => {
    localStorage.setItem('avatar_renderer', r);
    set({ avatarRenderer: r });
  },
  setMobileMenuOpen: (v) => set({ mobileMenuOpen: v }),
}));
