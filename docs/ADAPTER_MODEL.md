# Adapter Model

This file is the short overview.

For the full repo-grade contract and authoring guidance, use:

- [Architecture Overview](./ARCHITECTURE.md)
- [Adapter Contract](./ADAPTER_CONTRACT.md)
- [AI-Agent Adapter Generation Guide](./AI_ADAPTER_AUTHORING.md)

## Core idea

The repository is intentionally split into:

- generic core engine
- project-specific adapters

The core owns:

- UI
- scenario orchestration
- browser/session lifecycle
- history and artifacts
- evidence generation

An adapter owns:

- routes
- presets
- selectors
- auth hints
- scenarios
- settle hints
- manual-review checkpoints

## Included example

The shipped adapter example is:

- `ncs`

Implemented in:

- `lab/projects/ncs_adapter.py`

## Practical next step

If you want to add a project:

1. Read [Adapter Contract](./ADAPTER_CONTRACT.md)
2. Read [AI-Agent Adapter Generation Guide](./AI_ADAPTER_AUTHORING.md)
3. Inspect [examples/ncs/README.md](../examples/ncs/README.md)
