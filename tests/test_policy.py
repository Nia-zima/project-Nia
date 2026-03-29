"""
Phase 3: Policy Learning System テスト

Gymnasium環境、経験収集、方策学習のテスト
"""
import sys
from pathlib import Path
import pytest
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from backend.core.policy.environment import DepthSelectionEnv, ConversationState
from backend.core.policy.collector import ExperienceCollector, Experience
from backend.core.policy.learner import PolicyLearner, PolicyConfig
from backend.core.policy.feedback import HumanFeedback, FeedbackType


class TestDepthSelectionEnv:
    """Gymnasium環境のテスト"""

    def test_env_creation(self):
        """環境が正しく作成される"""
        env = DepthSelectionEnv()
        assert env.observation_space.shape == (8,)
        assert env.action_space.n == 4

    def test_reset(self):
        """リセットが正しく動作する"""
        env = DepthSelectionEnv()
        obs, info = env.reset(seed=42)

        assert obs.shape == (8,)
        assert all(0.0 <= v <= 1.0 for v in obs)
        assert "state" in info

    def test_step(self):
        """ステップが正しく動作する"""
        env = DepthSelectionEnv()
        env.reset(seed=42)

        obs, reward, terminated, truncated, info = env.step(1)  # DEPTH1

        assert obs.shape == (8,)
        assert isinstance(reward, float)
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        assert "action_name" in info

    def test_action_names(self):
        """アクション名が正しい"""
        env = DepthSelectionEnv()
        assert env.ACTION_NAMES[0] == "depth0"
        assert env.ACTION_NAMES[1] == "depth1"
        assert env.ACTION_NAMES[2] == "ask"
        assert env.ACTION_NAMES[3] == "wait"

    def test_episode_termination(self):
        """エピソード終了条件が正しい"""
        env = DepthSelectionEnv()
        env.reset(seed=42)

        # DEPTH0を選択すると終了
        _, _, terminated, _, _ = env.step(0)
        assert terminated is True

    def test_reward_calculation(self):
        """報酬計算が正しい"""
        env = DepthSelectionEnv()

        # 高確信度でDEPTH0を選択 → 正の報酬
        high_conf_state = ConversationState(
            confidence_metrics={
                "context_coverage": 0.9,
                "self_consistency": 0.8,
                "logit_based": 0.7,
                "question_clarity": 0.9,
                "composite_raw": 0.85,
                "composite_calibrated": 0.85,
            },
            dissonance=0.1,
            reason_codes=[],
            turn_count=2,
        )
        reward = env._calculate_reward(0, high_conf_state)  # DEPTH0
        assert reward > 0

        # 低確信度でDEPTH0を選択 → 負の報酬
        low_conf_state = ConversationState(
            confidence_metrics={
                "context_coverage": 0.2,
                "self_consistency": 0.3,
                "logit_based": 0.3,
                "question_clarity": 0.4,
                "composite_raw": 0.25,
                "composite_calibrated": 0.25,
            },
            dissonance=0.6,
            reason_codes=[],
            turn_count=2,
        )
        reward = env._calculate_reward(0, low_conf_state)  # DEPTH0
        assert reward < 0


