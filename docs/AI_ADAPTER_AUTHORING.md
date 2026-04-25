# AI-Agent Adapter Generation Guide For ActorHarbor

This guide explains how a human or AI coding agent should generate a new project adapter safely.

The goal is not “fully automatic magic”.

The goal is:

- inspect a target project
- map it into the adapter contract
- keep automation honest
- validate the result with evidence

Related docs:

- [Adapter Contract](./ADAPTER_CONTRACT.md)
- [Usage Guide](./USAGE.md)

## 1. Start with boundaries

Before generating an adapter:

- confirm the lab remains standalone
- do not modify the target product runtime just to make the adapter easier
- keep all project-specific knowledge inside the adapter/config layer

## 2. Inspect the target app

Gather the minimum real information needed:

- routes and route groups
- roles / actor types
- login surfaces
- protected surfaces after login
- any token/session entry flow
- stable selectors
- stable end-state signals
- major acceptance-worthy scenarios

Sources may include:

- frontend routes
- auth guards
- seeded demo users or tokens
- operator docs / SOPs
- screenshots or manual walkthroughs

## 3. Identify actor types

Define who the tool should simulate:

- patients / end users
- staff / operators
- supervisors
- admins
- platform users

For each actor, decide:

- which preset fields are needed
- whether login is credential-based, token-based, or not required
- what the intended landing/protected route is

## 4. Map the login/auth flow

The adapter should teach the runner how to tell the difference between:

- login form visible
- already authenticated on a protected surface
- redirected to login
- token/session already active

This should be explicit and adapter-driven.

Do not assume “login form must appear”.

## 5. Choose stable selectors

Prefer selectors that are:

- intentional
- stable
- semantically meaningful

Avoid fragile selectors when a better signal exists.

Prefer:

- form fields by type or reliable attributes
- stable button selectors
- route-level selectors
- visible text that is operationally meaningful

## 6. Choose stable end-state signals

Every automated step should end on a state that is actually verifiable.

Good signals:

- URL contains expected route
- a surface-specific selector becomes visible
- body text contains a seeded identifier or stable title

Weak signals:

- arbitrary timing only
- transient toast only
- assumptions without a visible end-state

## 7. Decide step honesty

For every step, decide one of:

- automated
- assisted
- manual-review

Use automated only when the end-state is stable enough.

Use manual-review when:

- realtime observation is still the truthful endpoint
- the page is visually inspectable but not stably assertable
- the flow is valuable but brittle to over-automate

## 8. Generate the adapter files

At minimum generate:

- adapter class
- presets
- scenarios
- selector map
- seed/reference notes

Also document:

- what was inferred
- what was observed directly
- which steps are manual-review on purpose

## 9. Validate with the lab

Run at least:

- one single-actor scenario
- one multi-actor scenario if the product needs it
- one manual-review scenario if full automation is not honest

Check:

- login/auth branching
- route reachability
- screenshot usefulness
- final status honesty
- artifact clarity

## 10. Red flags for AI-generated adapters

Reject or revisit the adapter if you see:

- every step marked automated with weak evidence
- login selectors that assume one exact DOM forever
- no manual-review points in flows that clearly need them
- final statuses that say pass while screenshots contradict that
- core code changed just to fit the adapter

## Worked approach

When asked to generate a new adapter, a good AI agent should:

1. Inspect the target project structure
2. Identify routes and auth flow
3. Identify 2-4 realistic actor presets
4. Define one stable scenario first
5. Add selectors and settle hints only where justified
6. Validate with a real run
7. Mark anything ambiguous as manual-review instead of pretending full automation

## Reference example

Use the shipped NCS adapter as a concrete example, not as a universal template:

- `lab/projects/ncs_adapter.py`
- `examples/ncs/README.md`
