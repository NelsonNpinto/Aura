# Permanent AURA demo on DigitalOcean

Prices checked on 3 November 2026. This guide creates a single-workspace demo that a hiring manager can use in a browser. The server runs the AI model through Ollama; the visitor needs no model installation or AI provider key. The commands below are instructions to run when provisioning your server, not a record of an existing cloud deployment.

## 1. Understand the bill

| Item | Current advertised price | Notes |
|---|---|---|
| DigitalOcean Basic, Regular CPU, 4 vCPUs / 8 GiB RAM / 160 GiB SSD | USD 48/month | Starting estimate for the core app and small models, not a capacity benchmark. Includes 5,000 GiB transfer. |
| Weekly Droplet backups | USD 9.60/month on that plan | Optional; percentage-based weekly backups add 20%. |
| Standard, non-premium .com at Porkbun | USD 11.81/year | Current registration and renewal list price; check the exact domain at checkout. An existing domain can supply a subdomain without a new registration. |
| HTTPS certificate | No certificate purchase needed | Caddy can obtain and renew a free certificate. |
| PostgreSQL, Ollama, AURA | No separate managed-service or AI API subscription for this setup | They run on the paid server. |

The server alone is USD 48/month before tax. With weekly backups it is USD 57.60/month before tax, plus the domain billed annually. For an India-billed personal account where DigitalOcean applies its published 18% GST, those server totals become USD 56.64 and USD 67.97 respectively. Card currency conversion and other applicable charges are additional. Confirm the checkout total; credits and promotions are not assumed here.

The Basic 16 GiB / 8 vCPU plan currently lists USD 96/month. Consider more RAM before adding the full Langfuse stack or larger models. Shared CPUs can have variable inference speed. The USD 24/month 4 GiB plan is cheaper, but this guide does not assume it has enough headroom for the complete AI dependency stack.

