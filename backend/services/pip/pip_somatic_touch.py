"""
Pip Somatic Touch (Phase D)
Converts Pip Scraps (orphaned emotions, fragmented dialogues) into
somatic feelings (physical sensations or vague memories) for Nia.
Currently runs in shadow mode: generating and logging, but NOT injecting.
"""
from __future__ import annotations

import random
from backend.core.logger import logger
from backend.services.pip.pip_scrap_store import PipScrap

class PipSomaticTouch:
    def __init__(self):
        # Templetes for transforming scraps into somatic whispers
        self.templates_emotion = [
            "ふと、言葉にならなかった感情の欠片が指先から伝わってきた気がした。({content})",
            "なんか懐かしいような、置いてけぼりのような気持ちが一瞬よぎった。({content})",
            "理由もないのに、少し心が揺れる感覚があった。({content})"
        ]
        self.templates_dialogue = [
            "誰かが言いかけてやめた言葉の響きが、耳の奥で微かに鳴った気がする。({content})",
            "口に出さずに飲み込んだ声が、一瞬だけ蘇ってきたような触り心地だった。({content})",
            "断片的な記憶が、触れた瞬間だけフワッと浮かんだ。({content})"
        ]

    def process_touch(self, scrap: PipScrap | None, current_bond: float) -> str | None:
        """
        Convert a scrap into a somatic experience string based on type and bond.
        If no scrap is provided, or the bond is too low to feel anything, returns None.
        """
        if not scrap:
            return None
            
        # Optional: Bond gating (e.g. only feel scraps if bond > -0.2)
        if current_bond < -0.2:
            logger.info(f"[PipSomaticTouch] Bond too low ({current_bond}) to feel scrap {scrap.id}")
            return None

        content = scrap.content
        somatic_text = None

        if scrap.scrap_type == "orphaned_emotion":
            t = random.choice(self.templates_emotion)
            somatic_text = t.format(content=content)
        elif scrap.scrap_type == "fragmented_dialogue":
            t = random.choice(self.templates_dialogue)
            somatic_text = t.format(content=content)
            
        if somatic_text:
            logger.info(
                f"[PipSomaticTouch] SHADOW MODE - Generated but NOT injected:\n"
                f"  Scrap ID: {scrap.id} ({scrap.scrap_type})\n"
                f"  Somatic Text: {somatic_text}"
            )
            
        return somatic_text

pip_somatic_touch = PipSomaticTouch()
