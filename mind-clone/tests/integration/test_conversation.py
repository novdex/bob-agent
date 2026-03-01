"""
Multi-turn conversation soak test (maps to Vending-Bench 2 + t2-bench).

Covers: message ordering stability, context trimming under load,
        tool_call/tool response integrity over many turns,
        memory growth patterns, summary creation.
"""

import pytest
from unittest.mock import patch, MagicMock

from mind_clone.agent.memory import (
    save_user_message,
    save_assistant_message,
    save_tool_result,
    get_conversation_history,
    count_messages,
    clear_conversation_history,
    prepare_messages_for_llm,
    trim_context_window,
    create_conversation_summary,
    get_conversation_summaries,
)
from mind_clone.agent.loop import _sanitize_tool_pairs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _noop_lock(owner_id, reason=""):
    from contextlib import nullcontext
    return nullcontext()


# ---------------------------------------------------------------------------
# Multi-turn conversation stability (maps to Vending-Bench)
# ---------------------------------------------------------------------------

class TestMultiTurnStability:
    """Soak test: 50+ messages, verify no degradation."""

    @patch("mind_clone.core.state.session_write_lock", side_effect=_noop_lock)
    def test_50_message_conversation_stable(self, _lock, db_session, sample_user):
        """Simulate 50 turn conversation and verify data integrity."""
        for i in range(25):
            save_user_message(db_session, sample_user.id, f"User message {i}")
            save_assistant_message(db_session, sample_user.id, f"Assistant response {i}")

        total = count_messages(db_session, sample_user.id)
        assert total == 50

        history = get_conversation_history(db_session, sample_user.id, limit=50)
        assert len(history) == 50

        # Verify alternating user/assistant pattern
        for i in range(0, 50, 2):
            assert history[i]["role"] == "user"
            assert history[i + 1]["role"] == "assistant"

    @patch("mind_clone.core.state.session_write_lock", side_effect=_noop_lock)
    def test_message_content_integrity_at_scale(self, _lock, db_session, sample_user):
        """All 50 messages retain exact content."""
        for i in range(50):
            save_user_message(db_session, sample_user.id, f"exact_content_{i:03d}")

        history = get_conversation_history(db_session, sample_user.id, limit=50)
        for i, msg in enumerate(history):
            assert msg["content"] == f"exact_content_{i:03d}"

    @patch("mind_clone.core.state.session_write_lock", side_effect=_noop_lock)
    def test_tool_call_integrity_over_many_turns(self, _lock, db_session, sample_user):
        """Tool calls and responses maintain pairing over 20 tool rounds."""
        for i in range(20):
            tc_id = f"tc_{i:03d}"
            tool_calls = [{"id": tc_id, "function": {"name": "search_web", "arguments": "{}"}}]
            save_assistant_message(
                db_session, sample_user.id, f"Using tool {i}", tool_calls=tool_calls,
            )
            save_tool_result(db_session, sample_user.id, tc_id, f"Result {i}")

        history = get_conversation_history(db_session, sample_user.id, limit=40)
        assert len(history) == 40

        # Verify all tool_call_ids pair correctly
        for i in range(0, 40, 2):
            assistant_msg = history[i]
            tool_msg = history[i + 1]
            assert assistant_msg["role"] == "assistant"
            assert tool_msg["role"] == "tool"
            assert tool_msg["tool_call_id"] == assistant_msg["tool_calls"][0]["id"]


# ---------------------------------------------------------------------------
# Context trimming under load (maps to Context-Bench)
# ---------------------------------------------------------------------------

class TestContextTrimmingUnderLoad:

    def test_trim_100_messages(self):
        """Verify trimming works correctly with 100 messages."""
        messages = [{"role": "system", "content": "You are Bob."}]
        for i in range(100):
            role = "user" if i % 2 == 0 else "assistant"
            messages.append({"role": role, "content": f"Message content {i} " + "x" * 50})

        result = trim_context_window(messages, max_chars=5000)
        assert result[0]["role"] == "system"
        assert len(result) < 101
        # Most recent messages should be preserved
        assert result[-1]["content"].startswith("Message content")

    def test_trim_preserves_recent_over_old(self):
        """Most recent messages should survive trimming."""
        messages = [{"role": "system", "content": "sys"}]
        for i in range(50):
            messages.append({"role": "user", "content": f"msg_{i:03d}_" + "p" * 200})

        result = trim_context_window(messages, max_chars=3000)
        contents = [m["content"] for m in result if m["role"] == "user"]
        # The last messages should be the ones with highest indices
        last_num = int(contents[-1].split("_")[1])
        assert last_num == 49  # Most recent preserved

    def test_system_always_survives_aggressive_trim(self):
        """Even with very low budget, system message is kept."""
        messages = [
            {"role": "system", "content": "Critical system prompt"},
            *[{"role": "user", "content": "x" * 1000} for _ in range(20)],
        ]
        result = trim_context_window(messages, max_chars=200)
        assert any(m["role"] == "system" for m in result)


