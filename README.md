# TMHI Gateway Watchdog

A self-hosted Python and Docker watchdog for supported T-Mobile Home Internet gateways.

TMHI Gateway Watchdog monitors internet connectivity from inside your home network. If the internet remains unavailable for a configured amount of time—but the gateway is still reachable locally—it signs in to the gateway's local API and requests a reboot.

This is designed for the common failure where devices remain connected to Wi-Fi or Ethernet and can still reach `192.168.12.1`, but the gateway has lost its usable cellular connection.

> [!IMPORTANT]
> Start with `DRY_RUN=true`. Confirm connectivity checks and gateway authentication work before allowing real automatic reboots.

## Features

- Multiple independent HTTP connectivity checks
- Sustained-outage confirmation instead of rebooting after one failure
- Local gateway reachability and authentication testing
- Automatic and manual gateway reboot requests
- Startup, post-reboot, and cooldown protection
- Maximum reboot limit per 24 hours
- Persistent SQLite event history
- Built-in browser dashboard
- REST API for a future or external UI
- Docker and Docker Compose deployment
- Prebuilt image support through GitHub Container Registry
- Password and API-token support through environment variables or Docker secret files

## Supported gateways

Version 0.1 supports gateways that use the unified `TMI/v1` local API:

- Arcadyan KVD21
- Arcadyan TMOG4AR
- Sagemcom Fast 5688W
- Sercomm TMOG4SE

The Nokia 5G21 uses a different cookie/CGI API and is not currently supported.

## How it works

1. The watchdog runs several internet checks every few seconds.
2. A round is considered online when the configured minimum number of checks succeed.
3. If the internet stays offline for the configured failure threshold, the outage is confirmed.
4. The watchdog verifies that the gateway is still reachable on the local network.
5. It signs in to the gateway's local API and sends the reboot request.
6. It waits through a post-reboot grace period before evaluating connectivity again.
7. Cooldown and daily reboot limits prevent reboot loops.

## Requirements

- A supported T-Mobile Home Internet gateway
- A Linux system, NAS, mini PC, or server that stays powered on
- Docker Engine
- Docker Compose v2 (`docker compose`)
- The Docker host must be connected to the same local network as the gateway

Check Docker:

```bash
docker --version
docker compose version
```

## Quick start — prebuilt image

This method pulls the published image from GitHub Container Registry instead of compiling it locally.

### 1. Download the project

```bash
git clone https://github.com/kevin1724/tmhi-watchdog.git
cd tmhi-watchdog
```

### 2. Create your configuration

```bash
cp .env.example .env
```

Generate a random API token and place it into `.env`:

```bash
TOKEN=$(openssl rand -hex 32)
sed -i "s|^API_TOKEN=.*|API_TOKEN=$TOKEN|" .env
```

Edit the file:

```bash
nano .env
```

Set your real gateway administrator password:

```env
GATEWAY_HOST=192.168.12.1
GATEWAY_PORT=8080
GATEWAY_USERNAME=admin
GATEWAY_PASSWORD=your-real-gateway-admin-password

DRY_RUN=true
WATCHDOG_ENABLED=true
```

Keep `DRY_RUN=true` during initial testing.

Save Nano with `Ctrl+O`, press `Enter`, then exit with `Ctrl+X`.

> [!WARNING]
> An `.env` file must contain only `NAME=value` lines and comments. Do not paste Python code, terminal prompts, or shell commands into it. Do not put spaces inside variable names.

### 3. Prepare persistent storage

The container runs as user ID `10001`. On Linux, make the local data directory writable by that user:

```bash
mkdir -p data
sudo chown -R 10001:10001 data
sudo chmod 750 data
```

This directory stores the SQLite event database and survives container recreation.

### 4. Validate the configuration

```bash
docker compose -f docker-compose.ghcr.yml config -q
```

No output means the Compose configuration is valid.

### 5. Start the application

