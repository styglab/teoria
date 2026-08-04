---
name: test-teoria-mcp
description: Validate the Teoria MCP gateway from unit tests through a real STDIO protocol call, including Tool discovery and public-procurement database queries. Use when asked to test, verify, diagnose, or smoke-test Teoria MCP, its registered Capability tools, or the company-to-procurement-contract MCP path.
---

# Test Teoria MCP

Validate the MCP boundary independently from direct Platform calls. Report separately whether unit tests, protocol initialization, Tool discovery, and actual Tool execution succeeded.

## Workflow

1. Work from the repository root and read `AGENTS.md` plus `docs/architecture/repository-structure.md`.
2. Run the MCP unit tests:

   ```bash
   uv run --locked --package teoria-mcp pytest mcp/tests
   ```

3. Confirm `.codex/config.toml` contains the `teoria` MCP server. Do not print credentials or complete database URLs.
4. Confirm the Data DB is running. Start or modify services only when the user requested it.
5. Run the bundled protocol smoke test:

   ```bash
   uv run --locked --package teoria-mcp python \
     .agents/skills/test-teoria-mcp/scripts/smoke_test.py
   ```

   Override the default date range only when the requested scenario requires it:

   ```bash
   uv run --locked --package teoria-mcp python \
     .agents/skills/test-teoria-mcp/scripts/smoke_test.py \
     --date-from 2026-01-01 --date-to 2026-08-03
   ```

6. If a business registration number was provided, invoke `get_company_public_procurement_contracts` through the available Teoria MCP Tool and verify the returned chain:

   `company → business_registration → contract_participation → contract`

7. Report the failing boundary and exact non-secret error. Do not silently replace an MCP invocation with a direct database or Runtime call.

## Success criteria

- MCP unit tests pass.
- MCP `initialize` and `tools/list` succeed.
- The three public-procurement Tools are exposed.
- `search_public_procurement_contracts` returns a successful MCP result.
- For company lookup requests, the expected ontology objects and links are present.

The current development setup uses embedded Runtime compatibility. Treat embedded DB access as temporary; do not redesign it into the target architecture where MCP calls the Runtime HTTP API.
