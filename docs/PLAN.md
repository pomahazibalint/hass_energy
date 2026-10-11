# Home Assistant Energy Accounting - Project Plan

## Vision
Build a generator-driven Home Assistant energy accounting system with Hungarian tariff support and reusable architecture.

## Principles
- Conventional Commits for every commit.
- Tests are required for new functionality and bug fixes where practical.
- No duplicated logic; repetitive Home Assistant YAML is generated, not handwritten.
- Generated files are artifacts; the generator and configuration model are the source of truth.
- Comments explain intent and rationale, not mechanics.
- No project-management terminology such as phases or waves in code or comments.
- No temporary or TODO comments in production code; future work belongs here or in GitHub issues.
- Every generated file should make it clear that it is generated and should not be edited manually.
- Deterministic generation: identical inputs must produce identical outputs.
- The repository should be understandable on its own without relying on chat history.

## Milestones
- [x] Repository structure
- [x] Generator framework
- [x] Configuration model
- [x] Documentation
- [x] Example configuration
- [x] Utility meters
- [x] Pricing
- [x] Device costs
- [x] House totals
- [x] Diagnostics
- [x] Projections
- [ ] Executive dashboard
- [ ] Device dashboard
- [ ] Solar dashboard
- [ ] Diagnostics dashboard
- [x] Tests
- [x] GitHub Actions
- [ ] Release process

## Current state
The generator produces seven packages from a configuration: utility meters,
banded pricing, device costs, house totals, the settlement automations,
diagnostics and projections. Device settlement meters carry the price bands as
utility_meter tariffs, so settlement costs are exact rather than estimated at
the current rate.

Continuous integration guards determinism with `generate --check`, validates
the generated YAML against Home Assistant's own schemas with
`hass --script check_config`, and renders every generated template against a
Home Assistant instance. `examples/` holds a configuration with its generated
output committed beside it.

A Home Assistant integration records meter quantities and derives the
settlement from them, for the two things generated YAML cannot express: prices
that change inside a settlement period, and a period boundary set by a meter
reading rather than a date. It ships its own copy of the settlement engine, so
it installs by copying one directory and needs nothing at runtime.

Dashboards are the remaining feature work, and the entities they need now
exist: the executive view reads the projections, the diagnostics view reads the
problem entities.

The integration's own record of energy is its weak point: it needs its own
reset detection, glitch handling and correction action, and cannot apportion a
price backdated into the period. [RECORDER_BACKED_SETTLEMENT.md](RECORDER_BACKED_SETTLEMENT.md)
plans its replacement by the recorder's long-term statistics, with cost
delivered to the energy dashboard as hourly statistics, and the migration path.

## Ideas backlog
- Recorder-backed settlement, see docs/RECORDER_BACKED_SETTLEMENT.md
- Tariff plugins
- Battery support
- Dynamic pricing
- Hourly solar-aware attribution
- EV analytics

This document is intended to be updated over multiple development sessions.
