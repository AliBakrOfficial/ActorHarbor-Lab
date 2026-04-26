# ActorHarbor Usage Guide

This guide is written for a new external engineer who wants to answer quickly:

- what is ActorHarbor
- how do I launch it
- how do I run a scenario
- how do I read the outputs
- how do I add an adapter
- how do I use AI to help generate an adapter

## Installation

Minimal local setup:

```powershell
cd tools\ActorHarbor-Lab
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-playwright.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

## Launch the UI

```powershell
cd tools\ActorHarbor-Lab
.\run-local-saas-lab.bat
```

Or:

```powershell
python run_lab.py
```

Or:

```powershell
python -m lab
```

Or with the package entry point after installation:

```powershell
actorharbor
```

## Run a scenario from CLI

```powershell
cd tools\ActorHarbor-Lab
.\.venv\Scripts\python.exe .\run_scenario.py admin-operations --mode automated --launch-mode browser
```

## Main workflow

1. Configure Chrome path and base URL
2. Choose the current adapter/project
3. Review presets and profiles
4. Choose a scenario
5. Pick run mode
6. Pick presentation mode
7. Decide whether to keep windows open
8. Run and inspect artifacts

For a tab-by-tab walkthrough, see [User Guide](./USER_GUIDE.md).

## Add or adapt a project

Start here:

- [Adapter Contract](./ADAPTER_CONTRACT.md)
- [AI-Agent Adapter Generation Guide](./AI_ADAPTER_AUTHORING.md)
- [NCS Example Adapter](../examples/ncs/README.md)

## Manual vs assisted vs automated

- `manual`
  - the tool launches routes and gives guidance only
- `assisted`
  - mixed operator + automation behavior
- `automated`
  - scripted steps where the adapter provides stable signals

## Keep-open

When keep-open is enabled:

- the UI prefers preserving live Playwright-backed sessions
- if true preservation is not possible in a given execution mode, the tool labels the fallback honestly

## Reading run outputs

Each run produces:

- `summary.json`
- `summary.md`
- `step-log.json`
- `evidence-index.json`
- screenshots

Use them in this order for fast review:

1. `summary.md`
2. `evidence-index.json`
3. key screenshots
4. `step-log.json`

## Common commands

Run tests:

```powershell
cd tools\ActorHarbor-Lab
python -m unittest discover -s tests
```

Compile-check key modules:

```powershell
cd tools\ActorHarbor-Lab
python -m py_compile .\lab\app.py .\lab\scenario_runner.py .\lab\run_history.py .\lab\automation\engine.py
```
