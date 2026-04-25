# ActorHarbor

**ActorHarbor — AI-connectable simulation lab for browser workflows and acceptance testing**

ActorHarbor is a standalone multi-actor browser simulation and acceptance harness. It helps engineering teams run realistic browser workflows, preserve evidence, and mix automated execution with honest manual-review checkpoints through an adapter-driven model.

Maintained by `AliBakrOfficial`.

It is built for situations where a plain test runner is not enough:

- multiple actors need separate browser state
- login and protected-route behavior matter
- evidence and screenshots matter as much as pass/fail
- some steps are stable enough to automate while others still require human review

## Key capabilities

- isolated Chrome user-data-dir profiles
- multi-actor scenario runner
- manual, assisted, and automated modes
- Playwright-backed automation
- truthful keep-open / live inspection semantics
- auth-aware branching and protected-surface detection
- evidence bundles with screenshots, summaries, logs, and indexes
- adapter-driven project support

## Why ActorHarbor exists

Many real SaaS workflows are not single-page happy-path demos. They involve:

- role switching
- separate browser state
- protected routes
- redirect behavior
- acceptance flows that still need operator judgment at the end

ActorHarbor exists to make those workflows runnable, inspectable, and documentable without pretending every flow should be a brittle fully automated E2E script.

## Why ActorHarbor is different

- **Multi-actor by design**
  - separate patient, nurse, admin, supervisor, or platform windows can participate in one scenario
- **Real browser workflows**
  - isolated profiles and persistent contexts reflect real session behavior
- **Truthful hybrid automation**
  - automated where stable, manual-review where honesty matters
- **Evidence-driven output**
  - summaries, step logs, screenshots, actor final-state captures, and evidence indexes
- **Adapter architecture**
  - the core stays reusable while project knowledge lives in adapters
- **AI-connectable adapter path**
  - routes, login strategy, selectors, settle hints, scenarios, and manual-review boundaries can be authored systematically by humans or AI agents

## Architecture snapshot

```text
ActorHarbor-Lab/
|-- README.md
|-- LICENSE
|-- pyproject.toml
|-- run_lab.py
|-- run_scenario.py
|-- data/
|-- docs/
|-- examples/
|-- lab/
|   |-- app.py
|   |-- scenario_runner.py
|   |-- run_history.py
|   |-- automation/
|   `-- projects/
|-- runtime/
`-- tests/
```

Core responsibilities:

- browser/session orchestration
- scenario execution
- artifact generation
- operator UI
- truthful outcome aggregation

Adapter responsibilities:

- routes
- role presets
- login strategy
- protected-surface detection
- selectors
- settle/evidence hints
- scenario definitions

## Quick start

### Install

```powershell
cd tools\ActorHarbor-Lab
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-playwright.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

### Launch the UI

```powershell
python run_lab.py
```

Or:

```powershell
python -m lab
```

Or after installation:

```powershell
actorharbor
```

### Run one scenario from CLI

```powershell
.\.venv\Scripts\python.exe .\run_scenario.py admin-operations --mode automated --launch-mode browser
```

## Adapter model

ActorHarbor is intentionally adapter-driven.

An adapter can define:

- routes and route intent
- actor presets / roles
- login strategy
- auth detection rules
- selectors
- scenario definitions
- settle hints
- evidence hints
- manual-review boundaries

The shipped repository includes one concrete example adapter:

- `ncs`

That adapter is useful as a worked example, but the core project identity is tool-first, not NCS-first.

## AI-agent adapter authoring angle

ActorHarbor is designed to be **AI-connectable** in a concrete way:

- an AI agent can inspect a project
- identify routes and login/auth flow
- propose selectors and stable end-state signals
- map scenarios into adapter definitions
- keep unstable checkpoints marked as manual-review instead of faking full automation

This is documented explicitly in:

- [AI-Agent Adapter Generation Guide](./docs/AI_ADAPTER_AUTHORING.md)

## Outputs and evidence

Each run can produce:

- `summary.json`
- `summary.md`
- `step-log.json`
- `evidence-index.json`
- screenshots

Final statuses are honest:

- `passed`
- `passed-with-recovery`
- `manual-review`
- `failed`

## Screenshots / hero visuals

Recommended GitHub README visuals for launch:

- operator console screenshot
- one multi-actor scenario run summary
- one artifact bundle screenshot showing `summary.md` plus screenshots

The current repo keeps visuals out of source until curated public assets are chosen.

## Trust model and limitations

ActorHarbor does not claim to be universal magic.

- stable flows can be automated
- weak flows should remain manual-review
- adapters are the project-specific mapping layer
- evidence matters as much as final status
- protected-route/auth behavior must be labeled truthfully

See:

- [Artifacts And Evidence](./docs/ARTIFACTS_AND_EVIDENCE.md)
- [Trust Model And Troubleshooting](./docs/TRUST_MODEL_AND_TROUBLESHOOTING.md)

## Docs map

- [Architecture Overview](./docs/ARCHITECTURE.md)
- [Adapter Model](./docs/ADAPTER_MODEL.md)
- [Adapter Contract](./docs/ADAPTER_CONTRACT.md)
- [AI-Agent Adapter Generation Guide](./docs/AI_ADAPTER_AUTHORING.md)
- [Usage Guide](./docs/USAGE.md)
- [Artifacts And Evidence](./docs/ARTIFACTS_AND_EVIDENCE.md)
- [Trust Model And Troubleshooting](./docs/TRUST_MODEL_AND_TROUBLESHOOTING.md)
- [Development Guide](./docs/DEVELOPMENT.md)
- [NCS Example Adapter](./examples/ncs/README.md)
- [Public Launch Notes](./docs/GITHUB_RELEASE_PREP.md)

## Contributing / development

Primary public maintainer: `AliBakrOfficial`.

Run tests:

```powershell
python -m unittest discover -s tests
```

Compile-check core modules:

```powershell
python -m py_compile .\run_lab.py .\run_scenario.py .\lab\app.py .\lab\scenario_runner.py .\lab\run_history.py .\lab\automation\engine.py
```

## License

MIT. See [LICENSE](./LICENSE).
