"""SkeletonCore — 会話の骨格（方向）を決定するコンポーネント."""

from .turn_role import TurnRole, derive_turn_role, get_turn_role_profile

__all__ = ["TurnRole", "derive_turn_role", "get_turn_role_profile"]
