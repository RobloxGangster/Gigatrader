Codex Guardrails

Do modify: services/**, cli/**, tools/**, tests/**, configs/**, Makefile, .github/workflows/**.

Do not modify or rely on: docs/agents/** (historical AI prompts/specs). Treat as non-authoritative notes.

Never add secrets to the repo. Use .env locally and CI secrets in Actions.

Tests must be offline. Mock Alpaca/DB; default to paper mode.
