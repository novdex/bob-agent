"""
Comprehensive tests for mind_clone.agent.vectors module.

Focus: embedding validation, vector similarity edge cases, zero vectors,
normalization, and boundary conditions.
"""

import pytest
import numpy as np
from unittest.mock import Mock, patch, MagicMock
from mind_clone.agent.vectors import (
    get_embedding,
    get_embeddings_batch,
    cosine_similarity,
    embedding_to_bytes,
    bytes_to_embedding,
    GLOVE_DIM,
)


class TestGetEmbedding:
    """Test get_embedding function."""

    def test_returns_zero_vector_when_glove_unavailable(self):
        """Should return zero vector when GloVe vectors not available."""
        with patch("mind_clone.agent.vectors._load_glove_vectors") as mock_load:
            mock_load.return_value = {}

            result = get_embedding("test")

            assert isinstance(result, np.ndarray)
            assert result.shape == (GLOVE_DIM,)
            assert np.allclose(result, np.zeros(GLOVE_DIM))

    def test_returns_zero_vector_for_empty_string(self):
        """Should return zero vector for empty string."""
        with patch("mind_clone.agent.vectors._load_glove_vectors") as mock_load:
            mock_load.return_value = {"test": np.ones(GLOVE_DIM)}

            result = get_embedding("")

            assert result.shape == (GLOVE_DIM,)
            assert np.allclose(result, np.zeros(GLOVE_DIM))

    def test_returns_zero_vector_for_no_oov_words(self):
        """Should return zero vector when all words are OOV."""
        with patch("mind_clone.agent.vectors._load_glove_vectors") as mock_load:
            mock_load.return_value = {"test": np.ones(GLOVE_DIM)}

            result = get_embedding("xyz9999 abc9999 def9999")

            assert result.shape == (GLOVE_DIM,)
            assert np.allclose(result, np.zeros(GLOVE_DIM))

    def test_normalizes_output_vector(self):
        """Should return normalized vector with magnitude ~1."""
        with patch("mind_clone.agent.vectors._load_glove_vectors") as mock_load:
            vec = np.random.randn(GLOVE_DIM).astype(np.float32)
            mock_load.return_value = {"test": vec}

            result = get_embedding("test")

            norm = np.linalg.norm(result)
            assert np.isclose(norm, 1.0, atol=1e-6) or np.allclose(result, np.zeros(GLOVE_DIM))

    def test_handles_case_insensitivity(self):
        """Should handle uppercase text."""
        with patch("mind_clone.agent.vectors._load_glove_vectors") as mock_load:
            vec = np.ones(GLOVE_DIM, dtype=np.float32)
            mock_load.return_value = {"test": vec}

            result1 = get_embedding("test")
            result2 = get_embedding("TEST")
            result3 = get_embedding("TeSt")

            assert np.allclose(result1, result2)
            assert np.allclose(result1, result3)

    def test_extracts_words_correctly(self):
        """Should extract words correctly from text."""
        with patch("mind_clone.agent.vectors._load_glove_vectors") as mock_load:
            vec = np.ones(GLOVE_DIM, dtype=np.float32) * 2
            mock_load.return_value = {"hello": vec, "world": vec}

            result = get_embedding("hello world")

            # Average of two unit vectors should be normalized
            assert result.shape == (GLOVE_DIM,)
            assert not np.allclose(result, np.zeros(GLOVE_DIM))

    def test_ignores_punctuation(self):
        """Should ignore punctuation in text."""
        with patch("mind_clone.agent.vectors._load_glove_vectors") as mock_load:
            vec = np.ones(GLOVE_DIM, dtype=np.float32)
            mock_load.return_value = {"hello": vec}

            result = get_embedding("hello!!! world... test,")

            # Should still work despite punctuation
            assert result.shape == (GLOVE_DIM,)

    def test_handles_numbers_in_text(self):
        """Should handle numbers in text."""
        with patch("mind_clone.agent.vectors._load_glove_vectors") as mock_load:
            vec = np.ones(GLOVE_DIM, dtype=np.float32)
            mock_load.return_value = {"test": vec}

            result = get_embedding("test 123 456 abc")

            assert result.shape == (GLOVE_DIM,)

    def test_returns_float32_dtype(self):
        """Should return float32 dtype."""
        with patch("mind_clone.agent.vectors._load_glove_vectors") as mock_load:
            vec = np.ones(GLOVE_DIM, dtype=np.float32)
            mock_load.return_value = {"test": vec}

            result = get_embedding("test")

            assert result.dtype == np.float32

    def test_handles_whitespace_only_input(self):
        """Should handle whitespace-only input."""
        with patch("mind_clone.agent.vectors._load_glove_vectors") as mock_load:
            mock_load.return_value = {"test": np.ones(GLOVE_DIM)}

            result = get_embedding("   \t\n  ")

            assert np.allclose(result, np.zeros(GLOVE_DIM))


