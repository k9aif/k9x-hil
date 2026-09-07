#!/usr/bin/env python3
"""k9x-hil — backing-service connectivity smoke test (Postgres, Kafka,
MinIO). Reads connection details from .env, same as the app itself.

Redis isn't checked — REDIS_HOST/PORT/PASSWORD exist in .env but the app
never actually imports redis anywhere (not in requirements.txt either),
so it's unused legacy config, not a real dependency.

Run directly, no test framework needed:

    python3 tests/db_test.py

Exits 0 if every configured service is reachable, non-zero otherwise.
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

results: list[tuple[str, bool, str]] = []


def check(name: str, fn) -> None:
    try:
        detail = fn()
        results.append((name, True, detail))
    except Exception as e:  # noqa: BLE001
        results.append((name, False, str(e)))


def check_postgres() -> str:
    import psycopg2

    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "k9x")
    user = os.environ.get("POSTGRES_USER", "postgres")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    schema = os.environ.get("POSTGRES_SCHEMA", "k9hil")

    conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname=db)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name = %s",
            (schema,),
        )
        if not cur.fetchone():
            raise RuntimeError(f"schema '{schema}' does not exist")
        tables = []
        for table in ("users", "projects", "applications", "queues", "tasks", "task_actions"):
            cur.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = %s AND table_name = %s",
                (schema, table),
            )
            if cur.fetchone()[0]:
                tables.append(table)
        return f"{host}:{port}/{db} — schema '{schema}', tables present: {tables}"
    finally:
        conn.close()


def check_kafka() -> str:
    from kafka import KafkaAdminClient

    broker = os.environ.get("KAFKA_BROKER", "localhost:9092")
    admin = KafkaAdminClient(bootstrap_servers=broker, client_id="k9x-hil-db-test")
    try:
        topics = admin.list_topics()
        return f"{broker} — {len(topics)} topics visible"
    finally:
        admin.close()


def check_minio() -> str:
    import boto3

    endpoint = os.environ.get("S3_ENDPOINT_URL", "http://localhost:9000")
    access_key = os.environ.get("AWS_ACCESS_KEY_ID", "")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
    s3 = boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=access_key,
                       aws_secret_access_key=secret_key)
    buckets = [b["Name"] for b in s3.list_buckets()["Buckets"]]
    return f"{endpoint} — buckets: {buckets}"


def main() -> int:
    check("Postgres", check_postgres)
    check("Kafka", check_kafka)
    check("MinIO", check_minio)

    ok = True
    for name, passed, detail in results:
        if passed:
            print(f"  PASS: {name} — {detail}")
        else:
            print(f"  FAIL: {name} — {detail}", file=sys.stderr)
            ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
