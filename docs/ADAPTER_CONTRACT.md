# ActorHarbor Adapter Contract

An adapter maps a specific application into the generic ActorHarbor core.

The adapter contract is intentionally practical rather than abstract-for-its-own-sake.

Related docs:

- [Adapter Model](./ADAPTER_MODEL.md)
- [AI-Agent Adapter Generation Guide](./AI_ADAPTER_AUTHORING.md)

## What the core expects

An adapter must provide enough project-specific knowledge for the core to:

- describe actors and presets
- build scenarios
- detect login/auth state
- navigate to intended surfaces
- locate stable UI selectors
- decide which steps are automated vs manual-review
- capture meaningful evidence

## Required adapter surfaces

Today the base contract in code is represented by:

- `lab/projects/base_adapter.py`

The minimum adapter needs to provide:

- `project_id`
- display `name`
- short `description`
- default presets
- default scenarios
- selector map
- seed/reference guidance lines

## Practical adapter responsibilities

### 1. Actor presets

An adapter should define reusable presets with fields such as:

- `id`
- `name`
- `kind`
  - patient / staff / platform / custom
- `role`
- `route`
- `base_route`
- `landing_route`
- `launch_mode`
- `login_email`
- `login_password`
- `qr_token`
- `tags`
- `notes`

### 2. Scenario definitions

Each scenario should define:

- participants
- actor-to-preset mapping
- ordered steps
- step mode
  - `manual`
  - `assisted`
  - `automated`
- route intent
- assertion intent
- guidance text
- screenshot hints
- settle hints
- post-login route hints where relevant

### 3. Selector map

Selectors belong to the adapter, not the generic core.

Keep them grouped by surface, for example:

- `staff_login`
- `patient_scan`
- `patient_services`
- `reports`

### 4. Auth detection hints

An adapter should make it possible to distinguish:

- login required
- already authenticated
- protected route reached
- redirect back to login

This is usually expressed through:

- login selectors
- protected route assertions
- post-login route hints
- stable route-specific selectors or text

### 5. Evidence hints

An adapter should identify what “meaningful ready state” looks like:

- selector visible
- URL contains
- body contains
- wait-for text
- settle hints for noisy/hydrating pages

## Recommended scenario step fields

The current runner understands step fields such as:

- `id`
- `title`
- `actor_id`
- `mode`
- `action`
- `guidance`
- `route`
- `selector`
- `selector_key`
- `wait_for_selector`
- `wait_for_selector_key`
- `wait_for_text`
- `assertion`
- `screenshot`
- `settle_ms`
- `post_login_route`

Not every project will need every field on every step.

## What should stay out of the core

The core should not be hardcoded with:

- product-specific route names
- product-specific role names
- product-specific selectors
- DOM assumptions for one app only
- app-specific manual-review wording

That all belongs in the adapter layer.

## Quality bar for an adapter

A good adapter:

- does not fake automation coverage
- prefers stable route/selector/end-state signals
- uses manual-review checkpoints honestly
- produces screenshots that demonstrate real state
- is understandable by another engineer without tribal knowledge

## Example adapter

See:

- `lab/projects/ncs_adapter.py`
- `examples/ncs/README.md`
- `examples/ncs/scenario-example.json`
