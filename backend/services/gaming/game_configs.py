"""Preset game configurations for screen-based gameplay."""
from __future__ import annotations

from backend.services.gaming.input_controller import GameConfig

# =============================================================================
# Vision prompts
# =============================================================================

_GENERIC_VISION_PROMPT = (
    "ゲーム画面を分析してください。以下を簡潔に報告:\n"
    "1. 画面に映っている場面（メニュー/ゲームプレイ/ロード画面など）\n"
    "2. プレイヤーキャラクターの状態（HP、位置、装備など見えるもの）\n"
    "3. 周囲の状況（敵、アイテム、障害物など）\n"
    "4. 画面上のテキストやUI要素\n"
    "5. 今すぐ注意すべきこと（危険、チャンスなど）"
)

# =============================================================================
# Game config presets
# =============================================================================

GAME_CONFIGS: dict[str, GameConfig] = {
    "generic": GameConfig(
        game_id="generic",
        game_name="Generic Game",
        vision_prompt=_GENERIC_VISION_PROMPT,
        actions={
            "move_forward": {"type": "key_hold", "key": "w", "duration": 0.5},
            "move_backward": {"type": "key_hold", "key": "s", "duration": 0.5},
            "move_left": {"type": "key_hold", "key": "a", "duration": 0.5},
            "move_right": {"type": "key_hold", "key": "d", "duration": 0.5},
            "jump": {"type": "key_press", "key": "space"},
            "interact": {"type": "key_press", "key": "e"},
            "attack": {"type": "mouse_click", "button": "left"},
            "defend": {"type": "mouse_click", "button": "right"},
            "inventory": {"type": "key_press", "key": "i"},
            "escape": {"type": "key_press", "key": "escape"},
            "look_around": {"type": "mouse_move"},
        },
        loop_interval_sec=3,
    ),
}


def get_config(game_id: str) -> GameConfig | None:
    """Get a game config by ID."""
    return GAME_CONFIGS.get(game_id)


def list_configs() -> list[dict[str, str]]:
    """List available game configs."""
    return [
        {"game_id": c.game_id, "game_name": c.game_name}
        for c in GAME_CONFIGS.values()
    ]
