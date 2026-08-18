# Deploying Yanai

This is a step-by-step runbook for taking Yanai from "runs on my laptop" to
a live HTTPS site: one VPS running Postgres (pgvector), the Go API, and the
built SvelteKit SPA behind Caddy, plus a GitHub Actions pipeline that
deploys on every push to `main`.

Steps marked **[HUMAN]** need a person — creating accounts, paying for
things, clicking through a provider's UI, pasting secrets into GitHub.
Every other step is a literal command a future Claude Code session (or you)
can run directly once it has SSH access to the server.

## Architecture

```
Browser ── HTTPS ──▶ Caddy ── /api/*, /healthz ──▶ api container ──▶ postgres container
                       │                                                (pgvector/pg16)
                       └── everything else ──▶ static SPA files (bind-mounted)
```

One VPS, three containers via Docker Compose. This matches the app's actual
constraints: voice-note audio lives on local disk (`STORAGE_DIR`), and the
background job worker runs in-process inside the API — both are
single-node by design, so a multi-instance PaaS would buy nothing here. A
~$5–6/mo VPS (Hetzner CX22, DigitalOcean Basic Droplet, or similar) is
enough for an MVP's traffic.

**Known limitation, by design (see CLAUDE.md / the project's stated
gaps):** there is no real authentication yet. The deployed app should only
ever hold the seeded demo tenant, never real student data, until auth
ships. Every request is dev-authenticated by baking a fixed
`X-Tenant-ID`/`X-Actor-ID` into the SPA build.

---

## 0. Prerequisites **[HUMAN]**

- A VPS running **Ubuntu 24.04**, reachable over SSH as root (or a sudo
  user). Any provider works — Hetzner, DigitalOcean, etc.
- A domain (or subdomain) with a DNS **A record** pointing at the VPS's
  public IP. Caddy needs this to issue a Let's Encrypt certificate — the
  deploy will fail without it resolving.
