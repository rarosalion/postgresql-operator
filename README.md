# postgresql-operator

Kubernetes operator that provisions Postgres roles/databases on an external Postgres server from
`PostgresDatabase` custom resources, instead of managing them by hand from outside the cluster.

## Why

Apps deployed to Kubernetes often need a database to exist before they can start, but Postgres
itself usually lives outside the cluster's own reconciliation model - so provisioning that database
ends up as a manual step, or an external script/playbook run out-of-band from the actual app
deployment. That split invites drift: the app's Helm release and its database can easily end up
out of sync, especially once credentials are involved (a password generated in one place has to be
copied correctly into another).

This operator brings database provisioning into Kubernetes' own declarative model. The app's chart
already has its own database password as a Secret (however it manages secrets - Vault, External
Secrets, sealed-secrets, whatever); it just also creates a small `PostgresDatabase` resource
pointing at that same Secret, and the operator reconciles the actual role/database into existence -
no separate script, no second copy of the password to keep in sync.

## How it works

- A `PostgresDatabase` CR lives in the *same namespace* as the app that needs it, and references a
  Secret (also in that namespace) holding the role's password - the app's own existing secret, not
  a new one.
- The operator watches for these CRs cluster-wide, but only ever reads Secrets by exact name (no
  list/watch on secrets) - it can't enumerate what else exists in a namespace. A consequence of
  this is that the operator only reconciles on a change to the CR itself, not on a change to the
  Secret it points at - a password rotation that only touches the Secret produces no CR diff, so
  the role's password silently never gets updated. The `postgres-database-request` chart (see
  below) works around this for its own callers by stamping a `checksum/password` annotation on the
  CR, computed from the password value at render time, so a password change always produces a real
  CR diff too. A `PostgresDatabase` CR written by hand (not via that chart) needs the same trick,
  or a manual `kubectl annotate ... force-reconcile=$(date +%s) --overwrite` nudge after rotating
  the Secret.
- It connects to the target Postgres server using an admin credential that lives *only* in the
  operator's own namespace (`postgresql-operator` by default) and is never mirrored anywhere.
- `CREATE ROLE`/`CREATE DATABASE` are idempotent (checks `pg_roles`/`pg_database` first).
- Adopting a role that already exists (not created by the operator) needs a one-off grant from a superuser, because the operator only holds admin on roles it created: `GRANT <role> TO <operator user> WITH ADMIN OPTION, SET TRUE`. Without it the CR is marked not ready with that exact command in `status.message`, and the operator stops retrying.
- Deleting a `PostgresDatabase` CR does **not** drop the role or database - that's deliberate, not
  an oversight. There's no delete handler at all.

## Deploying

```
helm install postgresql-operator ./chart \
  --set dbAdmin.host=postgres.example.com \
  --set dbAdmin.user=postgres \
  --set dbAdmin.password=<admin password>
```

See `examples/postgresdatabase.yaml` for the shape of a request.
