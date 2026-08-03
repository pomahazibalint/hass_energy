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
- [ ] Repository structure
- [ ] Generator framework
- [ ] Configuration model
- [ ] Documentation
- [ ] Example configuration
- [ ] Utility meters
- [ ] Pricing
- [ ] Device costs
- [ ] House totals
- [ ] Diagnostics
- [ ] Projections
- [ ] Executive dashboard
- [ ] Device dashboard
- [ ] Solar dashboard
- [ ] Diagnostics dashboard
- [ ] Tests
- [ ] GitHub Actions
- [ ] Release process

## Ideas backlog
- Tariff plugins
- Battery support
- Dynamic pricing
- Hourly solar-aware attribution
- EV analytics

This document is intended to be updated over multiple development sessions.