- A GitHub repo containing this monorepo (see §5 if it isn't pushed yet).
- Ability to add **repository secrets** under Settings → Secrets and
  variables → Actions.

## 1. Provision the VPS

SSH in as root and run:

```sh
# Docker Engine + Compose plugin (official Docker apt repo, Ubuntu 24.04 "noble")
apt-get update
apt-get install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# A non-root deploy user that owns the app and can run docker
adduser --disabled-password --gecos "" deploy
usermod -aG docker deploy

# Firewall: SSH + HTTP/HTTPS only
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable
```

**[HUMAN]** Generate a dedicated deploy keypair on your own machine (not
the VPS) and authorize it for the `deploy` user:

```sh
ssh-keygen -t ed25519 -f ./yanai_deploy_key -C "yanai-deploy" -N ""
```

Copy `yanai_deploy_key.pub`'s contents into
`/home/deploy/.ssh/authorized_keys` on the VPS (as root: `mkdir -p
/home/deploy/.ssh && echo '<pubkey>' >> /home/deploy/.ssh/authorized_keys
&& chown -R deploy:deploy /home/deploy/.ssh && chmod 700
/home/deploy/.ssh && chmod 600 /home/deploy/.ssh/authorized_keys`). Keep
`yanai_deploy_key` (the private half) — it becomes the `SSH_KEY` GitHub
secret in §5.

From here on, SSH in as `deploy@<your-server>` instead of root.

## 2. Lay out `/srv/yanai`

```sh
sudo mkdir -p /srv/yanai
sudo chown deploy:deploy /srv/yanai
git clone <your-repo-url> /srv/yanai
mkdir -p /srv/yanai/audio /srv/yanai/ui /srv/yanai/backups
```

Cloning the whole monorepo (not just `deploy/`) means `docker compose
build` works locally as a fallback if GHCR is ever unreachable — normal
deploys pull the pre-built image instead and never touch this build
context.

## 3. Configure secrets

```sh
cat > /srv/yanai/.env <<'EOF'
POSTGRES_PASSWORD=<generate a strong random password>
DOMAIN=yanai.example.com
API_IMAGE=ghcr.io/<github-owner>/yanai-api:latest
EOF
chmod 600 /srv/yanai/.env
```

Generate the Postgres password with e.g. `openssl rand -base64 24`.

**[HUMAN]** If the GHCR package (`yanai-api`) is private, the server needs
its own read access to pull it: either make the package public after the
first push (repo → Packages → yanai-api → Package settings → Change
visibility), or `docker login ghcr.io` on the server with a PAT that has
`read:packages`. Public is simpler for an MVP with no proprietary code in
the image.

## 4. First deploy (manual, one-time)

```sh
cd /srv/yanai

# Bring up Postgres alone first — the API's healthcheck-gated startup
# needs it already accepting connections.
docker compose --env-file .env -f deploy/docker-compose.prod.yml up -d postgres
docker compose --env-file .env -f deploy/docker-compose.prod.yml exec postgres pg_isready -U postgres -d yanai

# Build the API image locally for this first run (subsequent deploys pull
# from GHCR instead — see §5).
docker compose --env-file .env -f deploy/docker-compose.prod.yml build api

# Migrate. GOOSE_DRIVER/GOOSE_DBSTRING/GOOSE_MIGRATION_DIR are already set
# in the compose file's api service, so this needs no extra arguments.
docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  run --rm --entrypoint /usr/local/bin/goose api up

# Seed the demo tenant (NOT a goose migration — run directly, same as dev).
docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  exec -T postgres psql -U postgres -d yanai -f /seed/seed_demo_tenant.sql

# Get the demo teacher's actor id (users.id) for the SPA build below.
docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  exec -T postgres psql -U postgres -d yanai -tAc \
  "select id from users where email='janice.quispe@cristorey.edu.pe'"
```

The VPS never needs `bun` installed — only this first build does, and it's
built on whichever machine already has the toolchain (your laptop, or this
Claude Code session if it has SSH access to the server) and shipped over.
From `yanai-ui/` on that machine:

```sh
bun install
PUBLIC_API_BASE_URL='' \
PUBLIC_TENANT_ID='11111111-1111-4111-8111-111111111111' \
PUBLIC_ACTOR_ID='<the id from the query above>' \
bun run build
rsync -az --delete build/ deploy@<your-server>:/srv/yanai/ui/
```

Every deploy after this one builds the SPA in GitHub Actions instead (§5)
— the VPS only ever receives the finished static files.

Bring everything up and smoke-test:

```sh
cd /srv/yanai
docker compose --env-file .env -f deploy/docker-compose.prod.yml up -d
curl -fsS https://$(grep ^DOMAIN .env | cut -d= -f2)/healthz
```

Open `https://<your-domain>/` in a browser and walk all six screens
(Home, class dashboard, lesson/attendance, grades, notifications,
profile) against the live server.

## 5. Wire up GitHub Actions CI/CD

The workflows already exist in the repo:

- **`.github/workflows/ci.yml`** — on every PR and push to `main`: `go vet`
  + `go build` for the server, `bun run check` + `bun eslint .` + `bun run
  build` for the UI.
- **`.github/workflows/deploy.yml`** — on push to `main`: builds and
  pushes the API image to GHCR, builds the SPA, rsyncs the SPA and
  `deploy/` config to the server, pulls the new image, runs migrations,
  restarts the stack, and smoke-tests `/healthz` + `/api/v1/me`.

**[HUMAN]** Add these repository secrets (Settings → Secrets and variables
→ Actions → New repository secret):

| Secret | Value |
|---|---|
| `SSH_HOST` | the VPS's IP or hostname |
| `SSH_USER` | `deploy` |
| `SSH_KEY` | contents of the private half of the deploy keypair from §1 |
| `DOMAIN` | same value as `.env`'s `DOMAIN` on the server |
| `PUBLIC_TENANT_ID` | `11111111-1111-4111-8111-111111111111` |
| `PUBLIC_ACTOR_ID` | the actor id looked up in §4 |

`GITHUB_TOKEN` (used to push to GHCR) is provided automatically — nothing
to add for it.

Once the secrets are set, push to `main` and watch the Actions tab. Every
push after that redeploys automatically.

## 6. Backups

```sh
sudo tee /etc/cron.d/yanai-backup >/dev/null <<'EOF'
0 3 * * * deploy cd /srv/yanai && docker compose --env-file .env -f deploy/docker-compose.prod.yml exec -T postgres pg_dump -U postgres -Fc yanai > /srv/yanai/backups/yanai-$(date +\%Y\%m\%d).dump && find /srv/yanai/backups -name 'yanai-*.dump' -mtime +14 -delete
30 3 * * 0 deploy tar -czf /srv/yanai/backups/audio-$(date +\%Y\%m\%d).tar.gz -C /srv/yanai audio && find /srv/yanai/backups -name 'audio-*.tar.gz' -mtime +60 -delete
EOF
```

Nightly Postgres dumps (14-day retention), weekly audio-directory tarballs
(60-day retention). **[HUMAN, optional]** Copy `/srv/yanai/backups`
offsite periodically (e.g. `rclone sync /srv/yanai/backups
remote:yanai-backups`) — a backup that only lives on the machine it
protects against isn't a backup.

## 7. Rollback

Bad deploy? Re-point at the previous image tag and restart:

```sh
cd /srv/yanai
# Find the previous working sha from `git log` or the Actions run history.
sed -i 's#^API_IMAGE=.*#API_IMAGE=ghcr.io/<owner>/yanai-api:<previous-sha>#' .env
docker compose --env-file .env -f deploy/docker-compose.prod.yml pull api
docker compose --env-file .env -f deploy/docker-compose.prod.yml up -d api
```

Bad migration? Restoring the database means downtime — stop the API first
so nothing writes during the restore:

```sh
cd /srv/yanai
docker compose --env-file .env -f deploy/docker-compose.prod.yml stop api
docker compose --env-file .env -f deploy/docker-compose.prod.yml exec -T postgres \
  pg_restore -U postgres -d yanai --clean --if-exists < /srv/yanai/backups/yanai-<date>.dump
docker compose --env-file .env -f deploy/docker-compose.prod.yml start api
```

## 8. Verification checklist

- [ ] `curl https://<domain>/healthz` → `{"ok":true}`
- [ ] `curl https://<domain>/api/v1/me` with the demo tenant/actor headers
      → the seeded teacher
- [ ] All six screens load and work in a browser: Home, class dashboard,
      lesson/attendance (mark present, add a voice note), grades (enter a
      score), notifications, profile
- [ ] A push to `main` triggers `deploy.yml` and it goes green
- [ ] The nightly backup cron entry exists (`crontab -l` won't show it —
      check `/etc/cron.d/yanai-backup` and `ls /srv/yanai/backups` the
      morning after)