class TestExperienceCollector:
    """経験収集のテスト"""

    def test_collect_experience(self):
        """経験が正しく収集される"""
        collector = ExperienceCollector()

        exp = collector.collect(
            confidence_metrics={
                "context_coverage": 0.7,
                "self_consistency": 0.6,
                "logit_based": 0.5,
                "question_clarity": 0.8,
            },
            dissonance=0.3,
            reason_codes=["user_request"],
            action=1,
            action_name="depth1",
            thread_id="test_thread",
            turn_count=2,
        )

        assert exp.action == 1
        assert exp.action_name == "depth1"
        assert "user_request" in exp.reason_codes

    def test_assign_reward(self):
        """報酬が正しく付与される"""
        collector = ExperienceCollector()

        collector.collect(
            confidence_metrics={"context_coverage": 0.7},
            dissonance=0.3,
            reason_codes=[],
            action=1,
            action_name="depth1",
        )

        collector.assign_reward(0.8, user_satisfaction=0.9)

        exp = collector._current_episode[-1]
        assert exp.reward == 0.8
        assert exp.user_satisfaction == 0.9

    def test_end_episode(self):
        """エピソード終了が正しく処理される"""
        collector = ExperienceCollector()

        # 複数の経験を収集
        for i in range(3):
            collector.collect(
                confidence_metrics={"context_coverage": 0.5 + i * 0.1},
                dissonance=0.2,
                reason_codes=[],
                action=1,
                action_name="depth1",
            )
            collector.assign_reward(0.5)

        collector.end_episode(final_reward=0.3)

        assert len(collector.buffer) == 3
        assert collector.buffer[-1].done is True
        assert len(collector._current_episode) == 0

    def test_get_numpy_batch(self):
        """NumPyバッチが正しく生成される"""
        collector = ExperienceCollector()

        for i in range(10):
            collector.collect(
                confidence_metrics={
                    "context_coverage": 0.5,
                    "self_consistency": 0.5,
                    "logit_based": 0.5,
                    "question_clarity": 0.5,
                },
                dissonance=0.2,
                reason_codes=[],
                action=i % 4,
                action_name=["depth0", "depth1", "ask", "wait"][i % 4],
            )
            collector.assign_reward(0.5)
        collector.end_episode()

        states, actions, rewards, next_states, dones = collector.get_numpy_batch(5)

        assert states.shape == (5, 8)
        assert len(actions) == 5
        assert len(rewards) == 5

    def test_statistics(self):
        """統計情報が正しく計算される"""
        collector = ExperienceCollector()

        for i in range(5):
            collector.collect(
                confidence_metrics={"context_coverage": 0.5},
                dissonance=0.2,
                reason_codes=[],
                action=i % 2,
                action_name="depth1" if i % 2 else "depth0",
            )
            collector.assign_reward(1.0 if i % 2 else -0.5)
        collector.end_episode()

        stats = collector.get_statistics()
        assert stats["count"] == 5
        assert "reward_mean" in stats
        assert "action_distribution" in stats


class TestPolicyLearner:
    """方策学習のテスト"""

    def test_learner_creation(self):
        """学習器が正しく作成される"""
        config = PolicyConfig(learning_rate=0.01, n_epochs=10)
        learner = PolicyLearner(config)

        assert learner.config.learning_rate == 0.01
        assert learner.config.n_epochs == 10

    def test_select_action(self):
        """アクション選択が動作する"""
        learner = PolicyLearner()
        state = np.array([0.5, 0.5, 0.5, 0.5, 0.3, 0.0, 0.0, 0.2], dtype=np.float32)

        action = learner.select_action(state)
        assert 0 <= action <= 3

    def test_train_step(self):
        """1ステップの学習が動作する"""
        learner = PolicyLearner()

        state = np.array([0.5, 0.5, 0.5, 0.5, 0.3, 0.0, 0.0, 0.2], dtype=np.float32)
        next_state = np.array([0.6, 0.5, 0.5, 0.5, 0.2, 0.0, 0.0, 0.3], dtype=np.float32)

        td_error = learner.train_step(state, 1, 0.5, next_state, False)
        assert isinstance(td_error, float)

    def test_train_batch(self):
        """バッチ学習が動作する"""
        learner = PolicyLearner(PolicyConfig(n_epochs=5, batch_size=4))
        collector = ExperienceCollector()

        # 経験を生成
        for i in range(20):
            collector.collect(
                confidence_metrics={
                    "context_coverage": 0.5 + np.random.uniform(-0.2, 0.2),
                    "self_consistency": 0.5,
                    "logit_based": 0.5,
                    "question_clarity": 0.5,
                },
                dissonance=0.3,
                reason_codes=[],
                action=i % 4,
                action_name=["depth0", "depth1", "ask", "wait"][i % 4],
            )
            collector.assign_reward(np.random.uniform(-1, 1))
        collector.end_episode()

        result = learner.train(collector, n_epochs=5)

        assert "n_epochs" in result
        assert "final_td_error" in result
        assert result["n_experiences"] == 20

    def test_policy_summary(self):
        """方策サマリーが取得できる"""
        learner = PolicyLearner()

        # 未学習
        summary = learner.get_policy_summary()
        assert summary["status"] == "untrained"

        # 学習後
        state = np.array([0.5, 0.5, 0.5, 0.5, 0.3, 0.0, 0.0, 0.2], dtype=np.float32)
        learner.train_step(state, 1, 0.5, state, False)

        summary = learner.get_policy_summary()
        assert summary["status"] == "trained"
        assert "action_distribution" in summary


