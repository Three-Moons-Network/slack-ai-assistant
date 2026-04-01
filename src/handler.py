"""
Slack AI Assistant Lambda Handler

Receives Slack events (slash commands, mentions) via API Gateway,
retrieves relevant documents from S3, and generates answers using Claude.
Posts responses back to Slack with source citations.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from typing import Any

import anthropic
import boto3
from slack_sdk.signature import SignatureVerifier

from src.knowledge import KnowledgeBase
from src.slack_client import SlackClient

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
S3_BUCKET = os.environ.get("S3_BUCKET", "")
S3_PREFIX = os.environ.get("S3_PREFIX", "docs/")
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "")

# Signature verification
SIGNATURE_VERIFIER = SignatureVerifier(SLACK_SIGNING_SECRET)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SlackEvent:
    """Parsed Slack event."""
    type: str
    user_id: str
    channel: str
    text: str
    timestamp: str
    thread_ts: str | None = None
    event_id: str | None = None

    @property
    def is_thread_reply(self) -> bool:
        """Check if this is a reply in a thread."""
        return self.thread_ts is not None


@dataclass
class AssistantResponse:
    """Response from the assistant."""
    answer: str
    sources: list[str]
    model: str
    tokens_used: int
    latency_ms: int


# ---------------------------------------------------------------------------
# Slack signature verification
# ---------------------------------------------------------------------------

def verify_slack_signature(
    body: str,
    headers: dict[str, Any],
    timestamp: str,
) -> bool:
    """
    Verify that the request came from Slack.

    Uses HMAC-SHA256 signature verification as per Slack API docs.
    """
    try:
        # Check timestamp is not too old (prevent replay attacks)
        request_timestamp = int(timestamp)
        current_timestamp = int(time.time())

        if abs(current_timestamp - request_timestamp) > 300:  # 5 minutes
            logger.warning("Request timestamp too old", extra={"timestamp": request_timestamp})
            return False

        # Verify signature
        return SIGNATURE_VERIFIER.is_valid_request(body, headers)

    except Exception as exc:
        logger.error("Signature verification error", extra={"error": str(exc)})
        return False


# ---------------------------------------------------------------------------
# Parse Slack events
# ---------------------------------------------------------------------------

def parse_slack_event(body: dict[str, Any]) -> SlackEvent | None:
    """
    Parse a Slack event from the request body.

    Handles:
    - slash_command: /ask <question>
    - app_mention: @bot <question>
    """
    event_type = body.get("type")

    # Handle slash command
    if event_type == "slash_command":
        return SlackEvent(
            type="slash_command",
            user_id=body.get("user_id", ""),
            channel=body.get("channel_id", ""),
            text=body.get("text", ""),
            timestamp=body.get("trigger_id", ""),
            event_id=body.get("trigger_id"),
        )

    # Handle events API (app mentions, messages)
    if event_type == "url_verification":
        return None  # Slack URL verification

    if event_type == "event_callback":
        event = body.get("event", {})
        event_subtype = event.get("type")

        # Handle app mention
        if event_subtype == "app_mention":
            # Extract text after bot mention
            text = event.get("text", "")
            text = text.replace(f"<@{event.get('bot_id')}>", "").strip()

            return SlackEvent(
                type="app_mention",
                user_id=event.get("user", ""),
                channel=event.get("channel", ""),
                text=text,
                timestamp=event.get("ts", ""),
                thread_ts=event.get("thread_ts"),
                event_id=body.get("event_id"),
            )

        # Handle message in thread with bot mention
        if event_subtype == "message":
            text = event.get("text", "")
            if "<@" not in text:
                return None  # Ignore messages without mention

            text = text.replace(f"<@{event.get('bot_id')}>", "").strip()

            return SlackEvent(
                type="message",
                user_id=event.get("user", ""),
                channel=event.get("channel", ""),
                text=text,
                timestamp=event.get("ts", ""),
                thread_ts=event.get("thread_ts"),
                event_id=body.get("event_id"),
            )

    return None


# ---------------------------------------------------------------------------
# Knowledge base and Claude
# ---------------------------------------------------------------------------

def generate_answer(
    query: str,
    documents: list[tuple[Any, str]],
) -> AssistantResponse:
    """
    Generate an answer using Claude, grounded in retrieved documents.

    Args:
        query: The user's question
        documents: List of (Document, content) tuples from knowledge base

    Returns:
        AssistantResponse with answer, sources, and metrics
    """
    start = time.monotonic()
    client = anthropic.Anthropic()

    # Build context from documents
    sources_text = ""
    sources_list: list[str] = []

    if documents:
        sources_text = "\n\n## Company Documentation:\n\n"
        for doc, content in documents:
            sources_text += f"### {doc.name}\n{content[:2000]}\n\n"  # Limit per doc
            sources_list.append(doc.name)

    # Build system prompt
    system_prompt = (
        "You are a helpful company assistant. Answer questions based on the provided "
        "documentation. If you don't know something, say so clearly. Always cite your sources "
        "by mentioning the document names you referenced. Be concise and professional."
    )

    # Build user message
    user_message = f"{sources_text}\n\nUser question: {query}"

    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    latency_ms = int((time.monotonic() - start) * 1000)
    tokens_used = response.usage.input_tokens + response.usage.output_tokens

    answer_text = response.content[0].text

    return AssistantResponse(
        answer=answer_text,
        sources=sources_list,
        model=response.model,
        tokens_used=tokens_used,
        latency_ms=latency_ms,
    )


# ---------------------------------------------------------------------------
# DynamoDB conversation caching (optional)
# ---------------------------------------------------------------------------

def cache_conversation(
    channel: str,
    user_id: str,
    question: str,
    answer: str,
    sources: list[str],
) -> None:
    """
    Cache the conversation in DynamoDB for context and audit.

    Args:
        channel: Slack channel
        user_id: Slack user ID
        question: User's question
        answer: Assistant's answer
        sources: List of source documents used
    """
    if not DYNAMODB_TABLE:
        return

    try:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(DYNAMODB_TABLE)

        timestamp = int(time.time())
        conversation_id = f"{channel}#{timestamp}"

        table.put_item(
            Item={
                "conversation_id": conversation_id,
                "channel": channel,
                "user_id": user_id,
                "timestamp": timestamp,
                "question": question,
                "answer": answer,
                "sources": sources,
            }
        )

        logger.info(
            "Conversation cached",
            extra={"id": conversation_id, "sources": len(sources)},
        )

    except Exception as exc:
        logger.error("Failed to cache conversation", extra={"error": str(exc)})


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def lambda_handler(event: dict, context: Any) -> dict:
    """
    AWS Lambda handler for Slack bot.

    Receives Slack events via API Gateway, verifies signature,
    retrieves documents, generates answer, posts to Slack.
    """
    logger.info(
        "Received Slack event",
        extra={
            "headers": list(event.get("headers", {}).keys()),
            "body_len": len(event.get("body", "")),
        },
    )

    try:
        # Parse request
        headers = event.get("headers", {})
        body_str = event.get("body", "")

        if not body_str:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Empty body"}),
            }

        # Verify Slack signature
        timestamp = headers.get("X-Slack-Request-Timestamp", "")
        if not verify_slack_signature(body_str, headers, timestamp):
            logger.warning("Invalid Slack signature")
            return {
                "statusCode": 401,
                "body": json.dumps({"error": "Invalid signature"}),
            }

        # Parse body
        body = json.loads(body_str)

        # Handle URL verification challenge
        if body.get("type") == "url_verification":
            logger.info("Slack URL verification")
            return {
                "statusCode": 200,
                "body": json.dumps({"challenge": body.get("challenge")}),
            }

        # Parse event
        slack_event = parse_slack_event(body)
        if not slack_event or not slack_event.text:
            logger.info("No processable event")
            return {
                "statusCode": 200,
                "body": json.dumps({"ok": True}),
            }

        logger.info(
            "Processing Slack event",
            extra={
                "type": slack_event.type,
                "user": slack_event.user_id,
                "text_len": len(slack_event.text),
            },
        )

        # Initialize clients
        slack_client = SlackClient(SLACK_BOT_TOKEN)
        knowledge_base = KnowledgeBase(S3_BUCKET, S3_PREFIX)

        # Retrieve relevant documents
        documents = knowledge_base.retrieve(slack_event.text, max_documents=3)

        # Generate answer
        response = generate_answer(slack_event.text, documents)

        # Format response with sources
        answer_blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": response.answer,
                },
            },
        ]

        if response.sources:
            sources_text = ", ".join(f"`{s}`" for s in response.sources)
            answer_blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Sources: {sources_text}",
                    },
                ],
            })

        # Post to Slack
        slack_client.post_message(
            channel=slack_event.channel,
            text=response.answer,
            thread_ts=slack_event.thread_ts,
            blocks=answer_blocks,
        )

        # Cache conversation
        cache_conversation(
            slack_event.channel,
            slack_event.user_id,
            slack_event.text,
            response.answer,
            response.sources,
        )

        logger.info(
            "Response posted",
            extra={
                "channel": slack_event.channel,
                "sources": len(response.sources),
                "latency_ms": response.latency_ms,
            },
        )

        return {
            "statusCode": 200,
            "body": json.dumps({"ok": True}),
        }

    except json.JSONDecodeError as exc:
        logger.error("JSON decode error", extra={"error": str(exc)})
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Invalid JSON"}),
        }

    except Exception as exc:
        logger.exception("Unexpected error")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error"}),
        }
