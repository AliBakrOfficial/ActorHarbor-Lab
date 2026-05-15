# ActorHarbor Trust Model And Troubleshooting

## Trust model

The lab is not trying to be universal magic.

It makes a few explicit promises:

- adapters own app-specific knowledge
- manual-review is preserved where automation would be dishonest
- recovered execution issues are tracked explicitly
- preserved live sessions are labeled differently from reopened approximations

## What this tool does not promise

- zero flake on every product and every browser build
- full E2E replacement for all human judgment
- correctness without a project adapter
- reliable automation if the product surface has no stable signals

## Common issues

### Browser startup fails early

Check:

- Chrome path is valid
- the profile is not already in use by another process
- Playwright browser install is present
- the actor profile is not being reset while still open

### Protected route reopens to login

This usually means:

- you are seeing a reopened approximation, not a preserved live session
- or auth was already lost before the run ended
- or the run never truly left the login shell and an older URL-style assertion would have been misleading

Read:

- `validation_invalid_reasons`
- `inspection_state`
- `auth_state`
- `auth_label`
- `auth_surface` in state artifacts
- `staff_user_hint_present`
- `staff_auth_mode_hint_present`
- `patient_session_hint_present`
- `cookie_names` and `session_cookie_names` in state artifacts
- recent `/sanctum/`, auth, and `/patient/session/` request events inside `network_events`

Strong signal:

- if session cookies exist but `ncs.staff.user` never appears, the browser session reached cookie material without the frontend shell committing authenticated staff state

### Scenario says manual-review

That is not a failure by itself.

It means:

- the scenario intentionally ended at a human checkpoint
- or the adapter chose honesty over brittle fake automation

### Scenario says failed even though some later screenshots look good

After P10.9 this should only happen when:

- the run did not actually recover to the intended state
- or the recovered state belonged to a different context than the failed actor path

Check:

- `recovery_overview`
- per-step `recovered`
- `recovered_by_step_id`

### Scenario says validation-invalid

That means the lab does not trust the authenticated/runtime surface enough to make an honest product judgment yet.

Typical causes:

- the actor stayed on `staff-login`
- the patient surface collapsed to `patient-session-expired`
- the browser context still had cookie material but never stabilized into the authenticated shell
- auth/network bootstrap requests failed before the protected route became real
- a login request or route transition was aborted before frontend auth hints were written
- headless visibility evidence was not trustworthy enough to support hidden/visible judgment

Common reason labels:

- `staff-auth-not-stabilized`
- `patient-session-collapsed`
- `hidden-tab-evidence-unreliable`
- `selector-evidence-not-trustworthy`
- `stale-queue-contamination`

Important:

- `hidden-tab-evidence-unreliable` is an environment limitation in Playwright headless, not honest product proof by itself
- `stale-queue-contamination` means the run still cannot prove a clean baseline-versus-cleanup delta for queue residue, so closure judgment should stop there instead of blaming product cleanup logic prematurely
- if a scenario depends on true background-tab behavior, prefer a browser-mode manual sign-off over headless automation claims

Current ER-5 truth:

- automated control-surface closure evidence is now clean enough to close ER-5
- background-tab hidden-visible behavior is still intentionally validated through manual browser-mode sign-off

## Practical debugging sequence

1. Read `summary.md`
2. Open `evidence-index.json`
3. Check the final actor screenshots
4. Check failure points in `step-log.json`
5. Re-run in `browser` mode with keep-open if needed