```bash
docker compose -f docker-compose.ghcr.yml up -d
```

Check its state:

```bash
docker compose -f docker-compose.ghcr.yml ps
docker compose -f docker-compose.ghcr.yml logs --tail=100 tmhi-watchdog
```

## Build from source instead

Use this method when developing the project or testing local code changes:

```bash
git clone https://github.com/kevin1724/tmhi-watchdog.git
cd tmhi-watchdog
cp .env.example .env

mkdir -p data
sudo chown -R 10001:10001 data
sudo chmod 750 data

nano .env
docker compose config -q
docker compose up -d --build
```

Do not run `docker-compose.yml` and `docker-compose.ghcr.yml` at the same time. They both use container name `tmhi-watchdog` and host port `8088`.

## Open the dashboard

On the Docker host:

```text
http://localhost:8088/
```

From another computer or phone on the same network, use the Docker host's LAN address:

```text
http://DOCKER-SERVER-IP:8088/
```

Find the server address on Linux:

```bash
hostname -I
```

Example:

```text
http://192.168.12.50:8088/
```

Additional endpoints:

- Dashboard: `http://DOCKER-SERVER-IP:8088/`
- Health check: `http://DOCKER-SERVER-IP:8088/healthz`
- API documentation: `http://DOCKER-SERVER-IP:8088/docs`
- Current status: `http://DOCKER-SERVER-IP:8088/api/status`

Do not use `localhost` from your phone or another computer. On those devices, `localhost` refers to that device—not the Docker server.

## Safe testing before real reboots

Keep this setting enabled:

```env
DRY_RUN=true
```

### Test the application health

```bash
curl -sS http://127.0.0.1:8088/healthz
```

Expected response:

```json
{"ok":true,"version":"0.1.0"}
```

### Test internet detection

Prebuilt-image installation:

```bash
docker compose -f docker-compose.ghcr.yml exec tmhi-watchdog \
  python -m app.cli connectivity
```

Source-build installation:

```bash
docker compose exec tmhi-watchdog python -m app.cli connectivity
```

A working connection should report `"online": true`.

### Test gateway reachability and authentication

Prebuilt-image installation:

```bash
docker compose -f docker-compose.ghcr.yml exec tmhi-watchdog \
  python -m app.cli gateway-test
```

Source-build installation:

```bash
docker compose exec tmhi-watchdog python -m app.cli gateway-test
```

Expected result:

```json
{
  "reachable": true,
  "authenticated": true
}
```

- `reachable: true` means the container can reach the gateway's local API.
- `authenticated: true` means the configured administrator password works.

### Test through the browser dashboard

Open the dashboard, enter the `API_TOKEN` from `.env`, and run the gateway test.

The token can be displayed locally with:

```bash
grep '^API_TOKEN=' .env
```

Treat this token like a password. Do not post it publicly.

### Test a dry-run reboot

With `DRY_RUN=true`, a manual reboot request records what would happen without actually rebooting the gateway.

```bash
TOKEN=$(sed -n 's/^API_TOKEN=//p' .env)

curl -sS -X POST \
  -H "X-API-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"force":false}' \
  http://127.0.0.1:8088/api/reboot
```

Check the logs:

```bash
docker compose logs --tail=100 tmhi-watchdog
```

You should see a message similar to:

```text
DRY RUN: gateway reboot would have been requested
```

## Enable real automatic reboots

Only continue after the connectivity test and gateway test both succeed.

Edit `.env`:

```bash
nano .env
```

Change:

```env
DRY_RUN=false
```

Recreate the container so it loads the new setting.

Prebuilt-image installation:

```bash
docker compose -f docker-compose.ghcr.yml up -d --force-recreate
```

Source-build installation:

```bash
docker compose up -d --force-recreate
```

Confirm the effective setting:

```bash
curl -sS http://127.0.0.1:8088/api/config
```

Look for:

```json
"dry_run": false
```

Perform the first real reboot test only while you are at home and able to recover the gateway manually.

