"""Tests for Twitch IRC fetcher."""
from __future__ import annotations

import pytest

from backend.services.chat_bridge.twitch_fetcher import parse_privmsg


class TestParsePRIVMSG:
    def test_standard_message(self):
        raw = ":alice!alice@alice.tmi.twitch.tv PRIVMSG #mychannel :こんにちは！"
        result = parse_privmsg(raw)
        assert result is not None
        assert result["user_name"] == "alice"
        assert result["user_id"] == "twitch:alice"
        assert result["text"] == "こんにちは！"

    def test_message_with_spaces(self):
        raw = ":bob!bob@bob.tmi.twitch.tv PRIVMSG #stream :hello world this is a test"
        result = parse_privmsg(raw)
        assert result is not None
        assert result["text"] == "hello world this is a test"

    def test_message_with_emotes(self):
        raw = ":viewer1!viewer1@viewer1.tmi.twitch.tv PRIVMSG #ch :Kappa nice play PogChamp"
        result = parse_privmsg(raw)
        assert result is not None
        assert result["text"] == "Kappa nice play PogChamp"
        assert result["user_name"] == "viewer1"

    def test_message_with_colon_in_text(self):
        raw = ":user1!user1@user1.tmi.twitch.tv PRIVMSG #ch :time is 12:30"
        result = parse_privmsg(raw)
        assert result is not None
        assert result["text"] == "time is 12:30"

    def test_ping_returns_none(self):
        assert parse_privmsg("PING :tmi.twitch.tv") is None

    def test_join_returns_none(self):
        raw = ":user!user@user.tmi.twitch.tv JOIN #channel"
        assert parse_privmsg(raw) is None

    def test_notice_returns_none(self):
        raw = ":tmi.twitch.tv NOTICE * :Login authentication failed"
        assert parse_privmsg(raw) is None

    def test_empty_string_returns_none(self):
        assert parse_privmsg("") is None

    def test_numeric_message_returns_none(self):
        raw = ":tmi.twitch.tv 001 justinfan12345 :Welcome, GLHF!"
        assert parse_privmsg(raw) is None

    def test_nia_mention(self):
        raw = ":fan!fan@fan.tmi.twitch.tv PRIVMSG #nia_ch :ニアちゃん何してるの？"
        result = parse_privmsg(raw)
        assert result is not None
        assert "ニアちゃん" in result["text"]