class TestGetEmbeddingsBatch:
    """Test get_embeddings_batch function."""

    def test_returns_list_of_embeddings(self):
        """Should return list matching input length."""
        with patch("mind_clone.agent.vectors.get_embedding") as mock_embed:
            mock_embed.return_value = np.ones(GLOVE_DIM, dtype=np.float32)

            result = get_embeddings_batch(["text1", "text2", "text3"])

            assert len(result) == 3
            assert all(isinstance(v, np.ndarray) for v in result)

    def test_handles_empty_list(self):
        """Should handle empty input list."""
        with patch("mind_clone.agent.vectors.get_embedding") as mock_embed:
            result = get_embeddings_batch([])

            assert result == []
            mock_embed.assert_not_called()

    def test_handles_large_batch(self):
        """Should handle large batch of texts."""
        with patch("mind_clone.agent.vectors.get_embedding") as mock_embed:
            mock_embed.return_value = np.ones(GLOVE_DIM, dtype=np.float32)

            texts = [f"text_{i}" for i in range(1000)]
            result = get_embeddings_batch(texts)

            assert len(result) == 1000

    def test_preserves_order(self):
        """Should preserve order of embeddings."""
        with patch("mind_clone.agent.vectors.get_embedding") as mock_embed:
            embeddings = [
                np.ones(GLOVE_DIM, dtype=np.float32) * i
                for i in range(1, 4)
            ]
            mock_embed.side_effect = embeddings

            result = get_embeddings_batch(["a", "b", "c"])

            assert np.allclose(result[0], embeddings[0])
            assert np.allclose(result[1], embeddings[1])
            assert np.allclose(result[2], embeddings[2])


class TestCosineSimilarity:
    """Test cosine_similarity function."""

    def test_identical_vectors_return_one(self):
        """Should return 1.0 for identical vectors."""
        vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)

        similarity = cosine_similarity(vec, vec)

        assert np.isclose(similarity, 1.0)

    def test_orthogonal_vectors_return_zero(self):
        """Should return ~0 for orthogonal vectors."""
        vec1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        vec2 = np.array([0.0, 1.0, 0.0], dtype=np.float32)

        similarity = cosine_similarity(vec1, vec2)

        assert np.isclose(similarity, 0.0)

    def test_opposite_vectors_return_negative_one(self):
        """Should return -1.0 for opposite vectors."""
        vec1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        vec2 = np.array([-1.0, 0.0, 0.0], dtype=np.float32)

        similarity = cosine_similarity(vec1, vec2)

        assert np.isclose(similarity, -1.0)

    def test_zero_vector_a_returns_zero(self):
        """Should return 0 when first vector is zero."""
        vec_zero = np.zeros(100, dtype=np.float32)
        vec = np.ones(100, dtype=np.float32)

        similarity = cosine_similarity(vec_zero, vec)

        assert similarity == 0.0

    def test_zero_vector_b_returns_zero(self):
        """Should return 0 when second vector is zero."""
        vec = np.ones(100, dtype=np.float32)
        vec_zero = np.zeros(100, dtype=np.float32)

        similarity = cosine_similarity(vec, vec_zero)

        assert similarity == 0.0

    def test_both_vectors_zero_returns_zero(self):
        """Should return 0 when both vectors are zero."""
        vec_zero = np.zeros(100, dtype=np.float32)

        similarity = cosine_similarity(vec_zero, vec_zero)

        assert similarity == 0.0

    def test_near_zero_vectors_handled(self):
        """Should handle near-zero vectors gracefully."""
        vec1 = np.array([1e-10, 1e-10, 1e-10], dtype=np.float32)
        vec2 = np.array([1e-10, 1e-10, 1e-10], dtype=np.float32)

        similarity = cosine_similarity(vec1, vec2)

        assert isinstance(similarity, float)
        assert 0.0 <= similarity <= 1.0

    def test_scalar_values_consistent(self):
        """Should return consistent scalar values."""
        vec1 = np.random.randn(100).astype(np.float32)
        vec2 = np.random.randn(100).astype(np.float32)

        similarity = cosine_similarity(vec1, vec2)

        assert isinstance(similarity, float)
        assert -1.0 <= similarity <= 1.0

    def test_different_magnitudes(self):
        """Should be invariant to vector magnitude."""
        vec1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        vec2_small = np.array([0.5, 0.0, 0.0], dtype=np.float32)
        vec2_large = np.array([100.0, 0.0, 0.0], dtype=np.float32)

        sim_small = cosine_similarity(vec1, vec2_small)
        sim_large = cosine_similarity(vec1, vec2_large)

        assert np.isclose(sim_small, sim_large)

    def test_symmetry(self):
        """Should be symmetric: sim(a,b) == sim(b,a)."""
        vec1 = np.random.randn(100).astype(np.float32)
        vec2 = np.random.randn(100).astype(np.float32)

        sim_ab = cosine_similarity(vec1, vec2)
        sim_ba = cosine_similarity(vec2, vec1)

        assert np.isclose(sim_ab, sim_ba)


