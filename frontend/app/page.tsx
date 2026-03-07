"use client";
import React, { useState, useEffect, useCallback, useRef } from 'react';
import Sidebar from '@/components/Sidebar';
import ChatInterface from '@/components/ChatInterface';
import AvatarView from '@/components/AvatarView';
import dynamic from 'next/dynamic';

const Live2DView = dynamic(() => import('@/components/Live2DView'), { ssr: false });
import ActionIssuesPanel from '@/components/ActionIssuesPanel';
import ActionPanel from '@/components/ActionPanel';
import MemoryExplorer from '@/components/MemoryExplorer';
import LivestreamDashboard from '@/components/LivestreamDashboard';
import ProfileEditor from '@/components/ProfileEditor';
import SettingsPanel from '@/components/SettingsPanel';
import StatsPanel from '@/components/StatsPanel';
import DrawLab from '@/components/DrawLab';
import GamePanel from '@/components/GamePanel';
import VideoPanel from '@/components/VideoPanel';
import IdentityPanel from '@/components/IdentityPanel';
import DiaryViewer from '@/components/DiaryViewer';
import NeroChatPanel from '@/components/NeroChatPanel';
import NeroMeetingsPanel from '@/components/NeroMeetingsPanel';
import NeroTweetsPanel from '@/components/NeroTweetsPanel';
import { Menu, X } from 'lucide-react';
import { useUIStore } from '@/lib/stores/uiStore';

const MIN_CHAT_RATIO = 20;
const MAX_CHAT_RATIO = 70;
const DEFAULT_CHAT_RATIO = 33;

