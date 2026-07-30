# Deployment

The current image installs the exact production dependency set from the committed `uv.lock`, then contains the Teoria Python package and a copy of `registries/` and `references/`. Production-like validation therefore does not depend on a host bind mount.

```bash
docker compose -f deploy/compose.yaml run --build --rm registry-check
```

For local development, overlay the authored registry directory:

```bash
docker compose \
  -f deploy/compose.yaml \
  -f deploy/compose.dev.yaml \
  run --build --rm registry-check
```

The `mcp-stdio` profile is a process definition for local STDIO use. A remote deployment will use a separate Streamable HTTP entrypoint once that adapter is implemented; the compose file intentionally does not advertise an HTTP endpoint that does not exist yet.

Secrets are supplied at runtime through `.env` or a deployment secret manager and are excluded from the image build context.
