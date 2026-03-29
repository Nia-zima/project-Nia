"""
Depth Contracts - Phase 0

Depth0とDepth1の出力に対する契約（原則）を定義・検証するモジュール。

主要コンポーネント:
- Depth0Contract: Pre-Thoughtの原則（結論を出さない、不確実性を明示）
- Depth1Contract: Organize & Askの原則（質問、整理、推論チェーン）
- ValidationResult: 検証結果を格納するデータクラス
"""

from .depth_contracts import Depth0Contract, Depth1Contract, ValidationResult
from .validators import ContractValidator

__all__ = [
    "Depth0Contract",
    "Depth1Contract",
    "ValidationResult",
    "ContractValidator",
]
