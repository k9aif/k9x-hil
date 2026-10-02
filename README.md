# k9x-hil

Kafka-native human-in-the-loop case management for K9-AIF applications:
Project → Application → Queue (a Kafka topic) → Task. Applications publish a
task to their queue's topic and wait for the decision on the reply topic.

## Two instances, one image

`HIL_PROFILE` decides what an instance is (`backend/profile.py`).

| | public (default) | internal |
|---|---|---|
| Where | hil.k9x.ai (`ubuntu/build-run.sh`, :8086) | LAN only (`ubuntu_internal/build-run.sh`, :8096), never tunnelled |
| Data | demo projects, sample tasks, demo/admin logins on the sign-in page | real queues (incl. K9X Sentinel's Security tasks), one admin, no demo data |
| Sees traffic | yes: consumes the registered topics under its own consumer group | yes, under its own group |
| Decides | **no one, admin included**: `POST /api/tasks/{id}/action` returns 403 | yes |
| Publishes to Kafka | **never**: no replies, no TTL expiry, no dead-letter queue | replies, TTL expiry, DLQ |

Both instances receive every task message on the topics they register, but
only the internal one ever answers, so a public copy can never resume a
waiting application. After a decision the two differ: the public copy stays
open (it never hears the decision); the internal one shows the outcome.

Queues are registered in `backend/seed.py` (`seed_catalog`); the internal
instance registers the same system queues as the public one, plus the
internal-only ones. Sentinel's queue is internal-only.

Internal setup: copy `.env` to `.env.internal` and set the keys in
`.env.internal.example` (its own `POSTGRES_SCHEMA`, `HIL_CONSUMER_GROUP` and
`JWT_SECRET_KEY`); the script refuses to start if they're shared with public.
`HIL_ADMIN_PASSWORD` (re)sets the internal admin's password on every start.

Tests: `pytest -q tests`.
