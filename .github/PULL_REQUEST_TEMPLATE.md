<!--
Thanks for contributing to Airlock. Small, focused PRs get reviewed fastest.
-->

## What does this PR do?

<!-- One paragraph: the behavior change, and why it's needed. -->

## Containment impact

- [ ] This PR does **not** touch sandbox isolation, policy, or lifecycle code
- [ ] It does — threat-model note below

<!-- If checked: which of the four invariants (process isolation, secret hygiene,
     resource limits, lifecycle discipline) could this change affect, and why is it safe? -->

## Tests

- [ ] New/updated tests cover the behavior change
- [ ] Suite passes offline: `python -m pytest` (no Docker, no API keys needed)
- [ ] Bug fix includes a test that failed before the fix

## Screenshots / clips

<!-- For anything visible in the UI: before/after. Delete if not applicable. -->

## Checklist

- [ ] No new heavyweight dependencies (see CONTRIBUTING.md)
- [ ] Type hints on new public functions
- [ ] Docs updated (README / deploy docs / design doc) if behavior or setup changed
