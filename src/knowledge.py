"""
Knowledge base retrieval from S3.

Simple keyword-based document selection (no vector DB).
Fetches documents from S3 and matches against user query.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import boto3

logger = logging.getLogger(__name__)


@dataclass
class Document:
    """A document from the knowledge base."""
    key: str
    content: str
    size_bytes: int

    @property
    def name(self) -> str:
        """Extract filename from S3 key."""
        return self.key.split("/")[-1]


class KnowledgeBase:
    """Simple S3-backed knowledge base with keyword matching."""

    def __init__(self, bucket_name: str, prefix: str = "docs/") -> None:
        """
        Initialize knowledge base.

        Args:
            bucket_name: S3 bucket name
            prefix: S3 prefix for documents (default: "docs/")
        """
        self.bucket_name = bucket_name
        self.prefix = prefix
        self.s3_client = boto3.client("s3")

    def list_documents(self) -> list[Document]:
        """
        List all documents in the knowledge base.

        Returns:
            List of Document objects with metadata
        """
        documents: list[Document] = []

        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self.bucket_name, Prefix=self.prefix)

            for page in pages:
                if "Contents" not in page:
                    continue

                for obj in page["Contents"]:
                    if obj["Key"].endswith("/"):
                        continue  # Skip directories

                    documents.append(
                        Document(
                            key=obj["Key"],
                            content="",  # Content loaded on demand
                            size_bytes=obj["Size"],
                        )
                    )

            logger.info(
                "Listed documents",
                extra={"count": len(documents), "bucket": self.bucket_name},
            )
            return documents

        except Exception as exc:
            logger.error(
                "Failed to list documents",
                extra={"error": str(exc), "bucket": self.bucket_name},
            )
            return []

    def fetch_document(self, key: str) -> str:
        """
        Fetch document content from S3.

        Args:
            key: S3 object key

        Returns:
            Document content as string (utf-8 decoded)
        """
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            content = response["Body"].read().decode("utf-8")
            logger.info("Fetched document", extra={"key": key, "size_bytes": len(content)})
            return content
        except Exception as exc:
            logger.error(
                "Failed to fetch document",
                extra={"error": str(exc), "key": key},
            )
            return ""

    def retrieve(self, query: str, max_documents: int = 3) -> list[tuple[Document, str]]:
        """
        Retrieve relevant documents based on keyword matching.

        Simple strategy: split query into tokens, score documents by token frequency,
        return top matches with their content.

        Args:
            query: User query text
            max_documents: Maximum documents to return

        Returns:
            List of (Document, content) tuples, sorted by relevance
        """
        query_tokens = self._tokenize(query)

        if not query_tokens:
            logger.warning("Empty query tokens")
            return []

        documents = self.list_documents()
        scored_docs: list[tuple[Document, float, str]] = []

        for doc in documents:
            content = self.fetch_document(doc.key)
            if not content:
                continue

            # Simple scoring: count token matches in document
            doc_tokens = self._tokenize(content)
            score = sum(1 for token in query_tokens if token in doc_tokens)

            if score > 0:
                scored_docs.append((doc, float(score), content))

        # Sort by score (descending)
        scored_docs.sort(key=lambda x: x[1], reverse=True)

        result = [(doc, content) for doc, score, content in scored_docs[:max_documents]]

        logger.info(
            "Retrieved documents",
            extra={
                "query": query,
                "count": len(result),
                "max": max_documents,
            },
        )

        return result

    def _tokenize(self, text: str) -> set[str]:
        """
        Simple tokenization: lowercase, split on non-alphanumeric, filter short tokens.

        Args:
            text: Text to tokenize

        Returns:
            Set of tokens (words)
        """
        # Convert to lowercase and split on non-alphanumeric
        tokens = re.findall(r"\b[a-z0-9]+\b", text.lower())

        # Filter out very short tokens and common stopwords
        stopwords = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
            "of", "is", "are", "was", "were", "be", "by", "from", "as", "with",
            "that", "this", "it", "if", "which", "who", "what", "where", "when", "why",
        }

        return {
            token for token in tokens
            if len(token) > 2 and token not in stopwords
        }
