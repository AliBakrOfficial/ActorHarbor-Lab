# ActorHarbor Artifacts And Evidence

ActorHarbor is designed to produce reviewable evidence, not only pass/fail flags.

## Per-run artifact bundle

Each run writes under:

- `runtime/artifacts/<timestamp>/<scenario-id>/`

Typical files:

- `summary.json`
- `summary.md`
- `step-log.json`
- `evidence-index.json`
- screenshots

## What each file is for

### `summary.json`

Machine-friendly full run record:

- final status
- actor sessions
- step outcomes
- recovery overview
- inspection metadata

### `summary.md`

Human-friendly review entry point:

- scenario metadata
- final status
- actor sessions
- best evidence
- failure notes
- manual-review points

### `step-log.json`

Structured step-by-step output:

- actor
- step id/title
- action
- status
- resolution
- reason
- current URL
- screenshot path

### `evidence-index.json`

Quick index for:

- best evidence
- actor final states
- manual-review points
- failure points

## Evidence policy

The lab prefers:

- one useful screenshot over many low-value screenshots
- final actor-state screenshots
- manual-review evidence when practical
- failure screenshots when exceptions occur
- labels that explain what matters

## Status meanings

- `passed`
  - scenario reached intended automated end-state cleanly
- `passed-with-recovery`
  - scenario recovered from an early startup/attach issue and still reached intended state
- `manual-review`
  - scenario intentionally ends at a human checkpoint
- `failed`
  - intended state was not reached
