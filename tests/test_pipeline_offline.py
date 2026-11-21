"""End-to-end PolicyDesk runs through real ADK with the scripted fake model (no network)."""

from flightrec.agents.executor import execute
from flightrec.recorder.replay import tool_sequence


async def test_live_run_records_all_agents(run_kwargs):
    kw, saved = run_kwargs
    res = await execute("How many sick leaves do I get?", "E1003", **kw)
    assert res.status == "ok", res.error
    agents = [e["agent"] for e in res.events if e["type"] == "llm_call"]
    for a in ("planner", "researcher", "operator", "writer", "verifier"):
        assert a in agents
    assert [e["name"] for e in res.events if e["type"] == "tool_call"] == ["search_policies"]
    assert "[leave_policy]" in res.final_answer
    assert res.totals["tokens_in"] > 0 and res.totals["llm_calls"] >= 6
    assert [e["seq"] for e in res.events] == list(range(len(res.events)))
    assert res.run_id in saved


async def test_action_run_calls_backend(run_kwargs):
    kw, _ = run_kwargs
    res = await execute("What is my leave balance?", "E1003", **kw)
    assert res.status == "ok", res.error
    seq = tool_sequence(res.events)
    assert seq and seq[0][0] == "get_leave_balance"
