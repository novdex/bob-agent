# Mind Clone Agent API Documentation

## Base URL

```
http://localhost:8000
```

## Authentication

Most endpoints require authentication via:
- Telegram chat ID (for user-specific endpoints)
- Ops token (for administrative endpoints)

## Endpoints

### Health & Status

#### GET /heartbeat
Health check endpoint.

**Response:**
```json
{
  "status": "alive",
  "agent": "Mind Clone",
  "model": "kimi-k2.5",
  "timestamp": "2026-02-14T22:53:34+00:00"
}
```

#### GET /status/runtime
Get runtime metrics and state.

**Response:**
```json
{
  "worker_alive": true,
  "llm_failover_enabled": false,
  "command_queue_mode": "auto",
  "approval_pending_count": 0,
  "db_healthy": true,
  "webhook_registered": true
}
```

### Chat

#### POST /chat
Send a message to the agent.

**Request:**
```json
{
  "chat_id": "123456",
  "message": "Hello, what can you do?",
  "username": "john_doe"
}
```

**Response:**
```json
{
  "ok": true,
  "response": "I can help you with...",
  "session_id": "abc123"
}
```

### Tasks

#### GET /ui/tasks
List tasks for the authenticated user.

**Query Parameters:**
- `status` (optional) - Filter by status
- `limit` (optional) - Max results (default: 20)

**Response:**
```json
{
  "ok": true,
  "tasks": [
    {
      "id": 1,
      "title": "Research task",
      "status": "running",
      "created_at": "2026-02-14T10:00:00Z"
    }
  ]
}
```

#### POST /ui/tasks
Create a new task.

**Request:**
```json
{
  "title": "Research AI trends",
  "goal": "Find latest AI research papers"
}
```

**Response:**
```json
{
  "ok": true,
  "task_id": 42,
  "status": "open"
}
```

#### GET /ui/tasks/{task_id}
Get task details.

**Response:**
```json
{
  "ok": true,
  "task": {
    "id": 42,
    "title": "Research AI trends",
    "description": "Find latest AI research papers",
    "status": "running",
    "plan": [...],
    "created_at": "2026-02-14T10:00:00Z"
  }
}
```

#### POST /ui/tasks/{task_id}/cancel
Cancel a task.

**Response:**
```json
{
  "ok": true,
  "status": "cancelled"
}
```

### Goals

#### GET /goals
List goals.

**Response:**
```json
{
  "ok": true,
  "goals": [
    {
      "id": 1,
      "title": "Learn Python",
      "status": "active",
      "progress": 45
    }
  ]
}
```

#### POST /goal
Create a goal.

**Request:**
```json
{
  "title": "Learn Python",
  "description": "Master Python programming",
  "priority": "high"
}
```

#### GET /goal/{goal_id}
Get goal details.

#### PATCH /goal/{goal_id}
Update goal.

### Approvals

#### GET /ui/approvals/pending
List pending approvals.

**Response:**
```json
{
  "ok": true,
  "approvals": [
    {
      "id": 1,
      "tool_name": "run_command",
      "arguments": {"command": "ls -la"},
      "requested_at": "2026-02-14T10:00:00Z"
    }
  ]
}
```

#### POST /approval/decision
Approve or reject an approval request.

**Request:**
```json
{
  "token": "abc123",
  "decision": "approve",
  "reason": "Looks safe"
}
```

### Cron Jobs

#### GET /cron/jobs
List scheduled jobs.

#### POST /cron/jobs
Create a scheduled job.

**Request:**
```json
{
  "name": "Daily Report",
  "command": "generate_report",
  "schedule": "0 9 * * *",
  "timezone": "UTC"
}
```

#### POST /cron/jobs/{job_id}/disable
Disable a scheduled job.

### Debug & Monitoring

#### GET /debug/blackbox
Get blackbox event logs.

**Query Parameters:**
- `type` - Event type filter
- `limit` - Max events (default: 100)
- `since` - ISO timestamp

#### GET /debug/blackbox/sessions
List blackbox sessions.

#### GET /debug/blackbox/stream
Stream events (SSE).

### Telegram

#### POST /telegram/webhook
Telegram bot webhook endpoint.

**Note:** This endpoint receives updates from Telegram.

### Admin (Ops)

#### GET /ops/audit/events
Get audit log events.

#### GET /ops/usage/summary
Get usage statistics.

#### POST /ops/memory/reindex
Reindex memory vectors.

## Error Responses

All errors follow this format:

```json
{
  "ok": false,
  "error": "Error message",
  "code": "ERROR_CODE"
}
```

Common error codes:
- `UNAUTHORIZED` - Authentication required
- `FORBIDDEN` - Permission denied
- `NOT_FOUND` - Resource not found
- `VALIDATION_ERROR` - Invalid request data
- `INTERNAL_ERROR` - Server error

## WebSocket / SSE

### Event Stream

Connect to `/debug/blackbox/stream` for real-time events.

**Event Types:**
- `tool_call` - Tool execution
- `llm_request` - LLM API call
- `task_update` - Task status change
- `approval_needed` - Pending approval

## Rate Limiting

API endpoints are rate-limited:
- 100 requests per minute for standard endpoints
- 10 requests per minute for expensive operations (LLM calls)

## Pagination

List endpoints support pagination:

```
GET /ui/tasks?limit=20&offset=40
```

Response includes pagination info:

```json
{
  "ok": true,
  "tasks": [...],
  "pagination": {
    "total": 100,
    "limit": 20,
    "offset": 40,
    "has_more": true
  }
}
```