class TestHumanFeedback:
    """Human-in-the-Loopフィードバックのテスト"""

    def test_request_feedback(self):
        """フィードバックリクエストが動作する"""
        feedback = HumanFeedback()

        token = feedback.request_feedback(
            thread_id="test",
            turn_id=1,
            context={"action": "depth1"},
        )

        assert token is not None
        assert feedback.get_pending_count("test") == 1

    def test_submit_thumbs_up(self):
        """サムズアップが動作する"""
        feedback = HumanFeedback()

        feedback.request_feedback("test", 1, {"action": "depth1"})
        result = feedback.submit_thumbs_up("test", 1)

        assert result is not None
        assert result.feedback_type == FeedbackType.THUMBS_UP.value
        assert result.to_reward() == 1.0

    def test_submit_thumbs_down(self):
        """サムズダウンが動作する"""
        feedback = HumanFeedback()

        feedback.request_feedback("test", 1, {"action": "depth0"})
        result = feedback.submit_thumbs_down("test", 1)

        assert result is not None
        assert result.to_reward() == -1.0

    def test_submit_rating(self):
        """5段階評価が動作する"""
        feedback = HumanFeedback()

        feedback.request_feedback("test", 1, {"action": "depth1"})
        result = feedback.submit_rating("test", 1, 4)

        assert result is not None
        assert result.to_reward() == 0.5  # (4-3)/2 = 0.5

    def test_submit_correction(self):
        """修正提案が動作する"""
        feedback = HumanFeedback()

        feedback.request_feedback("test", 1, {"action": "depth0"})
        result = feedback.submit_correction("test", 1, "depth1", "もっと詳しく説明すべき")

        assert result is not None
        assert result.value["correct_action"] == "depth1"
        assert result.to_reward() == -0.5

    def test_satisfaction_score(self):
        """満足度スコアが計算される"""
        feedback = HumanFeedback()

        # 複数のフィードバックを収集
        for i in range(5):
            feedback.request_feedback("test", i, {})
            feedback.submit_rating("test", i, 4)  # 全て4点

        score = feedback.get_satisfaction_score("test")
        assert score is not None
        assert 0.5 < score < 1.0  # 4点はポジティブ

    def test_statistics(self):
        """統計情報が取得できる"""
        feedback = HumanFeedback()

        feedback.request_feedback("test", 1, {})
        feedback.submit_thumbs_up("test", 1)

        stats = feedback.get_statistics()
        assert stats["count"] == 1
        assert "satisfaction_score" in stats


class TestIntegration:
    """統合テスト"""

    def test_env_to_collector_flow(self):
        """環境→収集のフローが動作する"""
        env = DepthSelectionEnv()
        collector = ExperienceCollector()

        obs, info = env.reset(seed=42)
        state = info["state"]

        # 環境からアクションを実行し、経験を収集
        for _ in range(3):
            action = env.action_space.sample()
            obs, reward, terminated, truncated, info = env.step(action)

            collector.collect(
                confidence_metrics=state.confidence_metrics,
                dissonance=state.dissonance,
                reason_codes=state.reason_codes,
                action=action,
                action_name=env.ACTION_NAMES[action],
                turn_count=state.turn_count,
            )
            collector.assign_reward(reward)

            if terminated or truncated:
                break

            state = info["state"]

        collector.end_episode()
        assert len(collector.buffer) > 0

    def test_full_training_loop(self):
        """完全な学習ループが動作する"""
        env = DepthSelectionEnv()
        collector = ExperienceCollector()
        learner = PolicyLearner(PolicyConfig(n_epochs=5, batch_size=8))

        # 経験を収集
        for episode in range(5):
            obs, info = env.reset(seed=episode)
            state = info["state"]

            for _ in range(5):
                action = env.action_space.sample()
                obs, reward, terminated, truncated, info = env.step(action)

                collector.collect(
                    confidence_metrics=state.confidence_metrics,
                    dissonance=state.dissonance,
                    reason_codes=state.reason_codes,
                    action=action,
                    action_name=env.ACTION_NAMES[action],
                    turn_count=state.turn_count,
                )
                collector.assign_reward(reward)

                if terminated or truncated:
                    break

                state = info["state"]

            collector.end_episode()

        # 学習
        result = learner.train(collector)
        assert result["n_epochs"] == 5

        # 評価
        eval_result = learner.evaluate(collector)
        assert "accuracy" in eval_result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