## Default protection settings

The included `.env.example` uses these defaults:

| Setting | Default | Purpose |
|---|---:|---|
| `CHECK_INTERVAL_SECONDS` | `20` | Time between connectivity rounds |
| `FAILURE_THRESHOLD_SECONDS` | `180` | Internet must remain down for 3 minutes |
| `STARTUP_GRACE_SECONDS` | `60` | Prevents action immediately after startup |
| `POST_REBOOT_GRACE_SECONDS` | `480` | Allows 8 minutes for gateway recovery |
| `REBOOT_COOLDOWN_SECONDS` | `1800` | Prevents another reboot for 30 minutes |
| `MAX_REBOOTS_PER_24H` | `3` | Caps automatic and non-forced manual reboots |
| `PROBE_TIMEOUT_SECONDS` | `5` | Timeout for each internet probe |
| `MINIMUM_SUCCESSFUL_PROBES` | `2` | Successful probes required to consider internet online |

The default probes are:

```env
PROBE_URLS=https://connectivitycheck.gstatic.com/generate_204,https://www.cloudflare.com/cdn-cgi/trace,http://www.msftconnecttest.com/connecttest.txt
```

The watchdog uses HTTP/HTTPS checks rather than ICMP ping, so it does not need the `NET_RAW` capability.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `GATEWAY_HOST` | Yes | Gateway LAN address; normally `192.168.12.1` |
| `GATEWAY_PORT` | Yes | Unified local API port; normally `8080` |
| `GATEWAY_USERNAME` | Yes | Normally `admin` |
| `GATEWAY_PASSWORD` | For real reboots | Gateway administrator password |
| `DRY_RUN` | Yes | When `true`, records reboot decisions without sending them |
| `WATCHDOG_ENABLED` | Yes | Enables or disables the automatic watchdog loop |
| `API_TOKEN` | For controls | Protects manual POST API actions and dashboard controls |
| `DATABASE_PATH` | No | SQLite path; default `/data/watchdog.db` |
| `LOG_LEVEL` | No | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |
| `CORS_ORIGINS` | No | Comma-separated origins for a separate browser UI |

All supported values are documented in `.env.example`.

## API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/` | Built-in dashboard |
| `GET` | `/healthz` | Process health |
| `GET` | `/api/status` | Watchdog state and recent probe results |
| `GET` | `/api/config` | Non-secret effective configuration |
| `GET` | `/api/events?limit=100` | Persistent event history |
| `POST` | `/api/check` | Run one check without automatic reboot |
| `POST` | `/api/check/series` | Run a sequence of checks without automatic reboot |
| `POST` | `/api/gateway/test` | Test local reachability and login |
| `POST` | `/api/reboot` | Request a manual reboot |

POST endpoints require this header:

```text
X-API-Token: your-api-token
```

Manual reboot body:

```json
{
  "force": false
}
```

`force: true` bypasses cooldown and the 24-hour limit. It does not bypass `DRY_RUN`.

## Common commands

### View status

```bash
docker compose ps
```

### Follow logs

```bash
docker compose logs -f tmhi-watchdog
```

Press `Ctrl+C` to stop following logs. The container continues running.

### Restart

```bash
docker compose restart tmhi-watchdog
```

### Stop and remove the container

```bash
docker compose down
```

The SQLite database remains in `./data`.

### Rebuild after source changes

```bash
docker compose up -d --build
```

## Updating

### Prebuilt image

