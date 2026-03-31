"""
Agent core modules.
"""

from .identity import (
    generate_agent_uuid,
    load_identity,
    ensure_identity_exists,
    update_identity_kernel,
    check_authority,
    get_identity_summary,
)
from .memory import (
    get_conversation_history,
    save_message,
    save_user_message,
    save_assistant_message,
    save_tool_result,
    count_messages,
    clear_conversation_history,
    create_conversation_summary,
    get_conversation_summaries,
    prepare_messages_for_llm,
    trim_context_window,
)
from .llm import (
    call_llm,
    call_llm_json_task,
    get_available_models,
    estimate_cost,
)
from .loop import (
    run_agent_turn,
    run_agent_loop,
    build_system_prompt,
)
from .vectors import (
    get_embedding,
    get_embeddings_batch,
    cosine_similarity,
    embedding_to_bytes,
    bytes_to_embedding,
    GLOVE_DIM,
)

__all__ = [
    # Identity
    "generate_agent_uuid",
    "load_identity",
    "ensure_identity_exists",
    "update_identity_kernel",
    "check_authority",
    "get_identity_summary",
    # Memory
    "get_conversation_history",
    "save_message",
    "save_user_message",
    "save_assistant_message",
    "save_tool_result",
    "count_messages",
    "clear_conversation_history",
    "create_conversation_summary",
    "get_conversation_summaries",
    "prepare_messages_for_llm",
    "trim_context_window",
    # LLM
    "call_llm",
    "call_llm_json_task",
    "get_available_models",
    "estimate_cost",
    # Loop
    "run_agent_turn",
    "run_agent_loop",
    "build_system_prompt",
    # Vectors
    "get_embedding",
    "get_embeddings_batch",
    "cosine_similarity",
    "embedding_to_bytes",
    "bytes_to_embedding",
    "GLOVE_DIM",
]
