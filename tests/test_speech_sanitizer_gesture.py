from backend.services.speech_sanitizer import extract_metadata


def test_extract_metadata_accepts_gesture_tag_variants() -> None:
    text = "こんにちは [GESTURE: NOD] ［gesture：wave］ [gesture shrug]"
    cleaned, _primary, _tags, gestures = extract_metadata(text)

    assert "NOD" in gestures
    assert "WAVE" in gestures
    assert "SHRUG" in gestures
    assert "GESTURE" not in cleaned.upper()


def test_extract_metadata_removes_unknown_gesture_tags_without_emitting() -> None:
    text = "テスト [GESTURE:UNKNOWN] [GESTURE:BOW]"
    cleaned, _primary, _tags, gestures = extract_metadata(text)

    assert "UNKNOWN" not in gestures
    assert "BOW" in gestures
    assert "UNKNOWN" not in cleaned