```bash
cd ~/tmhi-watchdog
git pull
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

### Source build

```bash
cd ~/tmhi-watchdog
git pull
docker compose up -d --build
```

## Troubleshooting

### `line 1: key cannot contain a space`

Your `.env` file is malformed. Recreate it from the example:

```bash
mv .env .env.bad
cp .env.example .env
nano .env
```

A valid file begins with entries like:

```env
GATEWAY_HOST=192.168.12.1
GATEWAY_PORT=8080
```

It must not contain Python imports, terminal prompts, or commands.

Inspect hidden characters with:

```bash
sed -n '1,20l' .env
```

### `sqlite3.OperationalError: unable to open database file`

The container cannot write to the bind-mounted data directory.

```bash
mkdir -p data
sudo chown -R 10001:10001 data
sudo chmod 750 data
docker compose up -d --force-recreate
```

Verify numeric ownership:

```bash
ls -ldn data
```

The owner and group should be `10001 10001`.

### Dashboard does not open

Check whether the container is running:

```bash
docker compose ps
docker compose logs --tail=100 tmhi-watchdog
```

Test directly on the Docker host:

```bash
curl -i http://127.0.0.1:8088/healthz
```

Check whether port `8088` is listening:

```bash
sudo ss -ltnp | grep ':8088'
```

If the local curl works but another device cannot connect, allow the port through UFW:

```bash
sudo ufw allow 8088/tcp
```

Use the Docker server's LAN IP from other devices—not `localhost`.

### Port `8088` is already in use

Find the process using it:

```bash
sudo ss -ltnp | grep ':8088'
```

Change the Compose port mapping if needed:

```yaml
ports:
  - "8090:8000"
```

Then open port `8090` instead.

### Gateway is unreachable

Test the local gateway route from the Docker host:

```bash
curl -v --max-time 10 \
  "http://192.168.12.1:8080/TMI/v1/gateway/?get=all"
```

An HTTP response such as `200` or `401` confirms the address is reachable. A timeout usually indicates a routing, VLAN, firewall, or gateway-address issue.

### Gateway authentication fails

Confirm that:

- `GATEWAY_USERNAME=admin`
- `GATEWAY_PASSWORD` is the gateway administrator password
- The password has no accidental leading or trailing spaces
- You recreated the container after changing `.env`

```bash
docker compose up -d --force-recreate
```

### Docker permission denied

Add your account to the Docker group:

```bash
sudo usermod -aG docker "$USER"
newgrp docker
```

### Bridge networking cannot reach the gateway

Normal Docker bridge networking usually works. If your host blocks the route to `192.168.12.1`, remove the `ports:` section from Compose and add:

```yaml
network_mode: host
```

With host networking, the application listens directly on host port `8000` instead of mapped port `8088`.

## Security

- Keep the dashboard on your trusted LAN by default.
- Do not forward port `8088` directly to the internet.
- Use a long, random `API_TOKEN`.
- Never publish `.env`; it contains secrets.
- `.env` is included in `.gitignore`.
- Passwords and API tokens are not intentionally logged or stored in SQLite.
- The gateway API itself uses unencrypted local HTTP, so use it only on a trusted network.

Docker secret-style files are supported:

```env
GATEWAY_PASSWORD_FILE=/run/secrets/gateway_password
API_TOKEN_FILE=/run/secrets/api_token
```

When a `_FILE` variable is configured, it takes priority over the matching regular variable.

## Limitations

- This cannot recover a gateway whose local Ethernet, Wi-Fi, or API is completely frozen.
- It cannot help if the Docker host loses power or its LAN connection.
- Gateway firmware updates may change undocumented local API behavior.
- A broad upstream internet outage can also satisfy the reboot policy.
- Run only one application worker and one watchdog container per gateway.
- Use the application only with a gateway you own or are authorized to administer.

For failures where the entire gateway becomes locally unreachable, a separately controlled local power relay may still be required.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```

Build locally:

```bash
docker compose build
```

## Acknowledgements

The local gateway API behavior was studied using the open-source HINT Control project. See [`ACKNOWLEDGEMENTS.md`](ACKNOWLEDGEMENTS.md) for attribution and details.

## License

Released under the MIT License. See [`LICENSE`](LICENSE).

## Disclaimer

TMHI Gateway Watchdog is an unofficial community project. It is not affiliated with, endorsed by, or supported by T-Mobile.
