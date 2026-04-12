"""Tests for mind_clone.agent.vectors module (sentence-transformers)."""
import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from mind_clone.agent.vectors import (
    get_embedding, get_embeddings_batch, cosine_similarity,
    embedding_to_bytes, bytes_to_embedding, GLOVE_DIM, EMBEDDING_DIM,
)

def _make_mock_model(dim=EMBEDDING_DIM):
    m = MagicMock()
    def _encode(text, **kw):
        if isinstance(text, list):
            return np.array([np.random.randn(dim).astype(np.float32) for _ in text])
        return np.random.randn(dim).astype(np.float32)
    m.encode = MagicMock(side_effect=_encode)
    return m

class TestGetEmbedding:
    def test_returns_zero_when_model_unavailable(self):
        with patch("mind_clone.agent.vectors._ensure_model", return_value=None):
            r = get_embedding("test")
            assert r.shape == (EMBEDDING_DIM,)
            assert np.allclose(r, np.zeros(EMBEDDING_DIM))

    def test_returns_zero_for_empty_string(self):
        assert np.allclose(get_embedding(""), np.zeros(EMBEDDING_DIM))

    def test_returns_zero_for_whitespace(self):
        assert np.allclose(get_embedding("   "), np.zeros(EMBEDDING_DIM))

    def test_correct_dimension(self):
        with patch("mind_clone.agent.vectors._ensure_model", return_value=_make_mock_model()):
            assert get_embedding("test").shape == (EMBEDDING_DIM,)

    def test_returns_float32(self):
        with patch("mind_clone.agent.vectors._ensure_model", return_value=_make_mock_model()):
            assert get_embedding("test").dtype == np.float32

    def test_calls_model_encode(self):
        m = _make_mock_model()
        with patch("mind_clone.agent.vectors._ensure_model", return_value=m):
            get_embedding("hello world")
            m.encode.assert_called_once()

    def test_handles_unicode(self):
        with patch("mind_clone.agent.vectors._ensure_model", return_value=_make_mock_model()):
            assert get_embedding("Hello cafe").shape == (EMBEDDING_DIM,)

class TestGetEmbeddingsBatch:
    def test_returns_list(self):
        with patch("mind_clone.agent.vectors._ensure_model", return_value=_make_mock_model()):
            r = get_embeddings_batch(["a", "b", "c"])
            assert len(r) == 3

    def test_empty_list(self):
        assert get_embeddings_batch([]) == []

    def test_zero_when_model_unavailable(self):
        with patch("mind_clone.agent.vectors._ensure_model", return_value=None):
            r = get_embeddings_batch(["a", "b"])
            assert all(np.allclose(v, np.zeros(EMBEDDING_DIM)) for v in r)

class TestCosineSimilarity:
    def test_identical(self):
        v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        assert np.isclose(cosine_similarity(v, v), 1.0)
    def test_orthogonal(self):
        assert np.isclose(cosine_similarity(np.array([1,0,0.]), np.array([0,1,0.])), 0.0)
    def test_opposite(self):
        assert np.isclose(cosine_similarity(np.array([1,0,0.]), np.array([-1,0,0.])), -1.0)
    def test_zero_vec(self):
        assert cosine_similarity(np.zeros(10), np.ones(10)) == 0.0
    def test_symmetry(self):
        a, b = np.random.randn(50).astype(np.float32), np.random.randn(50).astype(np.float32)
        assert np.isclose(cosine_similarity(a, b), cosine_similarity(b, a))

class TestSerialization:
    def test_roundtrip(self):
        v = np.array([1.5, 2.5, 3.5], dtype=np.float32)
        assert np.allclose(bytes_to_embedding(embedding_to_bytes(v)), v)
    def test_bytes_length(self):
        assert len(embedding_to_bytes(np.zeros(100, dtype=np.float32))) == 400
    def test_returns_copy(self):
        b = embedding_to_bytes(np.array([1.0], dtype=np.float32))
        r = bytes_to_embedding(b); r[0] = 999
        assert np.isclose(bytes_to_embedding(b)[0], 1.0)

class TestConstants:
    def test_embedding_dim(self):
        assert EMBEDDING_DIM == 384
    def test_glove_dim_alias(self):
        assert GLOVE_DIM == EMBEDDING_DIM
