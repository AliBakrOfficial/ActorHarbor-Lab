# ActorHarbor Getting Started

This is the fastest path for a new engineer who wants to launch ActorHarbor and understand the first useful workflow.

## 1. Install dependencies

```powershell
cd tools\ActorHarbor-Lab
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-playwright.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

## 2. Launch the desktop app

Use the default Windows launcher:

```powershell
cd tools\ActorHarbor-Lab
.\run-local-saas-lab.bat
```

You can also launch with:

```powershell
python run_lab.py
```

## 3. Confirm the basic setup

In the app:

1. Open `Settings`
2. Confirm the `Base URL`
3. Confirm or auto-detect the Chrome path
4. Review the default launch mode
5. Save settings if needed

## 4. Follow the normal user journey

The usual workflow is:

1. create or select a profile
2. choose a scenario
3. send the scenario to `Scenario Runner`
4. pick a run mode
5. run the scenario
6. inspect artifacts and run history

## 5. Know the result meanings

ActorHarbor uses truthful result states:

- `passed`
- `passed-with-recovery`
- `manual-review`
- `failed`
- `validation-invalid`

That means a scenario can intentionally end in manual review if the last checkpoint still requires human judgment, and it can end in `validation-invalid` when the authenticated/runtime surface was not trustworthy enough to judge the product honestly.

## 6. Know where to go next

- UI walkthrough: [User Guide](./USER_GUIDE.md)
- command usage: [Usage Guide](./USAGE.md)
- evidence structure: [Artifacts And Evidence](./ARTIFACTS_AND_EVIDENCE.md)
- adapter model: [Adapter Contract](./ADAPTER_CONTRACT.md)
- AI-assisted adapter authoring: [AI-Agent Adapter Generation Guide](./AI_ADAPTER_AUTHORING.md)
