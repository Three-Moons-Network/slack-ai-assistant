"""Tests for knowledge base retrieval."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from src.knowledge import Document, KnowledgeBase


class TestDocument:
    def test_document_name_extraction(self):
        """Extract filename from S3 key."""
        doc = Document(
            key="docs/company-handbook.pdf",
            content="handbook content",
            size_bytes=5000,
        )

        assert doc.name == "company-handbook.pdf"


class TestKnowledgeBase:
    def test_tokenization_filters_stopwords(self):
        """Tokenizer should remove stopwords."""
        kb = KnowledgeBase("test-bucket")

        tokens = kb._tokenize("the quick brown fox jumps over the lazy dog")

        # Should remove "the", "over"
        assert "quick" in tokens
        assert "brown" in tokens
        assert "fox" in tokens
        assert "the" not in tokens

    def test_tokenization_lowercases(self):
        """Tokenizer should normalize to lowercase."""
        kb = KnowledgeBase("test-bucket")

        tokens = kb._tokenize("HELLO World")

        assert "hello" in tokens
        assert "world" in tokens

    def test_tokenization_filters_short_tokens(self):
        """Tokenizer should remove tokens shorter than 3 chars."""
        kb = KnowledgeBase("test-bucket")

        tokens = kb._tokenize("a big document")

        assert "big" in tokens
        assert "document" in tokens
        assert "a" not in tokens  # Too short

    @patch("src.knowledge.boto3.client")
    def test_list_documents(self, mock_boto3_client):
        """List all documents in bucket."""
        mock_s3 = MagicMock()

        # Mock paginator
        mock_paginator = MagicMock()
        mock_pages = [
            {
                "Contents": [
                    {"Key": "docs/file1.txt", "Size": 1000},
                    {"Key": "docs/file2.txt", "Size": 2000},
                    {"Key": "docs/", "Size": 0},  # Directory, should skip
                ],
            },
        ]
        mock_paginator.paginate.return_value = mock_pages
        mock_s3.get_paginator.return_value = mock_paginator

        mock_boto3_client.return_value = mock_s3

        kb = KnowledgeBase("test-bucket")
        docs = kb.list_documents()

        assert len(docs) == 2
        assert docs[0].key == "docs/file1.txt"
        assert docs[0].size_bytes == 1000

    @patch("src.knowledge.boto3.client")
    def test_fetch_document(self, mock_boto3_client):
        """Fetch document content from S3."""
        mock_s3 = MagicMock()
        mock_response = MagicMock()
        mock_response["Body"].read.return_value = b"Document content here"
        mock_s3.get_object.return_value = mock_response

        mock_boto3_client.return_value = mock_s3

        kb = KnowledgeBase("test-bucket")
        content = kb.fetch_document("docs/file.txt")

        assert content == "Document content here"

    @patch.object(KnowledgeBase, "list_documents")
    @patch.object(KnowledgeBase, "fetch_document")
    def test_retrieve_returns_top_matches(self, mock_fetch, mock_list):
        """Retrieve should return top documents by relevance score."""
        # Mock documents
        mock_list.return_value = [
            Document(key="docs/file1.txt", content="", size_bytes=1000),
            Document(key="docs/file2.txt", content="", size_bytes=2000),
        ]

        # Mock content
        def fetch_side_effect(key: str) -> str:
            if "file1" in key:
                return "pricing policy price information"
            return "other stuff unrelated"

        mock_fetch.side_effect = fetch_side_effect

        kb = KnowledgeBase("test-bucket")
        results = kb.retrieve("What is the pricing?", max_documents=2)

        # file1 should rank higher (contains "pricing" and "price")
        assert len(results) == 1
        assert "file1" in results[0][0].key
