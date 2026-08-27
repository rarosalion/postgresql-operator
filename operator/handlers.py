import base64
import os

import kopf
import psycopg2
import psycopg2.extensions
import psycopg2.sql
from kubernetes import client, config

DB_HOST = os.environ["DB_HOST"]
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
ADMIN_USER = os.environ["DB_ADMIN_USER"]
ADMIN_PASSWORD = os.environ["DB_ADMIN_PASSWORD"]


@kopf.on.startup()
def startup(**_):
    config.load_incluster_config()


def _admin_connection():
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=ADMIN_USER,
        password=ADMIN_PASSWORD,
        dbname="postgres",
    )
    conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
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

    with _admin_connection() as conn:
        with conn.cursor() as cur:
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

            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,))
            if not cur.fetchone():
                cur.execute(
                    psycopg2.sql.SQL("CREATE DATABASE {} OWNER {}").format(
                        psycopg2.sql.Identifier(database),
                        psycopg2.sql.Identifier(username),
                    )
                )
                logger.info(f"Created database {database!r}")

    patch.status["ready"] = True
    patch.status["message"] = "Role and database present"


# Deliberately no @kopf.on.delete handler - deleting the CR must never drop the database.
