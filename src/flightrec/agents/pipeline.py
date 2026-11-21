"""PolicyDesk: SequentialAgent planner -> researcher -> operator -> writer -> verifier, each with recorder callbacks."""

from __future__ import annotations

from google.adk.agents import LlmAgent, SequentialAgent
from google.genai import types

from flightrec.agents.tools import get_tools

AGENTS = ["planner", "researcher", "operator", "writer", "verifier"]


def build_pipeline(rec, prompts, model, temperature=0.0, tools: dict | None = None):
    cb = rec.callbacks()
    cfg = types.GenerateContentConfig(temperature=temperature)
    t = tools or get_tools(prompts.VERSION)

    def agent(name, instruction, key, tools=None):
        return LlmAgent(name=name, model=model, instruction=instruction, output_key=key,
                        tools=tools or [], generate_content_config=cfg, **cb)

    return SequentialAgent(name="policydesk", sub_agents=[
        agent("planner", prompts.PLANNER, "plan"),
        agent("researcher", prompts.RESEARCHER, "evidence", [t["search_policies"]]),
        agent("operator", prompts.OPERATOR, "action_result",
              [t["lookup_employee"], t["get_leave_balance"], t["create_it_ticket"], t["submit_expense_claim"]]),
        agent("writer", prompts.WRITER, "draft"),
        agent("verifier", prompts.VERIFIER, "final"),
    ])
