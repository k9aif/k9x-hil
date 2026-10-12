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
| For | visitors | K9-AIF Framework Administrators only |
| Badge (`HIL_BADGE`) | none | `Internal` |
| Queues | the example applications: EOC, DAS, Continuum, Process Studio AP | K9X Sentinel's Security tasks |
| Logins | demo/admin, shown on the sign-in page | one admin (`HIL_ADMIN_PASSWORD`), nothing shown |
| Actions | admin, manager (demo) or assignee; harmless: no example application consumes the replies | the framework admin |

Internal setup: copy `.env` to `.env.internal` and set the keys in
`.env.internal.example` (its own `POSTGRES_SCHEMA`, `HIL_CONSUMER_GROUP` and
`JWT_SECRET_KEY`); the script refuses to start if they're shared with public.
`HIL_ADMIN_PASSWORD` (re)sets the internal admin's password on every start.

## Run your own, rebranded for your organisation

A third kind of instance, `HIL_PROFILE=instance`, is one HIL for one project or
organisation: its own name, colours, logo text and about line, its own projects,
applications and queues, and its own schema, Kafka consumer group, JWT secret and
port. Same image as hil.k9x.ai; no code changes.

```bash
git clone https://github.com/k9aif/k9x-hil && cd k9x-hil
cp instances/das.yaml instances/acme.yaml   # set id: acme, branding, projects/applications/queues
cp .env.sample .env.acme                    # your PostgreSQL, Kafka and object storage
cat .env.das.example >> .env.acme           # then set HIL_INSTANCE=acme, HIL_INSTANCE_PORT,
                                            # POSTGRES_SCHEMA, HIL_CONSUMER_GROUP, JWT_SECRET_KEY, admin
bash ubuntu_instance/build-run.sh all acme  # build the image, start container k9x-hil-acme
```

`instances/<name>.yaml` is the instance: `branding` (name, subtitle, accent,
logo_text, about), `demo_login`, and the projects → applications → queues with
each queue's Kafka topic and deadline (`ttl_hours`, `ttl_action`). The instance's
admin can change the branding later through `PUT /api/branding`.

Tests: `pytest -q tests`.