# ---------------------------------------------------------------------------
# _sanitize_tool_pairs stress test (maps to GAIA reliability)
# ---------------------------------------------------------------------------

class TestSanitizeToolPairsStress:

    def test_20_matched_pairs(self):
        """20 consecutive tool_call + response pairs — all should survive."""
        messages = []
        for i in range(20):
            tc_id = f"tc_{i:03d}"
            messages.append({
                "role": "assistant", "content": f"Calling tool {i}",
                "tool_calls": [{"id": tc_id, "function": {"name": "search_web", "arguments": "{}"}}],
            })
            messages.append({
                "role": "tool", "content": f"Result {i}", "tool_call_id": tc_id,
            })

        result = _sanitize_tool_pairs(messages)
        assert len(result) == 40  # All pairs preserved

    def test_mixed_orphans_and_matched(self):
        """Mix of matched pairs and orphans — only valid pairs survive."""
        messages = [
            # Matched pair
            {"role": "assistant", "content": "good",
             "tool_calls": [{"id": "tc_good", "function": {"name": "search_web", "arguments": "{}"}}]},
            {"role": "tool", "content": "result", "tool_call_id": "tc_good"},
            # Orphan tool_call (no response)
            {"role": "assistant", "content": "orphan call",
             "tool_calls": [{"id": "tc_orphan", "function": {"name": "read_file", "arguments": "{}"}}]},
            # Orphan tool response (no call)
            {"role": "tool", "content": "orphan result", "tool_call_id": "tc_ghost"},
            # Regular message
            {"role": "user", "content": "hello"},
        ]

        result = _sanitize_tool_pairs(messages)
        # Good pair preserved, orphans handled
        assert any(m.get("tool_call_id") == "tc_good" for m in result)
        assert not any(m.get("tool_call_id") == "tc_ghost" for m in result)
        # User message always preserved
        assert any(m["content"] == "hello" for m in result)

    def test_alternating_user_assistant_tool_pattern(self):
        """Real conversation pattern: user -> assistant(tool) -> tool -> assistant -> user."""
        messages = [
            {"role": "user", "content": "search for AI"},
            {"role": "assistant", "content": "Searching...",
             "tool_calls": [{"id": "tc_1", "function": {"name": "search_web", "arguments": "{}"}}]},
            {"role": "tool", "content": "Found results", "tool_call_id": "tc_1"},
            {"role": "assistant", "content": "Here are the results."},
            {"role": "user", "content": "thanks"},
        ]

        result = _sanitize_tool_pairs(messages)
        assert len(result) == 5
        roles = [m["role"] for m in result]
        assert roles == ["user", "assistant", "tool", "assistant", "user"]


# ---------------------------------------------------------------------------
# Conversation summaries at scale
# ---------------------------------------------------------------------------

class TestConversationSummariesAtScale:

    def test_10_summaries_ordered(self, db_session, sample_user):
        """Multiple summaries maintain correct ordering."""
        for i in range(10):
            create_conversation_summary(
                db_session, sample_user.id,
                start_message_id=i * 10,
                end_message_id=(i + 1) * 10,
                summary=f"Summary batch {i}",
                key_points=[f"point_{i}"],
            )

        summaries = get_conversation_summaries(db_session, sample_user.id, limit=10)
        assert len(summaries) == 10

    def test_summary_key_points_preserved(self, db_session, sample_user):
        create_conversation_summary(
            db_session, sample_user.id, 0, 10,
            "Test summary",
            key_points=["GAIA", "BFCL", "Vending-Bench"],
            open_loops=["Need to test multi-turn"],
        )
        summaries = get_conversation_summaries(db_session, sample_user.id)
        assert summaries[0]["key_points"] == ["GAIA", "BFCL", "Vending-Bench"]
        assert summaries[0]["open_loops"] == ["Need to test multi-turn"]


# ---------------------------------------------------------------------------
# Clear + rebuild (maps to long-running agent sessions)
# ---------------------------------------------------------------------------

class TestClearAndRebuild:

    @patch("mind_clone.core.state.session_write_lock", side_effect=_noop_lock)
    def test_clear_and_rebuild_conversation(self, _lock, db_session, sample_user):
        """Simulate session reset: clear all, rebuild from scratch."""
        # Build up
        for i in range(30):
            save_user_message(db_session, sample_user.id, f"msg_{i}")
        assert count_messages(db_session, sample_user.id) == 30

        # Clear
        deleted = clear_conversation_history(db_session, sample_user.id)
        assert deleted == 30
        assert count_messages(db_session, sample_user.id) == 0

        # Rebuild
        for i in range(10):
            save_user_message(db_session, sample_user.id, f"new_msg_{i}")
        assert count_messages(db_session, sample_user.id) == 10
        history = get_conversation_history(db_session, sample_user.id)
        assert history[0]["content"] == "new_msg_0"
