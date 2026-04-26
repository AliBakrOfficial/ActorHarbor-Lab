# ActorHarbor Development Guide

Maintainer identity for the public repository:

- `AliBakrOfficial`

## Local development

```powershell
cd tools\ActorHarbor-Lab
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-playwright.txt
```

## Run tests

```powershell
cd tools\ActorHarbor-Lab
python -m unittest discover -s tests
```

## Validate key modules compile

```powershell
cd tools\ActorHarbor-Lab
python -m py_compile .\lab\app.py .\lab\scenario_runner.py .\lab\run_history.py .\lab\automation\engine.py
```

## Change discipline

When editing the core:

- keep app-specific behavior in adapters
- avoid hardcoding selectors in the generic engine
- prefer explicit status/resolution metadata over implicit interpretation
- keep artifacts and runtime state inside the lab folder only

## Contribution expectations

Good changes typically include:

- clear docs when behavior changes
- tests for status/output/path handling
- honest handling of manual-review vs automation
- no hidden coupling to a product runtime

## Public-release note

ActorHarbor is documented as a public-facing tool. Keep future wording:

- tool-first
- adapter-driven
- technically specific
- honest about manual-review and limitations

## Before publishing or handing off

Verify:

- docs still point to correct paths
- `.gitignore` protects runtime noise
- tests pass
- at least one real scenario still runs in a configured local environment
- screenshot placeholders and `docs/images/` remain public-ready
