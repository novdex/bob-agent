# QA Playbook

Structured testing guide for Claude Cowork when testing Bob (mind-clone).

**Tools available:** CLI scripts (`bob_*.py`), `curl`, `pytest`, and **Chrome browser via Computer Use** (for visual UI testing and Telegram Web).

## When to Run QA

- After Claude Code completes any implementation task
- After Bob restarts or config changes
- Weekly health check
- When the user reports an issue

---

## Level 1: Smoke Test (~30 seconds)

Run every time. Confirms Bob is alive and functional.

### 1.1 Server Health

```bash
python mind-clone/scripts/bob_health.py
```

- **Pass:** Server UP, Worker alive, Database healthy
- **Fail:** Any component shows DOWN/dead/error
- **Report:** Paste the full dashboard output

### 1.2 Compile + Test + Lint

```bash
python mind-clone/scripts/bob_check.py
```

- **Pass:** OVERALL: PASS (all steps green)
- **Fail:** Any step shows FAIL
- **Report:** Paste the failed step output

### 1.3 API Endpoints

```bash
python mind-clone/scripts/bob_api.py
```

- **Pass:** 0 failed endpoints
- **Fail:** Any endpoint returns 500 or connection error
- **Report:** List failed endpoints with status codes

---

## Level 2: Functional Test (~2 minutes)

Run after implementation. Confirms features work end-to-end.

### 2.1 Live Integration

```bash
python mind-clone/scripts/bob_test_live.py
```

- **Pass:** OVERALL: PASS (all tests green)
- **Fail:** Any test shows FAIL
- **Report:** Full output including timing

### 2.2 Chat Round-Trip

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is 2+2?", "chat_id": "cowork_qa"}'
```

- **Pass:** Response contains a coherent answer, response time < 30s
- **Fail:** Empty response, error, or timeout
- **Report:** Response text, timing, any error codes

### 2.3 Runtime Diagnostics

```bash
python mind-clone/scripts/bob_diag.py
```

- **Pass:** No critical issues found
- **Fail:** Any DIAGNOSIS issue listed
- **Report:** List all issues found

### 2.4 Memory Systems

```bash
python mind-clone/scripts/bob_memory.py stats
```

- **Pass:** All memory tables exist, counts reasonable
- **Fail:** Missing tables or ERROR entries
- **Report:** Full stats output

### 2.5 Browser: Telegram Web Chat (Computer Use)

Open Chrome and navigate to Telegram Web:

1. Go to `https://web.telegram.org`
2. Log in (if not already)
3. Find Bob's chat (search for the bot name)
4. Send: `hello`
5. Wait for response (up to 30s)
6. Send: `what tools do you have?`
7. Wait for response

- **Pass:** Both messages get coherent responses, no "processing failed" errors, response time < 30s
- **Fail:** No response, error message, garbled output, or timeout
- **Report:** Screenshot of conversation, response times, any errors visible in the UI

### 2.6 Browser: Bob Command Center UI (Computer Use)

Open Chrome and test the frontend dashboard:

1. Ensure Bob is running (`python mind-clone/scripts/bob_health.py`)
2. Navigate to `http://localhost:5173`
3. Verify the page loads (no white screen, no JS errors)
4. Check the status panel shows Bob as connected
5. Send a test message through the UI chat input
6. Verify the response appears in the chat window

- **Pass:** UI loads fully, status shows connected, chat round-trip works
- **Fail:** White screen, JS console errors, status shows disconnected, chat fails
- **Report:** Screenshot of UI state, any console errors (F12 > Console tab), response timing

### 2.7 Browser: API Visual Verification (Computer Use)

Open Chrome and verify key API endpoints return valid JSON:

1. Navigate to `http://localhost:8000/health` — verify JSON with `"status": "ok"`
2. Navigate to `http://localhost:8000/status/runtime` — verify JSON object with runtime keys
3. Navigate to `http://localhost:8000/docs` — verify Swagger/OpenAPI UI loads

