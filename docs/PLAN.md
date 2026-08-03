# Home Assistant Energy Accounting - Project Plan

## Vision
Build a generator-driven Home Assistant energy accounting system with Hungarian tariff support and reusable architecture.

## Current goals
- Repository structure
- Generator framework
- Documentation
- Example configuration

## Configuration model
- Device inventory model
- Billing configuration
- Validation

## YAML generation
- Utility meters
- Pricing
- Device costs
- House totals
- Diagnostics
- Projections

## Dashboard output
- Executive dashboard
- Device dashboard
- Solar dashboard
- Diagnostics dashboard

## Quality and release
- Tests
- GitHub Actions
- Release process

## Ideas backlog
- Tariff plugins
- Battery support
- Dynamic pricing
- Hourly solar-aware attribution
- EV analytics

## Project principles
- No duplicated logic; repetitive YAML is generated, not handwritten.
- Conventional Commits are required for meaningful changes.
- Tests are required for new functionality and bug fixes where practical.
- Generated files are artifacts and must not be edited manually.
- Comments explain intent and constraints, not mechanics.
- No references to phases, waves, or similar project-stage language in code or comments.
- No temporary TODO comments in production code; future work belongs in this plan or in GitHub issues.
- The source of truth is the configuration model and generator, not the generated YAML.
- Deterministic generation is required: identical inputs must produce identical outputs.
- Every architectural decision should be discoverable from the repository itself.

This document is intended to be updated over multiple development sessions.
