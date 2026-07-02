# Shipping Staircase via ASMP

[ASMP](https://agentservicemanifest.io) (Agent Service Management Protocol) is a
lightweight service registry for agent-operated infrastructure: one YAML
manifest per tool, a registry daemon, and a CLI (`asmp`) whose verbs include
`announce`, `register`, `list`, `get`, `find`, `health`, and `sync`.
Staircase ships to an ASMP registry the same way any tool does — this file is
the reproducible procedure.

## 1. The manifest

The manifest lives at the repo root: [`asmp.yaml`](../asmp.yaml). The fields
that matter:

- `name` / `version` / `description` — what shows up in `asmp list`.
- `capabilities.provides` — what other agents can discover it by
  (`asmp find expectations.management`).
- `infra.repo` + `infra.install` — where it lives and the exact commands a
  consumer runs to install it.
- `runtime.style: plugin`, `host_app: claude-code` — it runs inside Claude
  Code, not as a daemon.

## 2. Announce it

`asmp` runs on the registry host (default install `~/.local/bin/asmp`,
registry daemon on `localhost:7700`). From a machine with SSH access to that
host:

```sh
scp asmp.yaml <asmp-host>:/tmp/staircase.asmp.yaml
ssh <asmp-host> '~/.local/bin/asmp announce /tmp/staircase.asmp.yaml'
# → Announced staircase (generation 1)
```

`announce` performs the handshake registration (the entry records
`sync: announce`); plain `register` also works but skips the handshake.

## 3. Verify

```sh
ssh <asmp-host> '~/.local/bin/asmp get staircase && ~/.local/bin/asmp list | grep staircase'
```

`get` returns the full entry (repo, install commands, status, generation,
last_seen); the entry persists as `~/.asmp/services/staircase.asmp.yaml` on
the registry host, which is git-tracked.

## 4. Bump a version

Edit `version:` in `asmp.yaml` and re-run `asmp announce` — the registry
increments `generation` and stamps a fresh `last_seen`. That's the whole
release ritual: tag the repo, bump the manifest, announce.

## Notes

- The registry is host-local by default. ASMP has federation surface
  (`asmp sync`, `asmp scan`) for propagating entries between hosts; whether
  to federate is a registry-owner decision, not part of shipping a tool.
- Nothing in this procedure sends repository content anywhere — only the
  manifest metadata is registered.
