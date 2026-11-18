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
| Queues | the example applications: EOC, DAS, Continuum, Process Studio AP, OpenAI Demo Application (openai.k9x.ai invoice approvals) | K9X Sentinel's Security tasks |
| Logins | demo/admin, shown on the sign-in page | one admin (`HIL_ADMIN_PASSWORD`), nothing shown |
| Actions | admin, manager (demo) or assignee; harmless: no example application consumes the replies | the framework admin |

Internal setup: copy `.env` to `.env.internal` and set the keys in
`.env.internal.example` (its own `POSTGRES_SCHEMA`, `HIL_CONSUMER_GROUP` and
`JWT_SECRET_KEY`); the script refuses to start if they're shared with public.
`HIL_ADMIN_PASSWORD` (re)sets the internal admin's password on every start.

## The task contract: k9x.hil.task/v1 (1.6.0)

K9X HIL owns the structure of a task. A producer creates one by publishing a JSON message on a queue's topic that
conforms to the contract. The contract is served at `GET /api/contract/task` (JSON Schema) and published in this
repository as `contract/k9x.hil.task.v1.schema.json`. HIL enforces the same schema.

| Field | Meaning |
|---|---|
| `contract` | `"k9x.hil.task/v1"` |
| `task_type` | what kind of task, for example `invoice-approval`, `das-gate`, `security-finding` |
| `title`, `description` | what the reviewer is asked to decide |
| `correlation_id`, `reply_to` | the producer's id for this decision, and the topic the decision goes back on |
| `source_orchestrator`, `source_topic` | who asked |
| `priority` | `low`, `medium`, `high` or `critical` |
| `required_role`, `decision_authority` | the lowest HIL role allowed to decide, and who decides as the producer names it |
| `require_comment` | approval needs a written justification |
| `ttl_hours`, `ttl_action` | the deadline, and what happens after it (`reject`, `expire` or `escalate`) |
| `pii`, `pii_fields` | personal data in the task |
| `jira_ticket` | a linked ticket |
| `payload` | what the reviewer reads; its fields depend on `task_type` |
| `artifacts` | any number of `{uri, title, media_type, role, pii}`: `s3://bucket/key` (HIL fetches it from S3/MinIO) or `https://` links; `role` is `primary` (the document the decision is about) or `supporting` |

A message that names the contract and does not conform goes to `<topic>.dlq` with the reasons, and no task is
created. A message without `contract` (producers written before 1.6.0) is converted and accepted as before: plain-string
artifacts become artifact objects, unknown fields are dropped, and gaps are logged.

Every task is shown in one standard view: the same sections and fields for every producer, with "none" where a value
is absent. Each `s3://` artifact can be previewed or opened: a PDF opens in the browser's viewer, an image inline,
text as text, anything else as a download. Tests: `tests/test_task_contract.py`.

## API key for a server-to-server caller (1.5.0)

A backend that shows and decides tasks on behalf of its own users (the openai.k9x.ai demo's HIL pane) can send
`X-API-Key` instead of a sign-in token. It must match `HIL_API_KEY` and acts as `HIL_API_KEY_USER`: that user's
role still governs what may be decided, and decisions are recorded under that user. Keep the key on the
server; never send it to a browser. Empty `HIL_API_KEY` turns it off. Tests: `tests/test_api_key.py`.

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
each queue's Kafka topic and deadline (`ttl_hours`, `ttl_action`), and optionally the
minimum role that may decide its tasks (`required_role`: worker, manager or admin). The instance's
admin can change the branding later through `PUT /api/branding`.

**Who may decide (1.3.0).** A task message may name `required_role` (else the queue's)
and `decision_authority` (a label, e.g. "Milestone Decision Authority"). Approving or
rejecting needs that role or above, otherwise `403`; claiming and starting need none.
The decider recorded with the decision, and sent in the reply (`actor`, `actor_role`,
`decision_authority`), is the signed-in user, never a name sent by the client.

**Justification required (1.4.0).** A producer may mark a task `require_comment: true` (the
K9X Continuum does, for an SBB whose re-run inspection has findings or could not be verified).
Approving it then needs a non-empty comment, otherwise `422`; the comment travels in the reply.

**Intake never loses a task (1.4.1).** The consumer commits a topic offset only after its
message is stored as a task, skipped as a duplicate (`correlation_id`), or dead-lettered to
`<topic>.dlq`. If the database or the dead-letter publish fails, the offset stays uncommitted and
the consumer reconnects and receives the message again; a message the database itself rejects, or
one on a topic with no queue, is dead-lettered so it cannot block the queue.

Tests: `pytest -q tests`.