Sources: [Droplets](https://www.digitalocean.com/pricing/droplets), [backups](https://www.digitalocean.com/pricing/backups), [domain prices](https://porkbun.com/products/domains), [India billing tax](https://docs.digitalocean.com/platform/billing/taxes/ind/), [free TLS certificates](https://letsencrypt.org/).

## 2. Prepare an SSH key on your Mac

Open Terminal on your Mac. Create a dedicated key, choosing a passphrase when prompted:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/aura_cloud -C "aura-cloud"
```

If that filename already exists, reuse the existing key or choose another filename rather than overwriting it. All later SSH commands must use the filename you chose.

Copy only the public key:

```bash
pbcopy < ~/.ssh/aura_cloud.pub
```

The file without `.pub` is your private key. Keep it on your Mac.

Reference: [SSH key creation](https://docs.digitalocean.com/products/droplets/how-to/add-ssh-keys/create-with-openssh/).

## 3. Create the cloud account and server

Open the [DigitalOcean control panel](https://cloud.digitalocean.com/), create an account, add a payment method, and enable account two-factor authentication. Create a project called AURA, then choose Create > Droplets.

Select:

| Setting | Selection |
|---|---|
| Image | Ubuntu 24.04 LTS, x86-64 |
| Type | Basic, Regular CPU |
| Size | 8 GiB RAM / 4 vCPUs / 160 GiB SSD, advertised USD 48/month |
| Region | Nearest available region to you and your reviewers |
| Authentication | SSH key; paste the public key copied above |
| Quantity | One Droplet |
| Name | aura-demo |
| Extra volumes, managed database, load balancer, GPU | None for this setup |
| Monitoring | Optional, no additional Monitoring charge |
| Backups | Optional weekly plan; review the extra charge |

Review the price before clicking Create. Billing begins when the server is created. Copy its public IPv4 address; use it wherever this guide says `SERVER_IP`.

References: [Create a Droplet](https://docs.digitalocean.com/products/droplets/how-to/create/), [upload SSH keys](https://docs.digitalocean.com/platform/teams/how-to/upload-ssh-keys/), [Monitoring pricing](https://docs.digitalocean.com/products/monitoring/details/pricing/).

## 4. Configure the cloud firewall

In DigitalOcean, open Networking > Firewalls > Create Firewall. Name it `aura-demo`, apply it to your Droplet, and configure these inbound rules:

| Protocol / port | Allowed source |
|---|---|
| TCP 22 (SSH) | Your current public IP, using the panel's My IP option |
| TCP 80 (HTTP) | All IPv4 and IPv6 |
| TCP 443 (HTTPS) | All IPv4 and IPv6 |

Keep the default outbound allow rules so package downloads, DNS, and model downloads work. Do not add public inbound rules for 5273, 8200, 5433, 11434, 3300, or 19090. Compose already binds those published application ports to loopback.

If you change Wi-Fi or public IP and SSH stops working, update the SSH source rule in the control panel. Keep the provider's console available for recovery.

Reference: [Create a cloud firewall](https://docs.digitalocean.com/products/networking/firewalls/how-to/create/).

## 5. Connect and create the deployment user

On your Mac:

```bash
ssh -i ~/.ssh/aura_cloud root@SERVER_IP
```

Check that you are connecting to the server you just created when accepting its initial host key. On the fresh server, create a normal user and copy the authorized public keys:

```bash
adduser deploy
usermod -aG sudo deploy
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
install -m 600 -o deploy -g deploy /root/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
```

`adduser` asks for a password for the new account. It will be used for `sudo`.

Open another Mac Terminal window and verify the new account before closing the root connection:

```bash
ssh -i ~/.ssh/aura_cloud deploy@SERVER_IP
```

Run subsequent server commands as `deploy` unless a step says otherwise. `sudo` prompts for the deployment user's password.

## 6. Install server packages and Docker

On the server:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git python3 ca-certificates curl gnupg nano openssl dnsutils
```

If Ubuntu requests a reboot after upgrading, use `sudo reboot`, wait for the server to return, and reconnect with the `deploy` SSH command.

Install Docker from its official Ubuntu repository:

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker --version
sudo docker compose version
```

Reference: [Docker installation](https://docs.docker.com/engine/install/ubuntu/).

On this fresh server, configure Docker's rotating local log driver before creating containers:

```bash
sudo install -d -m 0755 /etc/docker
sudo nano /etc/docker/daemon.json
```

Enter the following JSON. If you already have Docker settings in this file, merge the property into them instead of replacing the file:

```json
{
  "log-driver": "local"
}
```

Then:

```bash
sudo systemctl restart docker
```

Reference: [Docker log rotation](https://docs.docker.com/engine/logging/configure/).

## 7. Clone AURA

For a public repository, on the server:

```bash
cd /home/deploy
git clone --branch main https://github.com/NelsonNpinto/Aura.git aura
cd /home/deploy/aura
```

If the repository is private, use this alternative before cloning. Create a separate server-to-GitHub key:

```bash
ssh-keygen -t ed25519 -f /home/deploy/.ssh/aura_github -C "aura-server-readonly"
cat /home/deploy/.ssh/aura_github.pub
```

In the GitHub repository, go to Settings > Deploy keys > Add deploy key. Paste that public key. Leave write access disabled. Then clone and configure the repository to reuse it:

```bash
cd /home/deploy
GIT_SSH_COMMAND='ssh -i /home/deploy/.ssh/aura_github -o IdentitiesOnly=yes' git clone --branch main git@github.com:NelsonNpinto/Aura.git aura
cd /home/deploy/aura
git config core.sshCommand 'ssh -i /home/deploy/.ssh/aura_github -o IdentitiesOnly=yes'
```

A passphrase-protected GitHub key may prompt when pulling updates. Do not paste an access token into a clone URL. Reference: [GitHub deploy keys](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys).

## 8. Create the server configuration

In the freshly cloned directory, let the helper create `.env` directly:

```bash
python3 scripts/configure-local.py
openssl rand -hex 32
nano .env
```

Copy the output of `openssl` into a password manager and set `API_KEY` to that value in `.env`. Nano saves with Control+O, Enter, and exits with Control+X.

| Variable | Value for this deployment |
|---|---|
| POSTGRES_USER / POSTGRES_DB | Keep `aura` |
| POSTGRES_PASSWORD | Keep the generated random value |
| DATABASE_URL | Keep the generated matching host-development URL; Compose supplies its own internal URL |
| API_KEY | Your newly generated workspace key |
| WEBHOOK_SECRET | Keep the separate generated webhook secret |
| OLLAMA_BASE_URL | Keep the default; Compose uses `http://ollama:11434` internally |
| OLLAMA_API_KEY | Blank for the private Ollama container |
| EMBEDDING_PROVIDER | `sentence-transformers` |
| OTEL_ENDPOINT | Blank for the first core deployment |
| LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY | Blank for the first core deployment |

```bash
chmod 600 .env
```

Do not use a database placeholder password. The helper generates a random database password when it creates a new `.env`; it preserves pre-existing files. It does not rotate an already initialized PostgreSQL volume's password. Never put these secrets in frontend `VITE_*` variables.

No paid AI key is required. `API_KEY` protects AURA; `WEBHOOK_SECRET` protects failure ingestion.

## 9. Build and start the core stack

```bash
cd /home/deploy/aura
sudo docker compose up -d --build
sudo docker compose ps
sudo docker compose logs --tail=100 backend
```

The first build downloads dependencies and can take several minutes or longer. The backend includes the RAG dependency group and automatically applies Alembic migrations before starting. You do not need Node or a host Python virtual environment on the server for this Docker deployment.

Check the API and frontend locally on the server:

```bash
curl -f http://127.0.0.1:8200/api/v1/health
curl -f http://127.0.0.1:5273/health
```

The API should report status `ok` and database `connected`; the frontend returns `ok`. This does not yet establish that a model is installed.

## 10. Download models on the server

```bash
sudo docker compose exec ollama ollama pull qwen2.5:0.5b
sudo docker compose exec ollama ollama pull llama3.2:1b
sudo docker compose exec ollama ollama list
```

The first model is a small pipeline demonstration model. A second model lets you demonstrate comparisons. Both are small models; their answers and judge scores need scrutiny. These commands download model files to the server, not to the visitor's computer.

Document embedding and optional reranking models download separately on first use and are cached in a persistent volume. Keep initial requests and evaluation datasets small on CPU inference.

## 11. Verify privately through SSH

On your Mac, open another Terminal:

```bash
ssh -i ~/.ssh/aura_cloud -N -L 5274:127.0.0.1:5273 -L 8201:127.0.0.1:8200 deploy@SERVER_IP
```

Keep that connection open. Open [the app](http://localhost:5274) and optionally [API docs](http://localhost:8201/docs). These local ports avoid the existing Mac deployment's ports.

In AURA Settings, enter the server's `API_KEY`, select Apply session key, then Check connections. Confirm the database, Ollama, and installed model list. Run one short Playground request. The key is stored for the browser session.

## 12. Register a domain and set DNS

If you already own a domain, use a subdomain. Otherwise use [Porkbun](https://porkbun.com/products/domains) to search for an available standard-price domain, review both registration and renewal prices, and buy the domain registration. Separate web hosting or a paid SSL add-on is unnecessary for this setup.

This guide uses `aura.YOUR_DOMAIN` as the hostname. At Porkbun, open Domain Management > your domain > DNS and add:

| Type | Host | Answer | TTL |
|---|---|---|---|
| A | aura | SERVER_IP | Default / 600 seconds |

Keep the domain's existing DNS service. You do not need to move nameservers to DigitalOcean. Remove conflicting records for this exact hostname only; preserve unrelated website and email records. An AAAA record must point to the correct server IPv6 address if you choose to use IPv6.

Reference: [Porkbun A-record instructions](https://kb.porkbun.com/article/54-how-to-use-a-records-to-point-your-domain-at-a-web-host).

Check resolution from your Mac or server:

```bash
dig +short aura.YOUR_DOMAIN A
```

Proceed when it returns the server's IP. If the domain uses Cloudflare DNS already, use DNS-only mode initially so a proxy does not add another timeout layer for synchronous evaluations.

## 13. Install Caddy and enable HTTPS

On the server:

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg
sudo chmod o+r /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install -y caddy
sudo nano /etc/caddy/Caddyfile
```

On this new server, replace the example site with the following, using your real hostname:

```caddyfile
aura.YOUR_DOMAIN {
    encode zstd gzip
    reverse_proxy 127.0.0.1:5273
}
```

Save, then run:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl enable --now caddy
sudo systemctl reload caddy
```

Caddy obtains and renews HTTPS certificates when DNS is correct and public ports 80/443 are reachable. Keep its data on the server intact for certificate persistence. AURA's frontend already proxies `/api/` to the backend, so this deployment needs no separate frontend API hostname or CORS change.

References: [Caddy installation](https://caddyserver.com/docs/install#debian-ubuntu-raspbian), [automatic HTTPS](https://caddyserver.com/docs/automatic-https).

## 14. Open the public demo and prepare reviewer data

Open `https://aura.YOUR_DOMAIN` in a browser and enter the server workspace key in Settings. This origin has separate browser storage from localhost. Check the public API health endpoint:

```bash
curl -f https://aura.YOUR_DOMAIN/api/v1/health
```

A new cloud database is empty. Prepare synthetic demo content:

1. Upload a short refund policy in Knowledge Base: `Refunds are available within 30 days of purchase.`
2. Index the document and inspect its chunks.
3. In Playground, ask `How long do I have to request a refund?` and generate an answer.
4. In Evaluations, check that the actual answer is non-empty and contains `30 days`.
5. In AI Judge, supply that question, actual answer, reference answer, and policy context, then inspect the scores and explanations.
6. Create a small dataset with clear expected answers and rules, save a baseline, and compare a second configuration.
7. Inspect the saved request and evaluation history in Traces and Monitoring.

Save observed results, including failures. AI judgments are estimates, not proof of correctness. Do not label yourself as having human-calibrated reliability until genuine human reviews have been collected.

Give a trusted reviewer the HTTPS URL, the workspace key privately, and a short description of the workflow above. They need only a browser. AURA currently gives key holders shared workspace editing access; this is not a read-only guest account. Use demo data and keep your private development data separate. A public anonymous guest mode would need additional application work.

## 15. Back up the application database and secrets

Enable the optional weekly Droplet backup through the provider panel if you want automated server backups, reviewing the cost. Also take application-level database backups before updates and migrations.

On the server:

```bash
cd /home/deploy/aura
umask 077
mkdir -p backups
sudo docker compose exec -T db pg_dump -U aura -d aura -Fc > backups/aura.dump
```

After the dump command succeeds, copy it to your Mac. On your Mac:

```bash
mkdir -p /Volumes/PortableSSD/aura/backups
scp -i ~/.ssh/aura_cloud deploy@SERVER_IP:/home/deploy/aura/backups/aura.dump /Volumes/PortableSSD/aura/backups/cloud-aura.dump
scp -i ~/.ssh/aura_cloud deploy@SERVER_IP:/home/deploy/aura/.env /Volumes/PortableSSD/aura/backups/cloud.env
chmod 600 /Volumes/PortableSSD/aura/backups/cloud-aura.dump /Volumes/PortableSSD/aura/backups/cloud.env
```

Keep dated copies rather than relying on one overwritten backup. Treat both files as private. The repository ignores `backups/`. Keep an additional secure copy that is not on the same cloud disk. Langfuse, if added, has separate databases and object storage; the AURA dump does not back those up.

To restore an AURA dump, first back up any destination data you want to preserve. Restoring with `--clean` replaces the destination application's database contents. On the destination server with `db` running:

```bash
cd /home/deploy/aura
sudo docker compose stop frontend backend
sudo docker compose exec -T db pg_restore -U aura -d aura --clean --if-exists --no-owner < backups/aura.dump
sudo docker compose up -d
```

## 16. Optionally copy your existing Mac data

Instead of starting with an empty demo database, you can copy your local AURA database. Review it first because it includes prompts, responses, documents, and review data.

On your Mac:

```bash
cd /Volumes/PortableSSD/aura
mkdir -p backups
umask 077
docker compose exec -T db pg_dump -U aura -d aura -Fc > backups/local-aura.dump
scp -i ~/.ssh/aura_cloud backups/local-aura.dump deploy@SERVER_IP:/home/deploy/aura/backups/local-aura.dump
```

Use the restore commands in step 15 with `backups/local-aura.dump` as input. Keep the cloud server's own generated database credentials; restoring data does not require changing them to your Mac's credentials. Redownload Ollama models rather than copying its cache. This does not transfer Langfuse's separate history.

## 17. Deploy updates

Create a database backup first. Then, on the server:

```bash
cd /home/deploy/aura
git pull --ff-only
sudo docker compose up -d --build
sudo docker compose restart frontend
sudo docker compose ps
curl -f http://127.0.0.1:8200/api/v1/health
```

The backend runs migrations at startup. Restarting frontend makes Nginx resolve the recreated backend container. Docker volumes preserve stored data, and the server's `.env` stays private. A GitHub push alone does not redeploy this server.

For OS maintenance, periodically review and install Ubuntu updates and reboot when required. Docker is enabled at boot and services use `restart: unless-stopped`, so running services normally return after a reboot. A container you explicitly stopped may need `sudo docker compose up -d`.

## 18. Optionally add Langfuse

Core AURA traces work without Langfuse. Check RAM headroom or resize before enabling its PostgreSQL, Redis, ClickHouse, storage, web, worker, and collector services.

The supplied Langfuse login URL assumes local port 3300. To avoid colliding with your existing Mac installation, use a private SSH tunnel on local port 3301 and an override:

```bash
cd /home/deploy/aura
python3 scripts/configure-local.py --observability
mkdir -p .local
nano .local/langfuse-remote.yml
```

Save:

```yaml
services:
  langfuse-web:
    environment:
      NEXTAUTH_URL: http://localhost:3301
  langfuse-worker:
    environment:
      NEXTAUTH_URL: http://localhost:3301
```

Start the complete profile:

```bash
sudo docker compose -f docker-compose.yml -f docker-compose.observability.yml -f .local/langfuse-remote.yml --profile observability up -d --build
sudo docker compose restart frontend
```

On your Mac:

```bash
ssh -i ~/.ssh/aura_cloud -N -L 3301:127.0.0.1:3300 deploy@SERVER_IP
```

Open [Langfuse](http://localhost:3301). The email is `developer@aura.local`; read `LF_ADMIN_PASSWORD` from the server's private `.env`. Do not share the monitoring admin password with demo visitors. Use the same three Compose files for subsequent observability updates and lifecycle commands so the URL override stays applied.

## 19. Monitor operation and troubleshoot

Useful commands on the server:

```bash
cd /home/deploy/aura
sudo docker compose ps
sudo docker compose logs --tail=100 backend
sudo docker compose logs --tail=100 ollama
sudo docker compose logs --tail=100 frontend
sudo journalctl -u caddy --no-pager -n 100
sudo docker stats --no-stream
df -h
free -h
```

| Symptom | Check |
|---|---|
| SSH times out | Server IP, cloud firewall SSH source, current public IP, and provider console. |
| Domain does not resolve | A record, conflicting records, and authoritative DNS service. |
| HTTPS is unavailable | Correct DNS, public ports 80/443, Caddy validation, and Caddy logs. |
| 401 in AURA | Apply the server workspace key in Settings for this browser origin/session. |
| No models | Run `sudo docker compose exec ollama ollama list`, pull a model, then refresh Settings. |
| Generation times out | Use shorter output, a smaller model, fewer simultaneous requests, and inspect CPU/RAM. |
| Indexing is slow initially | The embedding model may be downloading; inspect backend logs and disk space. |
| Scanned PDF cannot be read | OCR it before upload; extraction does not implement OCR. |
| 502 after backend recreation | Check backend health and restart frontend. |
| Security or judge failures | Inspect the actual result; small-model mistakes are not deployment success criteria to override. |
| Long batch interrupted | Interactive evaluation jobs are synchronous; use small batches. Durable queued execution is not implemented. |

Do not use `docker compose down -v` when preserving application data. Stopping containers with `docker compose down` preserves volumes but makes the app unavailable.

## 20. Control ongoing cost and close the deployment

Set a monthly [DigitalOcean spend alert](https://docs.digitalocean.com/platform/billing/spend-alerts/) at a budget you are comfortable with. For example, USD 70 with notifications at 50%, 80%, and 100%. Ordinary spend alerts notify; they do not cap Droplet charges.

Powering off the server, logging out of SSH, or stopping Docker does not stop the bundled Droplet's bill. [Billing continues until the Droplet is destroyed](https://docs.digitalocean.com/products/droplets/details/pricing/). Included transfer is finite; excess outbound transfer currently costs USD 0.01/GiB.

When retiring this demo, download database and secret backups you need, then use the control panel to [destroy only the AURA Droplet](https://docs.digitalocean.com/products/droplets/how-to/destroy/). Review retained snapshots, backups, or separately created volumes for ongoing charges. Domain registration and auto-renewal are managed separately at your registrar.
