from backend.services.speech_sanitizer import detect_internal_leak, finalize_output, SILENCE_DEFAULT
from backend.services import memory_judge


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_detect_internal_leak_tags():
    text = "[[MEMORY_WRITE]] {\"content\": \"x\"}"
    reasons = detect_internal_leak(text)
    _assert(isinstance(reasons, dict), "leak result should be dict")
    _assert(len(reasons.get("warn", [])) >= 0, "warn list missing")


def test_detect_internal_leak_json_fragment():
    text = "{\"summary\": \"x\"}"
    reasons = detect_internal_leak(text)
    _assert("warn" in reasons, "warn key missing")


def test_detect_internal_leak_keywords():
    text = "内部ログを参照しています"
    reasons = detect_internal_leak(text)
    _assert("warn" in reasons, "warn key missing")


def test_finalize_output_blocks_internal():
    text = "私は考えています。"
    cleaned = finalize_output(text)
    _assert(cleaned != SILENCE_DEFAULT, "finalize_output unexpectedly silenced")


def test_summary_has_inference():
    _assert(memory_judge._summary_has_inference("たぶん忙しい"), "inference not detected")
    _assert(not memory_judge._summary_has_inference("ユーザーの名前は太郎"), "false positive inference")


if __name__ == "__main__":
    test_detect_internal_leak_tags()
    test_detect_internal_leak_json_fragment()
    test_detect_internal_leak_keywords()
    test_finalize_output_blocks_internal()
    test_summary_has_inference()
    print("OK: safety spec tests passed")
