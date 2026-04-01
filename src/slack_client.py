"""
Slack API client wrapper.

Handles posting responses back to Slack using the Slack SDK.
"""

from __future__ import annotations

import logging
from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)


class SlackClient:
    """Wrapper around Slack SDK WebClient for easier usage."""

    def __init__(self, bot_token: str) -> None:
        """Initialize Slack client with bot token."""
        self.client = WebClient(token=bot_token)

    def post_message(
        self,
        channel: str,
        text: str,
        thread_ts: str | None = None,
        blocks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Post a message to a Slack channel.

        Args:
            channel: Channel ID or name (e.g., #general or C1234567890)
            text: Plain text fallback
            thread_ts: Optional thread timestamp to reply in a thread
            blocks: Optional Block Kit blocks for rich formatting

        Returns:
            Response from Slack API

        Raises:
            SlackApiError: If the API call fails
        """
        try:
            response = self.client.chat_postMessage(
                channel=channel,
                text=text,
                thread_ts=thread_ts,
                blocks=blocks,
            )
            logger.info(
                "Message posted",
                extra={
                    "channel": channel,
                    "ts": response.get("ts"),
                },
            )
            return response
        except SlackApiError as exc:
            logger.error(
                "Failed to post message",
                extra={
                    "error": str(exc),
                    "channel": channel,
                },
            )
            raise

    def post_ephemeral_message(
        self,
        channel: str,
        user: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Post an ephemeral (temporary, user-only visible) message.

        Args:
            channel: Channel ID
            user: User ID to show message to
            text: Plain text fallback
            blocks: Optional Block Kit blocks

        Returns:
            Response from Slack API
        """
        try:
            response = self.client.chat_postEphemeral(
                channel=channel,
                user=user,
                text=text,
                blocks=blocks,
            )
            logger.info(
                "Ephemeral message posted",
                extra={"channel": channel, "user": user},
            )
            return response
        except SlackApiError as exc:
            logger.error(
                "Failed to post ephemeral message",
                extra={"error": str(exc), "channel": channel},
            )
            raise

    def upload_file(
        self,
        channels: list[str],
        file: bytes,
        filename: str,
        title: str | None = None,
        initial_comment: str | None = None,
    ) -> dict[str, Any]:
        """
        Upload a file to Slack.

        Args:
            channels: List of channel IDs to upload to
            file: File bytes
            filename: Filename (e.g., "report.pdf")
            title: Optional file title
            initial_comment: Optional message to post with file

        Returns:
            Response from Slack API
        """
        try:
            response = self.client.files_upload_v2(
                channels=channels,
                file=file,
                filename=filename,
                title=title,
                initial_comment=initial_comment,
            )
            logger.info(
                "File uploaded",
                extra={"filename": filename, "channels": channels},
            )
            return response
        except SlackApiError as exc:
            logger.error(
                "Failed to upload file",
                extra={"error": str(exc), "filename": filename},
            )
            raise

    def get_user_info(self, user_id: str) -> dict[str, Any]:
        """
        Get information about a Slack user.

        Args:
            user_id: Slack user ID

        Returns:
            User info dictionary
        """
        try:
            response = self.client.users_info(user=user_id)
            return response.get("user", {})
        except SlackApiError as exc:
            logger.error(
                "Failed to get user info",
                extra={"error": str(exc), "user_id": user_id},
            )
            return {}
