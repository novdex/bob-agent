# Bob Agent Deployment Guide

## OpenClaw-Style Always-On Deployment (Windows)

Bob runs as an always-on daemon on your Windows PC, just like OpenClaw's
systemd/launchd approach. It auto-starts on boot, auto-restarts on crash,
and stays running 24/7.

### Architecture

```
┌─────────────┐     ┌──────────────────────────────────────────────┐
│  Telegram    │────▶│  Bob Agent (your Windows PC)                 │
│  (your phone)│◀────│                                              │
└─────────────┘     │  ┌──────────┐  ┌─────────┐  ┌────────────┐  │
                    │  │ FastAPI   │  │ Telegram│  │ Heartbeat  │  │
                    │  │ :8000    │  │ Polling │  │ Supervisor │  │
                    │  └────┬─────┘  └────┬────┘  └─────┬──────┘  │
                    │       │             │             │          │
                    │  ┌────▼─────────────▼─────────────▼──────┐  │
                    │  │         Agent Loop                     │  │
                    │  │   User msg → LLM (Kimi K2.5) → Tools  │  │
                    │  └────────────────────────────────────────┘  │
                    │       │                                      │
                    │  ┌────▼──────────────────────────────────┐   │
                    │  │  SQLite DB + GloVe Memory + Tools     │   │
                    │  └───────────────────────────────────────┘   │
                    └──────────────────────────────────────────────┘
```

### Prerequisites

1. Python 3.10+ installed and on PATH
2. Project cloned and dependencies installed:
   ```powershell
   cd ai-agent-platform
   pip install -e .
   cd mind-clone
   pip install -r requirements.txt
   ```
3. Telegram bot token from @BotFather
4. Kimi API key from Moonshot AI

### Quick Start (5 minutes)

#### Step 1: Configure .env

```powershell
cd mind-clone
copy .env.example .env
```

Edit `.env` and set these critical values:

```ini
# Required: LLM
KIMI_API_KEY=sk-your-moonshot-api-key-here

# Required: Telegram
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz

# Deployment mode (no public URL needed for polling)
WEBHOOK_BASE_URL=http://127.0.0.1:8000

# Enable always-on features
HEARTBEAT_AUTONOMY_ENABLED=true
HEARTBEAT_INTERVAL_SECONDS=45
CRON_ENABLED=true

# Windows: must be off (no Docker sandbox)
OS_SANDBOX_MODE=off

# Recommended policy for personal use
TOOL_POLICY_PROFILE=power
AUTONOMY_MODE=openclaw_max
APPROVAL_GATE_MODE=off
```

#### Step 2: Install Daemon

```powershell
.\scripts\bob_daemon.ps1 install
```

This:
- Creates a Windows Task Scheduler entry
- Starts Bob immediately
- Configures auto-restart on crash (3 retries, then 5 min cooldown)
- Auto-starts on Windows logon

#### Step 3: Message Bob on Telegram

Open Telegram, find your bot, send `/start`. Bob is live.

### Management Commands

```powershell
# Check if Bob is running
.\scripts\bob_daemon.ps1 status

# View logs
.\scripts\bob_daemon.ps1 logs

# Restart Bob
.\scripts\bob_daemon.ps1 restart

# Stop Bob
.\scripts\bob_daemon.ps1 stop

# Start Bob
.\scripts\bob_daemon.ps1 start

# Remove from startup
.\scripts\bob_daemon.ps1 uninstall
```

### What Runs

When Bob starts, it launches:

| Component | Purpose |
|-----------|---------|
| FastAPI server | API on port 8000 (health checks, web UI, webhook fallback) |
| Telegram polling | Long-polls Telegram for messages (no public URL needed) |
| Heartbeat supervisor | Health checks, metrics, cleanup every 45s |
| Cron supervisor | Runs scheduled jobs every 10s |
| Command queue | Fair per-owner message processing with 2 workers |
| Task engine | Background task execution |

### Telegram Commands

| Command | What it does |
|---------|-------------|
| `/start` | Initialize bot, create your user |
| `/help` | Show available commands |
| `/status` | Bob's runtime status |
| `/task <desc>` | Create a background task |
| `/tasks` | List active tasks |
| `/cancel` | Cancel current task |
| `/approve <token>` | Approve a pending action |
| `/reject <token>` | Reject a pending action |
| `/cron` | List scheduled jobs |
| *(any text)* | Chat with Bob directly |

### Logs

- Main log: `%USERPROFILE%\.mind-clone\logs\bob-agent.log`
- Auto-rotated at 10MB (keeps last 5 files)
- Watchdog events: restart attempts, crash reports

### Troubleshooting

**Port 8000 in use**: Kill existing python processes:
```powershell
Get-Process python | Where-Object { $_.Id -ne $PID } | Stop-Process -Force
```

**Bot not responding**: Check token is valid:
```powershell
curl "https://api.telegram.org/bot<TOKEN>/getMe"
```

**Crash loop**: Check logs for errors:
```powershell
.\scripts\bob_daemon.ps1 logs
```

**Circuit breaker tripped**: Check runtime status:
```powershell
curl http://127.0.0.1:8000/status/runtime
```
