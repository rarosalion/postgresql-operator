# postgresql-operator

Kubernetes operator (kopf-based) that provisions Postgres roles/databases on an external Postgres
server from `PostgresDatabase` custom resources. See [README.md](README.md) for the design
rationale.

## Layout

- `operator/handlers.py` - the entire operator. One `reconcile` handler for both create and update.
- `chart/` - the Helm chart. `chart/crds/` is installed automatically by `helm install`/`upgrade`
  and is *not* removed by `helm uninstall` (standard Helm CRD behavior).
- `examples/postgresdatabase.yaml` - shape of a `PostgresDatabase` request.
- `request-chart/` - a small, separately-versioned chart consuming apps use to request a database
  (see `README.md`'s "How it works"). Its own `templates/secret.yaml` (when not pointed at an
  `existingSecret`) creates a Secret with **both** a `username` and a `password` key - not just
  `password` - so it's directly usable by anything that wants a combined credential Secret (e.g. a
  chart with a `db.secret.{usernameKey,passwordKey}`-style external-database input), not only by
  the operator's own `passwordSecretRef`.
- `Dockerfile` - installs deps directly (not via `pyproject.toml`), so dependency versions are
  currently pinned in two places. Keep them in sync if you bump one.

## Local dev workflow

Run the operator directly against a real cluster without building a container:

```
export DB_HOST=... DB_PORT=5432 DB_ADMIN_USER=... DB_ADMIN_PASSWORD=...
kopf run --standalone operator/handlers.py
```

`startup()` falls back to `config.load_kube_config()` when not running in-cluster, so this picks up
whatever kubectl context is currently active.

To test the actual container + Helm chart path (recommended before considering a change done -
RBAC issues in particular only show up this way, not via raw `kopf run`):

```
docker build -t postgresql-operator:local-dev .
helm install postgresql-operator ./chart \
  --set image.repository=postgresql-operator --set image.tag=local-dev \
  --set dbAdmin.host=... --set dbAdmin.user=... --set dbAdmin.password=...
```

A local cluster (e.g. Docker Desktop's built-in Kubernetes) works well for this and shares its
image cache with `docker build`, so no registry push is needed.

## Known gotchas (learned the hard way)

- **Never use `with _admin_connection() as conn:`.** psycopg2's connection context manager wraps
  the block in transaction commit/rollback semantics *even with `autocommit = True`*, which breaks
  `CREATE DATABASE`/`DROP DATABASE` (they can't run inside a transaction block) with a confusing,
  deterministic `ActiveSqlTransaction` error. Use `contextlib.closing(_admin_connection())` instead
  - it only closes the connection, no transaction wrapping.
- **The `ClusterRole` needs `list`/`watch` on `CustomResourceDefinitions`.** kopf's cluster-wide
  resource discovery requires this. Without it, the operator logs repeated 403s in the background,
  eventually gives up, and silently stops watching for CR changes (only refreshing on pod restart).
  It still looks like it's "working" at first glance because the initial reconcile succeeds before
  the retries are exhausted.
- **`@kopf.on.create`/`@kopf.on.update` only fire on watch events**, not automatically on operator
  restart for objects that already exist. There's no `@kopf.on.resume` handler. When testing
  against a pre-existing CR after restarting the operator process, force a fresh event (delete the
  CR and recreate, or patch its `.spec`) rather than assuming a restart will re-trigger it.
- The missing `@kopf.on.delete` handler is deliberate, not an oversight - see the comment at the
  bottom of `handlers.py`. Never add one without discussing it first.
