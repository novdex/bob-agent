# Bob Power Features Batch 1 — Design Specification

**Date:** 2026-03-30
**Project:** Bob AI Agent (mind-clone)
**Features:** Context Engine, Persistent Channel Binding, Vision

---

## Feature 1: Smart Context Engine

### Problem
Bob loads last 30 raw messages and sends all to LLM. Wastes tokens on casual messages ("hi", "ok"). Loses important tool calls and corrections when history exceeds 30.

### Solution
Smart compression that keeps important messages full and compresses casual chat into summaries.

### How It Works
Before each LLM call, build context as:
1. **Recent messages (last 10)** — kept full, always
2. **Important messages (any age)** — kept full:
   - Messages containing tool calls or tool results
   - User corrections ("no", "wrong", "actually", "I meant")
   - Messages with code, data, or structured output
   - Research results and trade decisions
3. **Everything else** — compressed into 1-2 sentence summaries per group of 5-10 messages

### Importance Detection Rules
- Message role is "tool" → important
- Assistant message has tool_calls → important
- User message matches correction patterns → important
- Message length > 500 chars → likely important
- Everything else → compressible

### Files
- Create: `src/mind_clone/services/context_engine.py`
- Modify: `src/mind_clone/agent/memory.py` (use new engine in prepare_messages_for_llm)

---

## Feature 2: Persistent Channel Binding

### Problem
When Bob restarts, Telegram connection state is lost. Chat_id to owner_id mapping must be re-established. Cron jobs may fail after restart.

### Solution
Save channel state to disk on every message. Restore on startup.

### State File
Location: `~/.mind-clone/channels.json`
```json
{
  "telegram": {
    "chat_id": "6346698354",
    "username": "arsh9592deep",
    "owner_id": 3,
    "last_update_id": 123456789,
    "connected_at": "2026-03-30T14:00:00Z",
    "webhook_url": ""
  }
}
```

### Lifecycle
- **On message received:** Save/update channel state to disk
- **On startup:** Load state, restore chat_id→owner mapping, resume from last_update_id
- **On shutdown:** Save final state
- **On restart:** Send "Bob is back online" notification

### Files
- Create: `src/mind_clone/services/channel_state.py`
- Modify: `src/mind_clone/services/telegram/commands.py` (save state on message)
- Modify: `src/mind_clone/api/factory.py` (restore state on startup)

---

## Feature 3: Vision / Image Understanding

### Problem
Bob ignores photos sent on Telegram. Only processes text messages. Cannot see screenshots, charts, or images.

### Solution
Add photo handler to Telegram bot. Download image, send to MiMo-V2-Pro (multimodal) via OpenRouter, return analysis.

### Flow
1. User sends photo (with optional caption) on Telegram
2. `handle_photo_message()` downloads the image via Telegram API
3. Image converted to base64
4. Sent to MiMo-V2-Pro via OpenRouter with vision endpoint
5. Response sent back to user on Telegram
6. Optionally dispatched to agent loop for tool-based follow-up

### Model
- Xiaomi MiMo-V2-Pro via OpenRouter (`xiaomi/mimo-v2-pro`)
- Supports image input via base64 in message content
- Cost: $1/M tokens (only when photos are sent)

### Security
- Only processes images from known chat_id (user's chat)
- Max image size: 10MB
- Supported formats: JPEG, PNG, WebP

### Files
- Create: `src/mind_clone/agents/vision.py` (vision LLM call)
- Modify: `src/mind_clone/services/telegram/commands.py` (add handle_photo_message)
- Modify: `src/mind_clone/services/telegram/bot.py` (register PHOTO filter)

---

## Technology
- Vision model: xiaomi/mimo-v2-pro via OpenRouter
- Channel state: JSON file on disk
- Context compression: LLM-based summarization for message groups
- All features use existing Bob infrastructure (no new dependencies)
