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
- validation-invalid reasons when present
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
- state artifact path when present
- captured observations for state-driven steps

### `evidence-index.json`

Quick index for:

- best evidence
- actor final states
- validation-invalid reasons
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
- `validation-invalid`
  - the run did not reach a trustworthy authenticated/runtime surface, so product pass/fail judgment would be misleading

## Auth/session evidence hints

When a run is `validation-invalid`, check state artifacts for:

- `validation_invalid_reasons`
- `auth_surface`
- `staff_user_hint_present`
- `staff_auth_mode_hint_present`
- `patient_session_hint_present`
- `cookie_names`
- `session_cookie_names`
- recent `/sanctum/`, auth, and `/patient/session/` request events

Important:

- presence of `XSRF-TOKEN` or the session cookie name does **not** automatically prove authenticated shell success
- it only proves the browser context is carrying cookie material
- if cookies exist but `staff_user_hint_present` is false, the browser-session request path likely never committed authenticated frontend state
- protected-route truth still depends on the runtime surface leaving login/session-expired states cleanly
- if `validation_invalid_reasons` includes `hidden-tab-evidence-unreliable`, do not treat headless hidden/visible results as clean product evidence
- if `validation_invalid_reasons` includes `stale-queue-contamination`, do not treat cleanup badge residue as fresh lifecycle proof until the run shows a trustworthy pre-call baseline and a return to it

## Hidden-visible manual sign-off

For ER-5 closure, hidden-visible should be reviewed in browser mode, not headless mode.

Minimum manual evidence:

1. Open the nurse performance route in one tab and the nurse calls route in another tab for the same actor session.
2. Keep the performance tab in the background.
3. Trigger the patient call and let the helper actor accept it while the performance tab stays backgrounded.
4. Capture:
   - the visible calls tab while the performance tab is backgrounded
   - the performance tab immediately after returning to it
5. Pass only if:
   - no ghost lifecycle CTA remains after returning
   - no cleanup badge growth remains beyond the pre-call baseline
   - the background/foreground sequence is visible in the screenshots or operator notes

ER-5 closure note:

- automated closure evidence now covers:
  - outside-calls
  - inside-calls
  - same-user-two-tabs
  - supervisor control paths
- hidden-visible remains intentionally manual-sign-off evidence
