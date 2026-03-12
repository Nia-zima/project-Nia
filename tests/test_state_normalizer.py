from backend.core.agent_graph.state_normalizer import normalize_checkpoint_state


def test_normalize_checkpoint_state_splits_legacy_review_fields():
    values = {
        "review_token": "tok",
        "pending_actions": [{"kind": "say", "text": "旧レビュー"}],
        "rejected_actions": [
            {"kind": "say", "text": "旧却下", "token": "tok"},
            {"action_id": "save_memory", "status": "REJECTED", "reason": "gate"},
        ],
    }

    normalized = normalize_checkpoint_state(values)

    assert normalized["review_pending_actions"] == [{"kind": "say", "text": "旧レビュー"}]
    assert normalized["pending_actions"] == []
    assert normalized["review_rejected_actions"] == [{"kind": "say", "text": "旧却下", "token": "tok"}]
    assert normalized["rejected_actions"] == [{"action_id": "save_memory", "status": "REJECTED", "reason": "gate"}]


def test_normalize_checkpoint_state_preserves_explicit_split_fields():
    values = {
        "review_token": "tok",
        "review_pending_actions": [{"kind": "say", "text": "新レビュー"}],
        "pending_actions": [{"action_id": "search_memory", "pending_id": "p1"}],
        "review_rejected_actions": [{"kind": "say", "text": "旧発話", "token": "tok"}],
        "rejected_actions": [{"action_id": "save_memory", "status": "REJECTED"}],
    }

    normalized = normalize_checkpoint_state(values)

    assert normalized["review_pending_actions"] == values["review_pending_actions"]
    assert normalized["pending_actions"] == values["pending_actions"]
    assert normalized["review_rejected_actions"] == values["review_rejected_actions"]
    assert normalized["rejected_actions"] == values["rejected_actions"]
