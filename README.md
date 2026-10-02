# k9x-hil

Kafka-native human-in-the-loop case management for K9-AIF applications:
Project → Application → Queue (a Kafka topic) → Task. Applications publish a
task to their queue's topic and wait for the decision on the reply topic.

## Two instances, one image

`HIL_PROFILE` decides what an instance is (`backend/profile.py`). They
register disjoint topics, so a task only ever lands in one of them.

| | public (default) | internal |
|---|---|---|
| Where | hil.k9x.ai (`ubuntu/build-run.sh`, :8086) | LAN only (`ubuntu_internal/build-run.sh`, :8096), never tunnelled |
| For | visitors | K9-AIF Framework Administrators only (shown in its header) |
| Queues | the example applications: EOC, DAS, Continuum, Process Studio AP | K9X Sentinel's Security tasks |
| Logins | demo/admin, shown on the sign-in page | one admin (`HIL_ADMIN_PASSWORD`), nothing shown |
| Actions | admin, manager (demo) or assignee; harmless: no example application consumes the replies | the framework admin |

Internal setup: copy `.env` to `.env.internal` and set the keys in
`.env.internal.example` (its own `POSTGRES_SCHEMA`, `HIL_CONSUMER_GROUP` and
`JWT_SECRET_KEY`); the script refuses to start if they're shared with public.
`HIL_ADMIN_PASSWORD` (re)sets the internal admin's password on every start.

Tests: `pytest -q tests`.
