# ActorHarbor Architecture Overview

ActorHarbor is a standalone engineering tool with a simple split:

- core lab engine
- project adapters
- config/data
- runtime state and artifacts
- examples and tests

## Core package

The current core package is:

- `lab/`

Key modules:

- `lab/app.py`
  - tkinter operator console
- `lab/scenario_runner.py`
  - scenario planning, execution, live session continuity, status aggregation
- `lab/automation/engine.py`
  - Playwright-backed browser automation, launch stabilization, screenshot policy
- `lab/run_history.py`
  - artifact writing, summary generation, evidence indexing
- `lab/chrome_manager.py`
  - isolated Chrome launch commands and safe profile operations
- `lab/config_store.py`
  - JSON-backed config/state persistence

## Adapters

Project-specific knowledge lives under:

- `lab/projects/`

The shipped example adapter is:

- `lab/projects/ncs_adapter.py`

The core engine is not supposed to know application-specific routes, selectors, or login flows directly.

## Data and configuration

Stable tool-owned configuration lives under:

- `data/app_config.json`
- `data/projects.json`
- `data/presets.json`
- `data/profiles.json`
- `data/scenarios.json`
- `data/selector_maps.json`

These files are intentionally tool-local and do not depend on product runtime code changes.

## Runtime layout

Runtime-only data lives under:

- `runtime/chrome-data/`
- `runtime/state/`
- `runtime/artifacts/`

These paths are operational output, not source-of-truth code. They are git-ignored except for `.gitkeep` placeholders.

## Trust model

The lab is designed to be honest rather than magical:

- clean automation is used where a stable route/selector/assertion exists
- manual-review is preserved where human judgment is still the truthful endpoint
- recovered startup issues are tracked explicitly
- reopened approximations are labeled as approximations
- preserved live sessions are labeled separately from reopened convenience windows

## Related docs

- [Adapter Contract](./ADAPTER_CONTRACT.md)
- [AI-Agent Adapter Generation Guide](./AI_ADAPTER_AUTHORING.md)
- [Usage Guide](./USAGE.md)

## Supported execution modes

- `manual`
  - operator-driven only
- `assisted`
  - mixed operator + tool guidance / partial automation
- `automated`
  - scripted steps through the automation engine, with explicit manual checkpoints when needed

## Repository shape

This repo-grade layout is intended to stay understandable:

- root docs explain what the tool is and how to start
- `lab/` contains the implementation
- `docs/` contains deep-dive technical guidance
- `examples/` contains curated adapter/scenario examples
- `tests/` contains lightweight reliability coverage
