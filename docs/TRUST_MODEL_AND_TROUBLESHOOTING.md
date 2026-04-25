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

Read:

- `inspection_state`
- `auth_state`
- `auth_label`

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

## Practical debugging sequence

1. Read `summary.md`
2. Open `evidence-index.json`
3. Check the final actor screenshots
4. Check failure points in `step-log.json`
5. Re-run in `browser` mode with keep-open if needed
