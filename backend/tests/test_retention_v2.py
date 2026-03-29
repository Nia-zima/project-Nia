import os
import time
import importlib
from dataclasses import dataclass
from typing import Optional

@dataclass
class Case:
    name: str
    state_tag: Optional[str]
    seed: float
    age_days: float
    expected_stage: str

def _reload_retention_modules():
    """
    settings が env を読む設計なので、env をセットした後に reload して反映させる。
    """
    import backend.core.config as config
    import backend.services.retention_config as retention_config
    import backend.services.memory_judge as memory_judge

    importlib.reload(config)
    importlib.reload(retention_config)
    importlib.reload(memory_judge)
    return config.settings, memory_judge

def _decide_stage(*, state_tag: Optional[str], eff: float, promote_th: float, bg_th: float) -> str:
    """
    sweep_and_promote と同じ“判定”だけを切り出したミニ判定器。
    DBやChromaの副作用はテストしない（壊れやすいので）。
    """
    tag = (state_tag or "").upper()

    should_promote = eff >= promote_th
    if should_promote:
        return "long_term"

    # background 判定（A運用：upsert失敗してもSQLが真なら進む）
    if eff < bg_th:
        return "shadow" if tag == "DISSONANCE" else "background"

    # それ以外で DISSONANCE は shadow
    if tag == "DISSONANCE":
        return "shadow"

    return "capture"

def _run_cases(env_overrides: dict, cases: list[Case]):
    # env セット（空文字は消す）
    for k, v in env_overrides.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = str(v)

    settings, memory_judge = _reload_retention_modules()

    now = time.time()
    for c in cases:
        created_at = now - (c.age_days * 86400.0)
        eff = memory_judge.effective_retention(
            c.seed,
            created_at=created_at,
            state_tag=c.state_tag,
            now_ts=now,  # テストは now を固定する
        )

        stage = _decide_stage(
            state_tag=c.state_tag,
            eff=eff,
            promote_th=settings.RETENTION_PROMOTE_TH,
            bg_th=settings.RETENTION_BACKGROUND_TH,
        )

        assert stage == c.expected_stage, (
            f"[{c.name}] tag={c.state_tag} seed={c.seed} age_days={c.age_days} "
            f"eff={eff:.4f} expected={c.expected_stage} got={stage} "
            f"(th_promote={settings.RETENTION_PROMOTE_TH}, th_bg={settings.RETENTION_BACKGROUND_TH}, "
            f"hlC={settings.RETENTION_HALF_LIFE_CONSENT}, hlDef={settings.RETENTION_HALF_LIFE_DEFAULT}, grace={settings.RETENTION_GRACE_DAYS})"
        )

def test_retention_v2_default_params():
    """
    本番デフォルト値で、ステージ遷移が崩れていないかを見る。
    """
    env = {
        "RETENTION_PROFILE": "prod",
        # ここは “None” にして env 上書きを消す（＝デフォルト固定を検証）
        "RETENTION_PROMOTE_TH": None,
        "RETENTION_BACKGROUND_TH": None,
        "RETENTION_GRACE_DAYS": None,
        "RETENTION_HALF_LIFE_CONSENT": None,
        "RETENTION_HALF_LIFE_PONDERING": None,
        "RETENTION_HALF_LIFE_DISSONANCE": None,
        "RETENTION_HALF_LIFE_DEFAULT": None,
    }

    cases = [
        # 例：CONSENT は seed が高ければ long_term に行く（閾値0.70想定）
        Case("consent_new_highseed", "CONSENT", 0.80, 0.0, "long_term"),
        # DISSONANCE は long_term にならなければ shadow に寄る
        Case("dissonance_mid", "DISSONANCE", 0.60, 7.0, "shadow"),
        # タグ無しは劣化して capture になる（現状ロジックに合わせる）
        Case("none_week", None, 0.50, 7.0, "capture"),
    ]
    _run_cases(env, cases)

def test_retention_v2_fast_forward_env():
    """
    早回し用の env を明示的に入れた状態でも、
    想定通りの遷移になるか（テスト用プロファイルの健全性チェック）。
    """
    env = {
        "RETENTION_PROFILE": "prod",
        # 早回し例（必要に応じてあなたの“retention_test_v2”と同じ値に合わせてOK）
        "RETENTION_PROMOTE_TH": "0.70",
        "RETENTION_BACKGROUND_TH": "0.10",
        "RETENTION_GRACE_DAYS": "1.0",
        "RETENTION_HALF_LIFE_CONSENT": "10.0",
        "RETENTION_HALF_LIFE_PONDERING": "3.0",
        "RETENTION_HALF_LIFE_DISSONANCE": "1.5",
        "RETENTION_HALF_LIFE_DEFAULT": "2.0",
    }

    cases = [
        Case("consent_30days_seed08", "CONSENT", 0.80, 30.0, "capture"),
        Case("dissonance_7days_seed06", "DISSONANCE", 0.60, 7.0, "shadow"),
        Case("none_7days_seed05", None, 0.50, 7.0, "capture"),
    ]
    _run_cases(env, cases)
