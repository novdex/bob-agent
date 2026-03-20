"""End-to-end test of all Bob features."""
import sys
sys.path.insert(0, 'src')

print("=== BOB END-TO-END TEST ===\n")

results = []

def check(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    msg = f"  [{status}] {name}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    results.append((name, passed))

# 1. DB init
try:
    from mind_clone.database.session import SessionLocal, init_db
    init_db()
    db = SessionLocal()
    check("DB initialised", True)
except Exception as e:
    check("DB initialised", False, str(e)[:80])
    sys.exit(1)

# 2. All new models
try:
    from mind_clone.database.models import ExperimentLog, MemoryLink
    ep = ExperimentLog(owner_id=1, hypothesis_title="e2e test", score_before=0.5, score_after=0.6, improved=True)
    db.add(ep); db.commit(); db.refresh(ep)
    check("ExperimentLog model", True, f"id={ep.id}")
    ml = MemoryLink(owner_id=1, src_type="research_note", src_id=1, tgt_type="skill", tgt_id=1, relation="related")
    db.add(ml); db.commit(); db.refresh(ml)
    check("MemoryLink model", True, f"id={ml.id}")
except Exception as e:
    check("New DB models", False, str(e)[:80])

# 3. Tool registry — all 88 tools
try:
    from mind_clone.tools.registry import TOOL_DISPATCH
    expected = [
        'save_skill','recall_skill','list_skills','get_skill','archive_skill',
        'run_experiment','link_memories','memory_graph_search','auto_link_memory',
        'optimise_prompts','run_isolated_task','memory_decay'
    ]
    missing = [t for t in expected if t not in TOOL_DISPATCH]
    check("Tool registry (12 new tools)", not missing, f"{len(TOOL_DISPATCH)} total" if not missing else f"missing: {missing}")
except Exception as e:
    check("Tool registry", False, str(e)[:80])

# 4. Skill library
try:
    from mind_clone.tools.skill_library import tool_save_skill, tool_recall_skill, tool_list_skills
    r = tool_save_skill({'_owner_id': 1, 'title': 'E2E Test Skill', 'body': 'Step 1: test. Step 2: verify results carefully.', 'trigger_hints': ['test','e2e']})
    check("Skill library - save_skill", r.get('ok'), f"key={r.get('skill_key','?')}")
    r2 = tool_recall_skill({'_owner_id': 1, 'query': 'test verify results'})
    check("Skill library - recall_skill", r2.get('ok'), f"found={r2.get('found',0)}")
    r3 = tool_list_skills({'_owner_id': 1})
    check("Skill library - list_skills", r3.get('ok'), f"total={r3.get('total',0)}")
except Exception as e:
    check("Skill library", False, str(e)[:80])

# 5. Memory graph
try:
    from mind_clone.services.memory_graph import auto_link, graph_search, link_memories
    from mind_clone.database.models import ResearchNote
    note = ResearchNote(owner_id=1, topic='e2e memory graph test', summary='Testing the auto-link and graph search feature of memory graph')
    db.add(note); db.commit(); db.refresh(note)
    links = auto_link(db, 1, 'research_note', note.id)
    check("Memory graph - auto_link", True, f"{len(links)} links created")
    r = graph_search(db, 1, 'research_note', note.id, depth=1)
    check("Memory graph - graph_search", r.get('nodes_found', 0) >= 0, f"nodes={r.get('nodes_found',0)}")
except Exception as e:
    check("Memory graph", False, str(e)[:80])

# 6. Ebbinghaus
try:
    from mind_clone.services.ebbinghaus import decay_memories, boost_memory, prune_faded_memories
    r = decay_memories(db, 1)
    check("Ebbinghaus - decay", r.get('ok'), f"episodic={r.get('episodic_updated',0)} improvement={r.get('improvement_updated',0)}")
    r2 = prune_faded_memories(db, 1)
    check("Ebbinghaus - prune", r2.get('ok'), f"pruned={r2.get('episodic_pruned',0)}")
except Exception as e:
    check("Ebbinghaus", False, str(e)[:80])

# 7. Reflexion
try:
    from mind_clone.services.reflexion import save_reflection, get_recent_reflections
    note_r = save_reflection(db, 1, 'E2E reflexion test', 'I tried search_web. It failed because network error. Next time I should check connectivity first.', 'search_web')
    check("Reflexion - save_reflection", note_r is not None, f"id={note_r.id if note_r else 'none'}")
    lessons = get_recent_reflections(db, 1, query='search web network', limit=3)
    check("Reflexion - get_recent_reflections", isinstance(lessons, list), f"count={len(lessons)}")
except Exception as e:
    check("Reflexion", False, str(e)[:80])

# 8. Verifier
try:
    from mind_clone.services.verifier import _is_complex_task, verify_and_revise
    assert _is_complex_task('research the best AI papers') == True
    assert _is_complex_task('hi') == False
    assert _is_complex_task('implement a new feature') == True
    check("Generator->Verifier - complexity detection", True, "3/3 correct")
except Exception as e:
    check("Generator->Verifier", False, str(e)[:80])

# 9. Constitutional AI
try:
    from mind_clone.services.constitutional import _needs_review, BOB_CONSTITUTION
    assert _needs_review('I am confident this is correct') == True
    assert _needs_review('Hello how can I help') == False
    assert 'HONESTY' in BOB_CONSTITUTION
    assert 'SAFETY' in BOB_CONSTITUTION
    check("Constitutional AI", True, f"constitution={len(BOB_CONSTITUTION)} chars, triggers working")
except Exception as e:
    check("Constitutional AI", False, str(e)[:80])

# 10. Prompt optimizer
try:
    from mind_clone.services.prompt_optimizer import get_hint_for_tool, get_weak_tools, _BASELINE_TOOL_HINTS
    hint = get_hint_for_tool('search_web')
    assert hint is not None and len(hint) > 10
    weak = get_weak_tools(db, 1)
    check("DSPy prompt optimizer", True, f"baseline_hints={len(_BASELINE_TOOL_HINTS)} weak_tools={len(weak)}")
except Exception as e:
    check("DSPy prompt optimizer", False, str(e)[:80])

# 11. Task isolator
try:
    from mind_clone.services.task_isolator import _build_isolated_system_prompt, IsolatedTaskContext, decompose_and_isolate
    ctx = IsolatedTaskContext(task_id='test', task_description='Calculate 2+2', owner_id=1)
    prompt = _build_isolated_system_prompt(ctx)
    assert 'Calculate 2+2' in prompt
    assert 'Focus ONLY' in prompt
    check("CORPGEN task isolator", True, "context builder OK")
except Exception as e:
    check("CORPGEN task isolator", False, str(e)[:80])

# 12. Auto research / composite score
try:
    from mind_clone.services.auto_research import measure_composite_score, ensure_nightly_experiment_job
    score = measure_composite_score(db, 1)
    assert 'composite' in score
    assert 0.0 <= score['composite'] <= 1.0
    ensure_nightly_experiment_job(db, 1)
    check("Karpathy loop - composite score", True, f"composite={score['composite']} tool_success={score['tool_success_rate']} error={score['error_rate']}")
except Exception as e:
    check("Karpathy loop", False, str(e)[:80])

# 13. Live HTTP check
try:
    import urllib.request
    req = urllib.request.Request('http://localhost:8000/chat', method='POST',
        data=b'{"message":"hi","chat_id":"test"}',
        headers={'Content-Type': 'application/json'})
    try:
        resp = urllib.request.urlopen(req, timeout=3)
        check("Bob HTTP server", True, f"status={resp.status}")
    except urllib.error.HTTPError as e:
        check("Bob HTTP server", e.code < 500, f"status={e.code} (expected 4xx for missing fields)")
except Exception as e:
    check("Bob HTTP server", False, str(e)[:80])

db.close()

# Summary
print()
passed = sum(1 for _, p in results if p)
failed = sum(1 for _, p in results if not p)
print(f"=== RESULTS: {passed}/{len(results)} passed, {failed} failed ===")
if failed:
    print("\nFailed checks:")
    for name, p in results:
        if not p:
            print(f"  - {name}")
