import React, { useState, useEffect } from 'react';
import { User, Save, Plus, X, Hash, PenTool } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';

interface UserProfile {
    user_name: string;
    bio: string;
    interests: string[];
    traits: string[];
}

export default function ProfileEditor() {
    const [profile, setProfile] = useState<UserProfile>({
        user_name: "",
        bio: "",
        interests: [],
        traits: []
    });
    const [isLoading, setIsLoading] = useState(true);
    const [isSaving, setIsSaving] = useState(false);

    // Tag Input State
    const [newInterest, setNewInterest] = useState("");
    const [newTrait, setNewTrait] = useState("");

    useEffect(() => {
        fetchProfile();
    }, []);

    const fetchProfile = async () => {
        try {
            const data = await apiClient.fetchProfile() as unknown as UserProfile;
            setProfile(data);
        } catch (e) {
            console.error("Failed to fetch profile", e);
        } finally {
            setIsLoading(false);
        }
    };

    const handleSave = async () => {
        setIsSaving(true);
        try {
            await apiClient.updateProfile(profile as unknown as Record<string, unknown>);
            // Show success feedback (simple alert for now, toast ideal)
            alert("保存しました！");
        } catch (e) {
            console.error("Failed to save profile", e);
            alert("保存に失敗しました");
        } finally {
            setIsSaving(false);
        }
    };

    const addTag = (type: 'interests' | 'traits', value: string) => {
        if (!value.trim()) return;
        if (profile[type].includes(value.trim())) return;

        setProfile(prev => ({
            ...prev,
            [type]: [...prev[type], value.trim()]
        }));
    };

    const removeTag = (type: 'interests' | 'traits', value: string) => {
        setProfile(prev => ({
            ...prev,
            [type]: prev[type].filter(t => t !== value)
        }));
    };

    if (isLoading) return <div className="text-gray-400 p-8 text-center">プロフィールを読み込み中...</div>;

    return (
        <div className="h-full flex flex-col gap-8 text-white max-w-2xl mx-auto p-4">
            <header className="flex items-center justify-between border-b border-white/10 pb-4">
                <div className="flex items-center gap-3">
                    <User className="w-6 h-6 text-blue-400" />
                    <h2 className="text-xl font-bold">ユーザープロフィール</h2>
                </div>
                <button
                    onClick={handleSave}
                    disabled={isSaving}
                    className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
                >
                    <Save size={16} />
                    {isSaving ? "保存中..." : "変更を保存"}
                </button>
            </header>

            <div className="space-y-6">
                {/* 1. Basic Info */}
                <section className="space-y-4">
                    <div>
                        <label className="block text-xs font-medium text-gray-400 mb-1 uppercase">名前 (Originの名前)</label>
                        <input
                            type="text"
                            value={profile.user_name}
                            onChange={e => setProfile({ ...profile, user_name: e.target.value })}
                            className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all font-semibold text-lg"
                            placeholder="あなたの名前"
                        />
                    </div>

                    <div>
                        <label className="block text-xs font-medium text-gray-400 mb-1 uppercase">紹介文 / メモ</label>
                        <textarea
                            value={profile.bio}
                            onChange={e => setProfile({ ...profile, bio: e.target.value })}
                            className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all h-24 resize-none"
                            placeholder="ニアに知っておいてほしいことはありますか？"
                        />
                    </div>
                </section>

                {/* 2. Interests Tags */}
                <section>
                    <label className="block text-xs font-medium text-gray-400 mb-2 uppercase flex items-center gap-2">
                        <Hash size={12} />
                        興味・関心体系
                    </label>
                    <div className="bg-white/5 border border-white/10 rounded-xl p-4 space-y-3">
                        <div className="flex flex-wrap gap-2">
                            {profile.interests.map(tag => (
                                <span key={tag} className="flex items-center gap-1 px-3 py-1 bg-blue-500/20 text-blue-200 rounded-full text-sm border border-blue-500/30">
                                    {tag}
                                    <button onClick={() => removeTag('interests', tag)} className="hover:text-white"><X size={12} /></button>
                                </span>
                            ))}
                        </div>
                        <div className="flex gap-2">
                            <input
                                type="text"
                                value={newInterest}
                                onChange={e => setNewInterest(e.target.value)}
                                onKeyDown={e => {
                                    if (e.key === 'Enter') {
                                        addTag('interests', newInterest);
                                        setNewInterest("");
                                    }
                                }}
                                className="flex-1 bg-transparent border-none outline-none text-sm placeholder-gray-500"
                                placeholder="興味を追加 (Enterで確定)..."
                            />
                            <button
                                onClick={() => {
                                    addTag('interests', newInterest);
                                    setNewInterest("");
                                }}
                                className="p-1 hover:bg-white/10 rounded"
                            >
                                <Plus size={16} className="text-gray-400" />
                            </button>
                        </div>
                    </div>
                </section>

                {/* 3. Traits Tags */}
                <section>
                    <label className="block text-xs font-medium text-gray-400 mb-2 uppercase flex items-center gap-2">
                        <PenTool size={12} />
                        性格・特徴など
                    </label>
                    <div className="bg-white/5 border border-white/10 rounded-xl p-4 space-y-3">
                        <div className="flex flex-wrap gap-2">
                            {profile.traits.map(tag => (
                                <span key={tag} className="flex items-center gap-1 px-3 py-1 bg-purple-500/20 text-purple-200 rounded-full text-sm border border-purple-500/30">
                                    {tag}
                                    <button onClick={() => removeTag('traits', tag)} className="hover:text-white"><X size={12} /></button>
                                </span>
                            ))}
                        </div>
                        <div className="flex gap-2">
                            <input
                                type="text"
                                value={newTrait}
                                onChange={e => setNewTrait(e.target.value)}
                                onKeyDown={e => {
                                    if (e.key === 'Enter') {
                                        addTag('traits', newTrait);
                                        setNewTrait("");
                                    }
                                }}
                                className="flex-1 bg-transparent border-none outline-none text-sm placeholder-gray-500"
                                placeholder="特徴を追加 (Enterで確定)..."
                            />
                            <button
                                onClick={() => {
                                    addTag('traits', newTrait);
                                    setNewTrait("");
                                }}
                                className="p-1 hover:bg-white/10 rounded"
                            >
                                <Plus size={16} className="text-gray-400" />
                            </button>
                        </div>
                    </div>
                </section>
            </div>
        </div>
    );
}
