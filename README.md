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
