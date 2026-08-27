# postgresql-operator

Kubernetes operator that provisions Postgres roles/databases on an external Postgres server from
`PostgresDatabase` custom resources, instead of managing them by hand from outside the cluster.

## Why

Apps that need a Postgres database used to get one via an ansible playbook reading a Bitwarden
secret, with the same password then duplicated by hand into whatever secret store the consuming
Helm chart used (Vault). That duplication is exactly what caused real outages - a password never
copied over, or copied wrong. This operator makes the app's own chart the single source of truth:
it already has its own password (from Vault, same as always); the chart just also creates a small
`PostgresDatabase` resource pointing at that same Secret, and the operator does the rest.

## How it works

- A `PostgresDatabase` CR lives in the *same namespace* as the app that needs it, and references a
  Secret (also in that namespace) holding the role's password - the app's own existing Vault-sourced
  secret, not a new one.
- The operator watches for these CRs cluster-wide, but only ever reads Secrets by exact name (no
  list/watch on secrets) - it can't enumerate what else exists in a namespace.
- It connects to the target Postgres server using an admin credential that lives *only* in the
  operator's own namespace (`postgresql-operator` by default) and is never mirrored anywhere.
- `CREATE ROLE`/`CREATE DATABASE` are idempotent (checks `pg_roles`/`pg_database` first).
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
