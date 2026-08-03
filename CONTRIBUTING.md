# Contributing

## Principles
- Use Conventional Commits for meaningful changes.
- Keep changes small and reviewable.
- Treat generated YAML as an artifact, not source.
- Avoid handwritten repetition; add inventory data or generator logic instead.
- Keep comments focused on intent, constraints, and rationale.
- Do not use project-stage wording such as phases or waves in code or comments.

## Definition of done
A user-visible change is complete when:
- implementation is in place,
- tests are added or updated where practical,
- documentation is updated,
- generated output is refreshed when needed,
- and the repository remains in a usable state.

## Workflow
1. Update the configuration model or generator.
2. Regenerate the Home Assistant YAML output.
3. Run the test suite.
4. Commit using a Conventional Commit message.

## Commit message examples
- `feat(generator): add utility meter generation`
- `fix(pricing): handle settlement threshold edge case`
- `docs(plan): clarify billing model`
- `test(models): cover device inventory validation`
- `chore: regenerate packages`
