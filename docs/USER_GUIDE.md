# ActorHarbor User Guide

ActorHarbor is built as an operator console. The normal journey is:

1. create or select a profile
2. choose a scenario
3. run the scenario
4. inspect the result and artifacts

## Main tabs

### Profiles

Use this tab to:

- review available actor profiles
- open a profile in browser or app mode
- clone from a preset
- edit profile metadata
- reset or delete a profile safely

This tab is where you manage the actor identity that a scenario will use.

### Scenarios

Use this tab to:

- browse scenario definitions
- understand how many actors participate
- see which run modes are supported
- send the selected scenario to the runner

### Scenario Runner

This is the main execution console.

Use it to:

- choose `manual`, `assisted`, or `automated`
- choose presentation mode when supported
- decide whether to reset profiles before the run
- decide whether to keep windows open after completion
- watch live status, current actor, current URL, and logs

The right side is the live run area:

- step-by-step status
- current actor
- current page or URL when available
- best evidence path
- final scenario status

### Active Sessions

This tab helps you understand what is currently open or preserved.

Use it to inspect:

- live preserved sessions
- reopened approximations when true preservation is not possible
- actor/session identity
- whether auth was preserved

### Artifacts / Run History

This is where you review completed runs.

You can:

- inspect run history
- open artifact folders
- open summaries
- understand final statuses
- manage history safely without deleting outside the lab-owned runtime paths

### Project Adapter

This tab exposes the active adapter context.

Conceptually, the adapter is the project-specific mapping layer that defines:

- routes
- login rules
- selectors
- scenario structure
- settle hints
- evidence hints

### Settings

Use this tab to configure:

- base URL
- Chrome path
- launch defaults
- artifact behavior
- keep-open defaults

## Run modes

### Automated

The engine executes scripted steps where the adapter provides enough stable signals.

### Assisted

The tool mixes automation with operator guidance. This is useful when some transitions are stable but others still need a human in the loop.

### Manual

The tool launches and guides, but does not pretend the scenario is automated.

## Keep-open

When enabled, ActorHarbor tries to preserve the real live browser state after the run whenever practical.

The tool is careful about wording:

- `live preserved` means the actual live session remained inspectable
- `reopened approximation` means the run could not preserve the original live page and reopened a convenience view instead

## What artifacts contain

Each run can produce:

- `summary.json`
- `summary.md`
- `step-log.json`
- `evidence-index.json`
- screenshots

Recommended review order:

1. `summary.md`
2. `evidence-index.json`
3. key screenshots
4. `step-log.json`

## How to read scenario results

- `passed`
  - the intended end-state was reached without unresolved execution issues
- `passed-with-recovery`
  - the scenario recovered from a bounded issue and still reached the intended end-state
- `manual-review`
  - the scenario intentionally ended at a human checkpoint
- `failed`
  - the intended end-state was not reached or a meaningful failure remained unresolved

## Project adapters and AI-assisted adapter generation

ActorHarbor is adapter-driven, not hardcoded to one application.

An adapter supplies the project-specific layer:

- routes and route intent
- login strategy
- protected-surface rules
- selectors
- scenarios
- settle hints
- manual-review boundaries

This is also the main AI-connectable path. A human or AI agent can inspect a target application, map those concepts, and generate or refine an adapter without changing the reusable core.

See:

- [Getting Started](./GETTING_STARTED.md)
- [Adapter Contract](./ADAPTER_CONTRACT.md)
- [AI-Agent Adapter Generation Guide](./AI_ADAPTER_AUTHORING.md)
