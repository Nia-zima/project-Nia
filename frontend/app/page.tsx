"use client";
import React, { useState, useEffect } from 'react';
import Sidebar from '@/components/Sidebar';
import ChatInterface from '@/components/ChatInterface';
import AvatarView from '@/components/AvatarView';
import ActionPanel from '@/components/ActionPanel';
import ActionIssuesPanel from '@/components/ActionIssuesPanel';
import MemoryExplorer from '@/components/MemoryExplorer';
import LivestreamDashboard from '@/components/LivestreamDashboard';
import SettingsPanel from '@/components/SettingsPanel';
import StatsPanel from '@/components/StatsPanel';
import DrawLab from '@/components/DrawLab';
import { Menu, X } from 'lucide-react';

export default function Home() {
  const [activeTab, setActiveTab] = useState('chat'); // 'chat' | 'memories' | 'profile' | 'settings'
  const [isTalking, setIsTalking] = useState(false);
  const [emotion, setEmotion] = useState("neutral");
  const [agentState, setAgentState] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const [agentMode, setAgentMode] = useState('normal'); // 'normal' | 'stream' | 'dev'
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // Load mode from localStorage on mount
  useEffect(() => {
    const savedMode = localStorage.getItem('agent_mode');
    if (savedMode) setAgentMode(savedMode);
  }, []);

  // Save mode when changed
  const handleModeChange = (mode: string) => {
    setAgentMode(mode);
    localStorage.setItem('agent_mode', mode);
  };

  // Close mobile menu when tab changes
  const handleTabChange = (tab: string) => {
    setActiveTab(tab);
    setMobileMenuOpen(false);
  };

  return (
    <main className="flex h-screen w-full overflow-hidden bg-[#0f0f12] text-white">
      {/* Mobile Menu Button */}
      <button
        className="md:hidden fixed top-3 left-3 z-50 p-2 rounded-xl glass"
        onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
      >
        {mobileMenuOpen ? <X size={24} /> : <Menu size={24} />}
      </button>

      {/* 1. Sidebar - Desktop: always visible, Mobile: overlay */}
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

      {/* 2. Main Content Area */}
      <div className="flex-1 flex max-w-full relative">

        {/* Avatar Panel (Right Side by default or Split) */}
        {/* Let's do a split view: Left Chat, Right Avatar */}

        <div className="flex-1 flex flex-col h-full relative z-10 p-2 md:p-4">
          {/* Tab Content Routing */}
          {activeTab === 'chat' && (
            <div className="flex h-full gap-2 md:gap-4">
              {/* Chat Panel (Full width on mobile, 1/3 on XL) */}
              <div className="w-full xl:w-1/3 h-full flex flex-col glass rounded-2xl md:rounded-3xl overflow-hidden relative">
                {/* Background Effect */}
                <div className="absolute top-0 w-full h-32 bg-gradient-to-b from-blue-900/20 to-transparent pointer-events-none" />
                <ChatInterface
                  onStateChange={(talking, emo, thinking) => {
                    setIsTalking(talking);
                    setEmotion(emo);
                    if (typeof thinking === "boolean") {
                      setIsThinking(thinking);
                    }
                  }}
                  onAgentStateChange={(state) => setAgentState(state)}
                  agentMode={agentMode} // Pass mode to chat
                />
              </div>

              {/* Avatar Panel (Right, Grows to fill space) */}
              <div className="hidden xl:flex flex-1 h-full flex-col gap-2">
                <div className="flex-1 rounded-3xl overflow-hidden glass-panel">
                  <AvatarView isTalking={isTalking} emotion={emotion} isThinking={isThinking} stateTag={agentState} />
                </div>
                <div className="h-[40%] min-h-[240px] rounded-3xl overflow-hidden glass-panel">
                  {agentMode === 'stream' ? (
                    <LivestreamDashboard />
                  ) : (
                    <ActionPanel threadId="default_thread" />
                  )}
                </div>
              </div>
            </div>
          )}

          {activeTab === 'memories' && (
            <div className="flex-1 glass rounded-2xl md:rounded-3xl p-4 md:p-8 overflow-y-auto">
              <MemoryExplorer />
            </div>
          )}

          {/* profile tab disabled */}

          {activeTab === 'settings' && (
            <div className="flex-1 glass rounded-2xl md:rounded-3xl p-4 md:p-8 overflow-y-auto">
              <SettingsPanel currentMode={agentMode} onModeChange={handleModeChange} />
            </div>
          )}

          {activeTab === 'stats' && (
            <div className="flex-1 glass rounded-3xl overflow-hidden">
              <StatsPanel />
            </div>
          )}

          {activeTab === 'action_issues' && (
            <div className="flex-1 glass rounded-3xl overflow-hidden">
              <ActionIssuesPanel threadId="default_thread" />
            </div>
          )}

          {activeTab === 'draw_lab' && (
            <div className="flex-1 glass rounded-3xl overflow-hidden">
              <DrawLab />
            </div>
          )}

          {activeTab !== 'chat' && activeTab !== 'memories' && activeTab !== 'settings' && activeTab !== 'stats' && activeTab !== 'action_issues' && activeTab !== 'draw_lab' && (
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