export default function Home() {
  const [activeTab, setActiveTab] = useState('chat');
  const { agentMode, setAgentMode, avatarRenderer, setAvatarRenderer, mobileMenuOpen, setMobileMenuOpen } = useUIStore();

  // Resizable chat/avatar ratio
  const [chatRatio, setChatRatio] = useState(DEFAULT_CHAT_RATIO);
  const [isDragging, setIsDragging] = useState(false);
  const [isXL, setIsXL] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Load persisted state on mount
  useEffect(() => {
    const savedMode = localStorage.getItem('agent_mode');
    if (savedMode) setAgentMode(savedMode);
    const savedRenderer = localStorage.getItem('avatar_renderer') as 'vrm' | 'live2d' | null;
    if (savedRenderer) setAvatarRenderer(savedRenderer);
    const savedRatio = localStorage.getItem('chat_avatar_ratio');
    if (savedRatio) {
      const n = Number(savedRatio);
      if (n >= MIN_CHAT_RATIO && n <= MAX_CHAT_RATIO) setChatRatio(n);
    }
  }, []);

  // Track XL breakpoint for resize behavior
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 1280px)');
    setIsXL(mq.matches);
    const handler = (e: MediaQueryListEvent) => setIsXL(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  const handleTabChange = (tab: string) => {
    setActiveTab(tab);
    setMobileMenuOpen(false);
  };

  // --- Resize handlers ---
  const handleResizeMove = useCallback((clientX: number) => {
    const container = containerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    const ratio = ((clientX - rect.left) / rect.width) * 100;
    const clamped = Math.max(MIN_CHAT_RATIO, Math.min(MAX_CHAT_RATIO, Math.round(ratio)));
    setChatRatio(clamped);
  }, []);

  const handleResizeEnd = useCallback(() => {
    setIsDragging(false);
    setChatRatio(prev => {
      localStorage.setItem('chat_avatar_ratio', String(prev));
      return prev;
    });
  }, []);

  useEffect(() => {
    if (!isDragging) return;
    const onMouseMove = (e: MouseEvent) => {
      e.preventDefault();
      handleResizeMove(e.clientX);
    };
    const onMouseUp = () => handleResizeEnd();
    const onTouchMove = (e: TouchEvent) => {
      if (e.touches.length > 0) handleResizeMove(e.touches[0].clientX);
    };
    const onTouchEnd = () => handleResizeEnd();

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
    document.addEventListener('touchmove', onTouchMove);
    document.addEventListener('touchend', onTouchEnd);
    return () => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
      document.removeEventListener('touchmove', onTouchMove);
      document.removeEventListener('touchend', onTouchEnd);
    };
  }, [isDragging, handleResizeMove, handleResizeEnd]);

  const handleResizeStart = (e: React.MouseEvent | React.TouchEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  return (
    <main className="flex h-dvh w-full overflow-hidden bg-[#0f0f12] text-white">
      {/* Mobile Menu Button */}
      <button
        className="md:hidden fixed top-3 left-3 z-50 p-2 rounded-xl glass"
        onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
      >
        {mobileMenuOpen ? <X size={24} /> : <Menu size={24} />}
      </button>

      {/* Desktop Sidebar */}
      <div className="hidden md:block">
        <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />
      </div>

      {/* Mobile Sidebar Overlay */}
      {mobileMenuOpen && (
        <div className="md:hidden fixed inset-0 z-40">
          <div className="absolute inset-0 bg-black/60" onClick={() => setMobileMenuOpen(false)} />
          <div className="absolute left-0 top-0 h-full z-50">
            <Sidebar activeTab={activeTab} setActiveTab={handleTabChange} />
          </div>
        </div>
      )}

      {/* Main Content Area */}
      <div className="flex-1 flex max-w-full relative min-w-0">
        <div className="flex-1 flex flex-col h-full relative z-10 p-2 md:p-4 min-w-0">

          {/* Chat Tab */}
          {activeTab === 'chat' && (
            <div ref={containerRef} className="flex h-full gap-0 relative">
              {/* Chat Column */}
              <div
                className="w-full xl:w-auto h-full flex flex-col gap-2"
                style={isXL ? { width: `${chatRatio}%` } : undefined}
              >
                {/* Livestream Dashboard (stream mode only) */}
                {agentMode === 'stream' && (
                  <div className="hidden xl:block h-[18%] min-h-[110px] rounded-3xl overflow-hidden glass-panel">
                    <LivestreamDashboard threadId="default_thread" />
                  </div>
                )}

                {/* Chat */}
                <div className="flex-1 min-h-0 glass rounded-2xl md:rounded-3xl overflow-hidden relative">
                  <div className="absolute top-0 w-full h-32 bg-gradient-to-b from-blue-900/20 to-transparent pointer-events-none" />
                  <ChatInterface agentMode={agentMode} />
                </div>
              </div>

              {/* Resize Handle */}
              <div
                className="hidden xl:flex items-center justify-center cursor-col-resize select-none group z-10"
                style={{ width: '12px', margin: '0 -2px' }}
                onMouseDown={handleResizeStart}
                onTouchStart={handleResizeStart}
              >
                <div className={`w-1 h-16 rounded-full transition-all duration-150 ${
                  isDragging
                    ? 'bg-blue-400 h-full'
                    : 'bg-white/10 group-hover:bg-blue-400/60 group-hover:h-24'
                }`} />
              </div>

              {/* Avatar Panel */}
              <div
                className="hidden xl:flex flex-1 h-full min-h-0 flex-col gap-2"
                style={isDragging ? { pointerEvents: 'none' } : undefined}
              >
                <div className="flex-1 min-h-0 rounded-3xl overflow-hidden glass-panel">
                  {avatarRenderer === 'live2d' ? (
                    <Live2DView />
                  ) : (
                    <AvatarView />
                  )}
                </div>
              </div>

              {/* Drag overlay to prevent canvas capture */}
              {isDragging && (
                <div className="fixed inset-0 z-50 cursor-col-resize" />
              )}
            </div>
          )}

          {/* Diary Tab */}
          {activeTab === 'diary' && (
            <div className="flex-1 glass rounded-2xl md:rounded-3xl p-4 md:p-8 overflow-y-auto">
              <DiaryViewer />
            </div>
          )}

          {/* Memories Tab */}
          {activeTab === 'memories' && (
            <div className="flex-1 glass rounded-2xl md:rounded-3xl p-4 md:p-8 overflow-y-auto">
              <MemoryExplorer />
            </div>
          )}

          {/* Profile Tab */}
          {activeTab === 'profile' && (
            <div className="flex-1 glass rounded-2xl md:rounded-3xl p-4 md:p-8 overflow-y-auto">
              <ProfileEditor />
            </div>
          )}

          {/* Settings Tab */}
          {activeTab === 'settings' && (
            <div className="flex-1 glass rounded-2xl md:rounded-3xl p-4 md:p-8 overflow-y-auto">
              <SettingsPanel
                currentMode={agentMode}
                onModeChange={setAgentMode}
                avatarRenderer={avatarRenderer}
                onRendererChange={setAvatarRenderer}
              />
            </div>
          )}

          {/* Stats Tab */}
          {activeTab === 'stats' && (
            <div className="flex-1 glass rounded-3xl overflow-hidden">
              <StatsPanel />
            </div>
          )}

          {/* Action Review Tab */}
          {activeTab === 'action_review' && (
            <div className="flex-1 glass rounded-3xl overflow-hidden">
              <ActionPanel threadId="default_thread" />
            </div>
          )}

          {/* Action Issues Tab */}
          {activeTab === 'action_issues' && (
            <div className="flex-1 glass rounded-3xl overflow-hidden">
              <ActionIssuesPanel threadId="default_thread" />
            </div>
          )}

          {/* Draw Lab Tab */}
          {activeTab === 'draw_lab' && (
            <div className="flex-1 glass rounded-3xl overflow-hidden">
              <DrawLab />
            </div>
          )}

          {/* Game Tab */}
          {activeTab === 'game' && (
            <div className="flex-1 glass rounded-3xl overflow-hidden">
              <GamePanel />
            </div>
          )}

          {/* Video Tab */}
          {activeTab === 'video' && (
            <div className="flex-1 glass rounded-3xl overflow-hidden">
              <VideoPanel />
            </div>
          )}

          {/* Identity Tab */}
          {activeTab === 'identity' && (
            <div className="flex-1 glass rounded-3xl overflow-hidden">
              <IdentityPanel />
            </div>
          )}

          {/* Nero Chat Tab */}
          {activeTab === 'nero_chat' && (
            <div className="flex-1 glass rounded-2xl md:rounded-3xl overflow-hidden flex flex-col mt-10 md:mt-0">
              <NeroChatPanel />
            </div>
          )}

          {/* Nero Meetings Tab */}
          {activeTab === 'nero_meetings' && (
            <div className="flex-1 glass rounded-2xl md:rounded-3xl overflow-hidden flex flex-col mt-10 md:mt-0">
              <NeroMeetingsPanel />
            </div>
          )}

          {/* Nero Tweets Tab */}
          {activeTab === 'nero_tweets' && (
            <div className="flex-1 glass rounded-2xl md:rounded-3xl overflow-hidden flex flex-col mt-10 md:mt-0">
              <NeroTweetsPanel />
            </div>
          )}

          {/* Fallback for unknown tabs */}
          {!['chat', 'diary', 'memories', 'profile', 'settings', 'stats', 'action_review', 'action_issues', 'draw_lab', 'game', 'video', 'identity', 'nero_chat', 'nero_meetings', 'nero_tweets'].includes(activeTab) && (
            <div className="flex-1 glass rounded-2xl md:rounded-3xl p-4 md:p-8 flex items-center justify-center">
              <div className="text-center">
                <h2 className="text-3xl font-bold mb-2">準備中</h2>
                <p className="text-gray-500">{activeTab} モジュールは現在開発中です。</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
