import base64
import contextlib
import os

import kopf
import psycopg2
import psycopg2.sql
from kubernetes import client, config

DB_HOST = os.environ["DB_HOST"]
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
ADMIN_USER = os.environ["DB_ADMIN_USER"]
ADMIN_PASSWORD = os.environ["DB_ADMIN_PASSWORD"]


@kopf.on.startup()
def startup(**_):
    try:
        config.load_incluster_config()
    except config.ConfigException:
        # Not running in a Pod - fall back to the local kubeconfig, for running the operator
        # directly against a real cluster during development.
        config.load_kube_config()


def _admin_connection():
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=ADMIN_USER,
        password=ADMIN_PASSWORD,
        dbname="postgres",
    )
    conn.autocommit = True
    return conn


def _read_password(namespace: str, secret_ref: dict) -> str:
    v1 = client.CoreV1Api()
    secret = v1.read_namespaced_secret(secret_ref["name"], namespace)
    encoded = secret.data[secret_ref["key"]]
    return base64.b64decode(encoded).decode()


@kopf.on.create("db.rarosalion.github.io", "v1", "postgresdatabases")
@kopf.on.update("db.rarosalion.github.io", "v1", "postgresdatabases")
def reconcile(spec, namespace, patch, logger, **_):
    database = spec["databaseName"]
    username = spec["username"]
    password = _read_password(namespace, spec["passwordSecretRef"])

    # contextlib.closing, not `with conn:` - the latter wraps the block in a transaction for
    # commit/rollback purposes even with autocommit set, which breaks CREATE/DROP DATABASE
    # (they can't run inside a transaction block).
    with contextlib.closing(_admin_connection()) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (username,))
        if cur.fetchone():
            cur.execute(
                psycopg2.sql.SQL("ALTER ROLE {} WITH PASSWORD %s").format(
                    psycopg2.sql.Identifier(username)
                ),
                (password,),
            )
            logger.info(f"Role {username!r} already existed, password updated")
        else:
            cur.execute(
                psycopg2.sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD %s").format(
                    psycopg2.sql.Identifier(username)
                ),
                (password,),
            )
            logger.info(f"Created role {username!r}")

        # CREATEROLE grants admin on roles it creates, but not automatically the ability to
        # SET ROLE to them (PG16+) - which CREATE DATABASE ... OWNER needs, since assigning
        # ownership requires acting as that role. Idempotent - safe to run every reconcile.
        cur.execute(
            psycopg2.sql.SQL("GRANT {} TO CURRENT_USER WITH SET TRUE").format(
                psycopg2.sql.Identifier(username)
            )
        )

        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,))
        if not cur.fetchone():
            # Explicit ENCODING/TEMPLATE - the cluster's template1 default is SQL_ASCII, and a
            # bare CREATE DATABASE silently inherits that rather than UTF8.
            cur.execute(
                psycopg2.sql.SQL(
                    "CREATE DATABASE {} OWNER {} ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0"
                ).format(
                    psycopg2.sql.Identifier(database),
                    psycopg2.sql.Identifier(username),
                )
            )
            logger.info(f"Created database {database!r}")

    patch.status["ready"] = True
    patch.status["message"] = "Role and database present"


# Deliberately no @kopf.on.delete handler - deleting the CR must never drop the database.
