# Review agent

This workspace will contain the Python LangGraph workflow, ingestion, deterministic policy engine, evidence tools, model adapters, citation checks, packet composition, and checkpoint integration.

Keep deterministic policy, orchestration, provider adapters, and document extraction in separate modules. Every model/tool boundary uses structured schemas and local fakes. The first implementation change must add locked dependencies and deterministic lint, type-check, unit-test, and package commands.
