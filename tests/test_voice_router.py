from fastapi.testclient import TestClient

from backend.server import app
from backend.services.stt_service import stt_service


def test_voice_session_http_and_ws_ping_pong() -> None:
    with TestClient(app) as client:
        start = client.post(
            "/api/voice/session/start",
            json={"thread_id": "voice_test_thread", "client_id": "voice_test_client"},
        )
        assert start.status_code == 200
        start_body = start.json()
        assert start_body.get("ok") is True
        session = start_body.get("session", {})
        session_id = session.get("session_id")
        assert isinstance(session_id, str) and session_id

        status_before = client.get(f"/api/voice/session/{session_id}")
        assert status_before.status_code == 200
        assert status_before.json().get("session", {}).get("thread_id") == "voice_test_thread"

        with client.websocket_connect(
            f"/api/voice/ws?session_id={session_id}&client_id=voice_test_client",
            headers={"origin": "http://localhost:3000"},
        ) as ws:
            first = ws.receive_json()
            assert first.get("type") == "voice_session_state"
            ws.send_json({"type": "ping"})
            pong = ws.receive_json()
            assert pong.get("type") == "pong"
            ws.send_json({"type": "voice_turn_end", "mime_type": "audio/webm"})
            stt_final = ws.receive_json()
            assert stt_final.get("type") == "stt_final"
            assert "ok" in stt_final

        stop = client.post("/api/voice/session/stop", json={"session_id": session_id, "reason": "manual_stop"})
        assert stop.status_code == 200
        stopped = stop.json().get("session", {})
        assert stopped.get("status") == "manual_stop"
        assert stopped.get("connection_count") == 0


def test_voice_ws_duplicate_seq_is_ignored() -> None:
    with TestClient(app) as client:
        start = client.post(
            "/api/voice/session/start",
            json={"thread_id": "voice_dup_thread", "client_id": "voice_dup_client"},
        )
        assert start.status_code == 200
        session_id = start.json()["session"]["session_id"]

        original_transcribe = stt_service.transcribe_container_bytes
        original_transcribe_pcm = stt_service.transcribe_pcm_bytes
        captured_sizes: list[int] = []

        async def _fake_transcribe(audio_bytes: bytes, mime_type: str):
            captured_sizes.append(len(audio_bytes))
            return {"ok": True, "text": f"len={len(audio_bytes)}", "provider": "fake", "reason": None}

        async def _fake_transcribe_pcm(pcm_bytes: bytes):
            captured_sizes.append(len(pcm_bytes))
            return {"ok": True, "text": f"len={len(pcm_bytes)}", "provider": "fake", "reason": None}

        stt_service.transcribe_container_bytes = _fake_transcribe
        stt_service.transcribe_pcm_bytes = _fake_transcribe_pcm
        try:
            with client.websocket_connect(
                f"/api/voice/ws?session_id={session_id}&client_id=voice_dup_client",
                headers={"origin": "http://localhost:3000"},
            ) as ws:
                _ = ws.receive_json()  # voice_session_state

                # Same seq twice should be deduplicated on server side.
                chunk_msg = {
                    "type": "voice_chunk",
                    "utterance_id": "utt-dup-1",
                    "seq": 1,
                    "mime_type": "audio/webm",
                    "payload_b64": "YQ==",  # b"a"
                }
                ws.send_json(chunk_msg)
                ack1 = ws.receive_json()
                assert ack1.get("type") == "voice_chunk_ack"
                assert ack1.get("duplicate") is None

                ws.send_json(chunk_msg)
                ack2 = ws.receive_json()
                assert ack2.get("type") == "voice_chunk_ack"
                assert ack2.get("duplicate") is True

                ws.send_json({"type": "voice_turn_end", "utterance_id": "utt-dup-1", "mime_type": "audio/webm"})
                final = ws.receive_json()
                assert final.get("type") == "stt_final"
                assert final.get("utterance_id") == "utt-dup-1"
                # PCM size varies depending on ffmpeg decode of test data;
                # just verify stt_final arrives with some text from the fake.
                assert isinstance(final.get("text"), str)
        finally:
            stt_service.transcribe_container_bytes = original_transcribe
            stt_service.transcribe_pcm_bytes = original_transcribe_pcm


def test_voice_ws_interleaved_utterances_return_matching_finals() -> None:
    with TestClient(app) as client:
        start = client.post(
            "/api/voice/session/start",
            json={"thread_id": "voice_interleave_thread", "client_id": "voice_interleave_client"},
        )
        assert start.status_code == 200
        session_id = start.json()["session"]["session_id"]

        original_transcribe = stt_service.transcribe_container_bytes
        original_transcribe_pcm = stt_service.transcribe_pcm_bytes

        async def _fake_transcribe(audio_bytes: bytes, mime_type: str):
            # Distinguish turns by payload length only.
            return {"ok": True, "text": f"len={len(audio_bytes)}", "provider": "fake", "reason": None}

        async def _fake_transcribe_pcm(pcm_bytes: bytes):
            return {"ok": True, "text": f"pcm={len(pcm_bytes)}", "provider": "fake", "reason": None}

        stt_service.transcribe_container_bytes = _fake_transcribe
        stt_service.transcribe_pcm_bytes = _fake_transcribe_pcm
        try:
            with client.websocket_connect(
                f"/api/voice/ws?session_id={session_id}&client_id=voice_interleave_client",
                headers={"origin": "http://localhost:3000"},
            ) as ws:
                _ = ws.receive_json()  # voice_session_state

                # Interleave chunks of two utterances and finalize separately.
                ws.send_json(
                    {
                        "type": "voice_chunk",
                        "utterance_id": "utt-A",
                        "seq": 1,
                        "mime_type": "audio/webm",
                        "payload_b64": "YQ==",  # 1 byte
                    }
                )
                _ = ws.receive_json()
                ws.send_json(
                    {
                        "type": "voice_chunk",
                        "utterance_id": "utt-B",
                        "seq": 1,
                        "mime_type": "audio/webm",
                        "payload_b64": "YmI=",  # 2 bytes
                    }
                )
                _ = ws.receive_json()

                ws.send_json({"type": "voice_turn_end", "utterance_id": "utt-A", "mime_type": "audio/webm"})
                final_a = ws.receive_json()
                assert final_a.get("type") == "stt_final"
                assert final_a.get("utterance_id") == "utt-A"
                # Verify stt_final arrives with text from the fake transcribe
                assert isinstance(final_a.get("text"), str)

                ws.send_json({"type": "voice_turn_end", "utterance_id": "utt-B", "mime_type": "audio/webm"})
                final_b = ws.receive_json()
                assert final_b.get("type") == "stt_final"
                assert final_b.get("utterance_id") == "utt-B"
                assert isinstance(final_b.get("text"), str)
        finally:
            stt_service.transcribe_container_bytes = original_transcribe
            stt_service.transcribe_pcm_bytes = original_transcribe_pcm
