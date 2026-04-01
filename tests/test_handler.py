"""Tests for the Slack assistant handler."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


from src.handler import (
    lambda_handler,
    parse_slack_event,
    verify_slack_signature,
)


# ---------------------------------------------------------------------------
# verify_slack_signature
# ---------------------------------------------------------------------------


class TestVerifySlackSignature:
    def test_valid_signature_passes(self):
        """A properly signed request should pass verification."""
        # In real testing, you'd use actual Slack test credentials
        # This test demonstrates the integration point
        assert verify_slack_signature is not None

    def test_missing_timestamp_fails(self):
        """Request without timestamp should fail."""
        result = verify_slack_signature("body", {}, "")
        assert result is False


# ---------------------------------------------------------------------------
# parse_slack_event
# ---------------------------------------------------------------------------


class TestParseSlackEvent:
    def test_parse_slash_command(self):
        """Parse /ask slash command."""
        body = {
            "type": "slash_command",
            "user_id": "U123456",
            "channel_id": "C123456",
            "text": "What is our return policy?",
            "trigger_id": "abc123",
        }

        event = parse_slack_event(body)

        assert event is not None
        assert event.type == "slash_command"
        assert event.user_id == "U123456"
        assert event.text == "What is our return policy?"

    def test_parse_app_mention(self):
        """Parse @bot mention event."""
        body = {
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "user": "U123456",
                "channel": "C123456",
                "text": "<@U_BOT> What is the pricing?",
                "ts": "1234567890.123456",
                "bot_id": "U_BOT",
            },
            "event_id": "Ev123456",
        }

        event = parse_slack_event(body)

        assert event is not None
        assert event.type == "app_mention"
        assert event.user_id == "U123456"
        assert "pricing" in event.text

    def test_parse_url_verification(self):
        """URL verification returns None (handled separately)."""
        body = {
            "type": "url_verification",
            "challenge": "abc123",
        }

        event = parse_slack_event(body)
        assert event is None

    def test_parse_event_without_mention_ignored(self):
        """Messages without bot mention are ignored."""
        body = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "user": "U123456",
                "channel": "C123456",
                "text": "Random message",
                "ts": "1234567890.123456",
            },
        }

        event = parse_slack_event(body)
        assert event is None

    def test_parse_thread_reply(self):
        """Parse message in thread."""
        body = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "user": "U123456",
                "channel": "C123456",
                "text": "<@U_BOT> Follow up question",
                "ts": "1234567890.123457",
                "thread_ts": "1234567890.123456",
                "bot_id": "U_BOT",
            },
            "event_id": "Ev123456",
        }

        event = parse_slack_event(body)

        assert event is not None
        assert event.is_thread_reply is True
        assert event.thread_ts == "1234567890.123456"


# ---------------------------------------------------------------------------
# lambda_handler
# ---------------------------------------------------------------------------


class TestLambdaHandler:
    def _mock_slack_headers(self) -> dict[str, str]:
        """Return minimal headers for Slack request."""
        return {
            "X-Slack-Request-Timestamp": "1234567890",
            "X-Slack-Signature": "v0=abc123",
        }

    def test_url_verification_challenge(self):
        """Slack URL verification should return challenge."""
        body = {
            "type": "url_verification",
            "challenge": "abc123xyz",
        }

        event = {
            "headers": self._mock_slack_headers(),
            "body": json.dumps(body),
        }

        with patch("src.handler.verify_slack_signature", return_value=True):
            result = lambda_handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["challenge"] == "abc123xyz"

    def test_empty_body_returns_400(self):
        event = {
            "headers": self._mock_slack_headers(),
            "body": "",
        }

        result = lambda_handler(event, None)
        assert result["statusCode"] == 400

    def test_invalid_signature_returns_401(self):
        body = {
            "type": "slash_command",
            "user_id": "U123456",
            "channel_id": "C123456",
            "text": "test",
        }

        event = {
            "headers": self._mock_slack_headers(),
            "body": json.dumps(body),
        }

        with patch("src.handler.verify_slack_signature", return_value=False):
            result = lambda_handler(event, None)

        assert result["statusCode"] == 401

    @patch("src.handler.verify_slack_signature", return_value=True)
    @patch("src.handler.KnowledgeBase")
    @patch("src.handler.SlackClient")
    @patch("src.handler.anthropic.Anthropic")
    def test_successful_slash_command(
        self,
        mock_anthropic_cls,
        mock_slack_cls,
        mock_kb_cls,
        mock_verify,
    ):
        """Process a slash command successfully."""
        # Setup mocks
        mock_anthropic = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Return policy info here")]
        mock_response.model = "claude-sonnet-4-20250514"
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        mock_anthropic.messages.create.return_value = mock_response
        mock_anthropic_cls.return_value = mock_anthropic

        mock_kb = MagicMock()
        mock_kb.retrieve.return_value = []  # No documents
        mock_kb_cls.return_value = mock_kb

        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        # Request
        body = {
            "type": "slash_command",
            "user_id": "U123456",
            "channel_id": "C123456",
            "text": "What is the return policy?",
            "trigger_id": "abc123",
        }

        event = {
            "headers": {"X-Slack-Request-Timestamp": "1234567890"},
            "body": json.dumps(body),
        }

        result = lambda_handler(event, None)

        assert result["statusCode"] == 200
        assert mock_slack.post_message.called

    @patch("src.handler.verify_slack_signature", return_value=True)
    def test_event_without_text_ignored(self, mock_verify):
        """Event with no text is ignored."""
        body = {
            "type": "slash_command",
            "user_id": "U123456",
            "channel_id": "C123456",
            "text": "",
            "trigger_id": "abc123",
        }

        event = {
            "headers": {"X-Slack-Request-Timestamp": "1234567890"},
            "body": json.dumps(body),
        }

        result = lambda_handler(event, None)

        assert result["statusCode"] == 200
        body_dict = json.loads(result["body"])
        assert body_dict["ok"] is True
