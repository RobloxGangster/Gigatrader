# Codegen Guardrails
- Do modify: services/**, cli/**, tools/**, tests/**, configs/**, Makefile, .github/workflows/**, docs/** (except docs/agents/** pointers).
- Do not modify or rely on: docs/agents/** pointer stubs, random *.md outside docs/.
- Keep lockfiles (requirements-*.txt), legal docs, and golden fixtures.
- Tests and validators must run offline and not require external services.
