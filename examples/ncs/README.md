# NCS Adapter Example For ActorHarbor

This folder is a curated example of how one project is expressed through the adapter model.

It is not the core identity of the tool.

It demonstrates:

- one shipped adapter (`ncs`)
- one scenario definition shape
- how actor presets, routes, and selector-driven automation fit together

It also shows how an AI agent or adapter author can:

- map roles into presets
- translate route knowledge into scenario steps
- identify where manual-review is still the honest boundary

## Example files

- `scenario-example.json`
  - simplified example scenario based on the shipped NCS flows

## Where the real adapter lives

- `lab/projects/ncs_adapter.py`
- `data/scenarios.json`
- `data/presets.json`
- `data/selector_maps.json`

## What this example is meant to show

- how participants map to presets
- how steps are ordered
- where assertions and settle hints belong
- where manual-review remains appropriate