- **Pass:** All 3 endpoints return valid JSON or UI, no 500 errors
- **Fail:** Any endpoint returns error, empty page, or non-JSON response
- **Report:** Screenshot of each endpoint's response

---

## Level 3: Deep Diagnostic (~5 minutes)

Run weekly or when investigating issues.

### 3.1 Security Audit

```bash
python mind-clone/scripts/bob_security.py
```

- **Pass:** ALL CHECKS PASSED (8/8)
- **Fail:** Any check shows FAIL
- **Report:** List failed checks with details

### 3.2 LLM Failover Chain

```bash
python mind-clone/scripts/bob_llm.py status
```

- **Pass:** Primary model responding, failover configured
- **Fail:** Primary model errors, no failover
- **Report:** Model status and error details

### 3.3 Telegram Integration

```bash
python mind-clone/scripts/bob_telegram.py status
```

- **Pass:** Bot token configured, webhook or polling active
- **Fail:** Token missing, neither mode active
- **Report:** Full status output

### 3.4 Database Integrity

```bash
python mind-clone/scripts/bob_db.py tables
```

- **Pass:** All expected tables present (40+)
- **Fail:** Missing tables
- **Report:** Table list with counts

### 3.5 Performance Baseline

```bash
python mind-clone/scripts/bob_bench.py latency --messages 5
```

- **Pass:** Mean latency < 30,000ms, 0 errors
- **Fail:** Errors > 0 or mean > 30s
- **Report:** Latency statistics (min, p50, p90, max, mean)

### 3.6 Queue and Scheduler

```bash
python mind-clone/scripts/bob_queue.py status
python mind-clone/scripts/bob_cron.py status
```

- **Pass:** Queue functional, no stuck jobs
- **Fail:** Queue errors, stuck items
- **Report:** Status output from both

### 3.7 Tool Registry

```bash
python mind-clone/scripts/bob_tools.py list
```

- **Pass:** All expected tools registered, none blocked
- **Fail:** Missing or blocked tools
- **Report:** Tool list and any blocked tools

### 3.8 Unit Tests

```bash
cd mind-clone && pytest --tb=short -q
```

- **Pass:** All tests pass (31+ tests)
- **Fail:** Any test failure
- **Report:** Failed test names and short tracebacks

---

## Level 4: Feature-Specific QA

Run after a specific feature implementation. Use this template:

```
Feature: [name from Notion board]
Spec: docs/specs/FEAT-[name].md
Date: YYYY-MM-DD

Tests:
  1. [Description] -- PASS/FAIL -- [details]
  2. [Description] -- PASS/FAIL -- [details]
  3. [Description] -- PASS/FAIL -- [details]

Regression: Ran Level 1 smoke test -- PASS/FAIL
Overall: PASS / FAIL / PARTIAL
Notes: [any observations]
```

Test against the **Acceptance Criteria** listed in the feature spec.

---

## Report Formats

### QA Report (for Notion)

```
Title: QA-YYYY-MM-DD-L[level]-[summary]
Type: QA Report
Priority: P2-Medium (or higher if issues found)

Content:
  Date: YYYY-MM-DD HH:MM
  QA Level: 1 / 2 / 3 / 4
  Trigger: [what prompted this QA run]

  Results:
  | Test | Result | Notes |
  |------|--------|-------|
  | ...  | PASS/FAIL | ... |

  Issues Found: [count]
  Bug Tickets Created: [list or "none"]
  Overall Verdict: PASS / FAIL / PARTIAL
```

### Bug Report (for Notion)

```
Title: BUG-[short description]
Type: Bug
Priority: P0/P1/P2/P3

Content:
  ## Steps to Reproduce
  1. ...
  2. ...

  ## Expected Behavior
  ...

  ## Actual Behavior
  ...

  ## Script/Endpoint Used
  ...

  ## Error Output
  [key lines, truncated]

  ## Suggested Fix Area
  [file or module if known]
```