class TestEmbeddingToBytes:
    """Test embedding_to_bytes function."""

    def test_converts_embedding_to_bytes(self):
        """Should convert numpy array to bytes."""
        vec = np.array([1.0, 2.0, 3.0], dtype=np.float32)

        result = embedding_to_bytes(vec)

        assert isinstance(result, bytes)
        assert len(result) == 12  # 3 * 4 bytes per float32

    def test_preserves_values_on_roundtrip(self):
        """Should preserve values when converted back."""
        original = np.array([1.5, 2.5, 3.5], dtype=np.float32)

        as_bytes = embedding_to_bytes(original)
        recovered = bytes_to_embedding(as_bytes)

        assert np.allclose(original, recovered)

    def test_handles_large_vector(self):
        """Should handle large vectors."""
        vec = np.random.randn(10000).astype(np.float32)

        result = embedding_to_bytes(vec)

        assert isinstance(result, bytes)
        assert len(result) == 40000  # 10000 * 4

    def test_handles_zero_vector(self):
        """Should handle zero vector."""
        vec = np.zeros(100, dtype=np.float32)

        result = embedding_to_bytes(vec)

        assert isinstance(result, bytes)
        assert len(result) == 400


class TestBytesToEmbedding:
    """Test bytes_to_embedding function."""

    def test_converts_bytes_to_embedding(self):
        """Should convert bytes back to numpy array."""
        original = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        as_bytes = embedding_to_bytes(original)

        result = bytes_to_embedding(as_bytes)

        assert isinstance(result, np.ndarray)
        assert result.dtype == np.float32
        assert np.allclose(result, original)

    def test_returns_copy_not_view(self):
        """Should return a copy, not a view."""
        original = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        as_bytes = embedding_to_bytes(original)

        result = bytes_to_embedding(as_bytes)

        # Modify result and verify original bytes unchanged
        result[0] = 999.0
        recovered = bytes_to_embedding(as_bytes)

        assert recovered[0] != 999.0
        assert np.isclose(recovered[0], 1.0)

    def test_handles_empty_bytes(self):
        """Should handle empty bytes."""
        result = bytes_to_embedding(b"")

        assert isinstance(result, np.ndarray)
        assert len(result) == 0

    def test_handles_misaligned_bytes(self):
        """Should handle bytes not aligned to float32 (3 bytes)."""
        # 3 bytes is not a multiple of 4
        with pytest.raises((ValueError, AssertionError)):
            bytes_to_embedding(b"abc")


class TestVectorBoundaries:
    """Test boundary conditions for vector operations."""

    def test_glove_dim_constant(self):
        """Should have correct GLOVE_DIM constant."""
        assert GLOVE_DIM == 100
        assert isinstance(GLOVE_DIM, int)

    def test_embeddings_are_float32(self):
        """All embeddings should be float32."""
        with patch("mind_clone.agent.vectors._load_glove_vectors") as mock_load:
            vec = np.random.randn(GLOVE_DIM).astype(np.float32)
            mock_load.return_value = {"test": vec}

            result = get_embedding("test")

            assert result.dtype == np.float32

    def test_embedding_dimension_consistency(self):
        """All embeddings should have same dimension."""
        with patch("mind_clone.agent.vectors._load_glove_vectors") as mock_load:
            vec = np.ones(GLOVE_DIM, dtype=np.float32)
            mock_load.return_value = {"a": vec, "b": vec}

            e1 = get_embedding("a")
            e2 = get_embedding("b")

            assert e1.shape == e2.shape == (GLOVE_DIM,)

    def test_very_long_text(self):
        """Should handle very long text input."""
        with patch("mind_clone.agent.vectors._load_glove_vectors") as mock_load:
            vec = np.ones(GLOVE_DIM, dtype=np.float32)
            mock_load.return_value = {"word": vec}

            long_text = " ".join(["word"] * 10000)
            result = get_embedding(long_text)

            assert result.shape == (GLOVE_DIM,)

    def test_unicode_text_handling(self):
        """Should handle Unicode text."""
        with patch("mind_clone.agent.vectors._load_glove_vectors") as mock_load:
            vec = np.ones(GLOVE_DIM, dtype=np.float32)
            mock_load.return_value = {"hello": vec}

            result = get_embedding("Hello 世界 مرحبا мир 🚀 café")

            assert result.shape == (GLOVE_DIM,)

    def test_special_characters_ignored(self):
        """Should ignore special characters."""
        with patch("mind_clone.agent.vectors._load_glove_vectors") as mock_load:
            vec = np.ones(GLOVE_DIM, dtype=np.float32)
            mock_load.return_value = {"test": vec}

            result = get_embedding("test!@#$%^&*()")

            assert result.shape == (GLOVE_DIM,)
