# TMHI Gateway Watchdog

[![Docker Hub](https://img.shields.io/badge/Docker%20Hub-kevina1724%2Ftmhi--watchdog-2496ED?logo=docker&logoColor=white)](https://hub.docker.com/r/kevina1724/tmhi-watchdog)
[![Docker Hub downloads](https://img.shields.io/docker/pulls/kevina1724/tmhi-watchdog?label=Docker%20Hub%20downloads&logo=docker)](https://hub.docker.com/r/kevina1724/tmhi-watchdog)

A self-hosted Python and Docker watchdog for supported T-Mobile Home Internet gateways.

TMHI Gateway Watchdog checks multiple internet endpoints from inside your home network. If internet access remains down for a configured period while the gateway is still reachable locally, it signs in to the gateway's local API and requests a reboot.

This targets the failure where phones and computers remain connected to Wi-Fi or Ethernet and can still open `192.168.12.1`, but the gateway has lost its cellular internet connection.

> [!IMPORTANT]
> Keep `DRY_RUN=true` until the connectivity and gateway-login tests both succeed.

## Features

- Multiple independent HTTP/HTTPS connectivity checks
- Sustained-outage confirmation before any reboot
- Local gateway reachability and authentication testing
- Gateway API/model auto-detection for supported local gateways
- Automatic and manual reboot requests
- Startup grace, post-reboot grace, cooldown, and daily reboot limits
- Persistent SQLite event history
- Built-in browser dashboard and REST API
- Docker health check and automatic restart support
- Safe dry-run mode enabled by default
- AMD64 and ARM64 container publishing through GitHub Actions

## Supported gateways

Version 0.1 supports gateways using the unified `TMI/v1` local API:

- Arcadyan KVD21
- Arcadyan TMOG4AR
- Sagemcom Fast 5688W
- Sercomm TMOG4SE

The Nokia 5G21 uses a different CGI/cookie API and is not currently supported.

## Project layout

```text
tmhi-watchdog/
├── src/tmhi_watchdog/       Application package
│   ├── main.py              FastAPI routes and dashboard server
│   ├── watchdog.py          Outage and reboot state machine
│   ├── gateway.py           Gateway login and reboot client
│   ├── connectivity.py      Internet connectivity probes
│   ├── storage.py           SQLite event storage
│   ├── config.py            Environment configuration
│   ├── models.py            Runtime data models
│   ├── cli.py               Diagnostic commands
│   └── static/              Dashboard HTML, JavaScript, and CSS
├── tests/                   Automated tests
├── deploy/                  Optional deployment examples
├── docs/                    Additional documentation
├── scripts/                 GitHub helper scripts
├── .github/                 CI and container-publishing workflows
├── docker-compose.yml       Recommended source deployment
├── Dockerfile               Container build
└── .env.example             Reference for generated settings
```

The organized `src/` layout prevents duplicate root-level modules and accidental imports from the wrong file.

## Requirements

- A supported T-Mobile Home Internet gateway
- A Linux server, NAS, mini PC, or always-on computer
- Docker Engine
- Docker Compose v2 (`docker compose`)
- The Docker host connected to the gateway's local network

Verify Docker:

```bash
docker --version
docker compose version
```

## Quick start: build from source

### 1. Download the project

```bash
git clone https://github.com/kevin1724/tmhi-watchdog.git
cd tmhi-watchdog
```

Or extract the downloaded ZIP and enter the folder.

### 2. Validate and start

```bash
docker compose config -q
docker compose up -d --build
```

Check the container:

```bash
docker compose ps
docker compose logs --tail=100 tmhi-watchdog
```

The default Compose file uses a Docker-managed named volume. On first start, the app creates `/data/watchdog.env` with safe defaults and leaves `DRY_RUN=true`. You do **not** need to create a host `.env` file or `chown` a local `data` folder.

### 3. Open the dashboard

On the Docker server:

```text
http://localhost:8088/
```

From a phone or another computer, use the Docker server's LAN IP:

```text
http://DOCKER-SERVER-IP:8088/
```

Find the server IP:

```bash
hostname -I
```

Other useful URLs:

- Dashboard: `http://SERVER-IP:8088/`
- Health check: `http://SERVER-IP:8088/healthz`
- API documentation: `http://SERVER-IP:8088/docs`
- Current status: `http://SERVER-IP:8088/api/status`

Do not use `localhost` from your phone; on a phone, `localhost` means the phone itself.

## Safe testing

Leave this enabled:

```env
DRY_RUN=true
```

### Test the API

```bash
curl -sS http://127.0.0.1:8088/healthz
```

Expected:

```json
{"ok":true,"version":"0.1.1"}
```

### Test internet detection

```bash
docker compose exec tmhi-watchdog \
  python -m tmhi_watchdog.cli connectivity
```

A working connection should report:

```json
"online": true
```

### Test gateway reachability and login

In the dashboard, enter the gateway admin password in the Gateway login row,
leave Remember checked, then click Log in. The app saves the password to
`/data/watchdog.env` inside the Docker data volume.

From the CLI:

```bash
docker compose exec tmhi-watchdog \
  python -m tmhi_watchdog.cli gateway-test
```

Expected:

```json
{
  "reachable": true,
  "authenticated": true
}
```

- `reachable: true` means Docker can access the gateway locally.
- `authenticated: true` means the configured admin password works.

### Test a reboot without rebooting

With `DRY_RUN=true`, this records the reboot decision but does not send the command:

```bash
curl -sS -X POST \
  -H "Content-Type: application/json" \
  -d '{"force":false}' \
  http://127.0.0.1:8088/api/reboot
```

Check the logs:

```bash
docker compose logs --tail=100 tmhi-watchdog
```

You should see:

```text
DRY RUN: gateway reboot would have been requested
```

## Enable real automatic reboots

Only continue after the connectivity test and gateway login test both succeed.

Edit the generated settings file:

```bash
docker compose exec tmhi-watchdog \
  sh -c "sed -i 's/^DRY_RUN=.*/DRY_RUN=false/' /data/watchdog.env"
```

The relevant value should now be:

```env
DRY_RUN=false
```

Restart the container so the app reloads the generated file:

```bash
docker compose restart tmhi-watchdog
```

Confirm the effective setting:

```bash
curl -sS http://127.0.0.1:8088/api/config
```

The response should include:

```json
"dry_run": false
```

Perform the first real reboot test only while you are home and can recover the gateway manually.

## Prebuilt Docker images

The image is published on Docker Hub:

- Docker Hub: [kevina1724/tmhi-watchdog](https://hub.docker.com/r/kevina1724/tmhi-watchdog)
- Current Docker Hub downloads: **31** (checked July 17, 2026)

Pull it directly:

```bash
docker pull kevina1724/tmhi-watchdog:latest
```

A GHCR image is also available for users who prefer GitHub Container Registry:

```bash
docker compose -f deploy/docker-compose.ghcr.yml pull
docker compose -f deploy/docker-compose.ghcr.yml up -d
```

View logs:

```bash
docker compose -f deploy/docker-compose.ghcr.yml logs -f tmhi-watchdog
```

## Configuration defaults

| Variable | Default | Purpose |
|---|---:|---|
| `CHECK_INTERVAL_SECONDS` | `20` | Time between connectivity rounds |
| `FAILURE_THRESHOLD_SECONDS` | `180` | Continuous outage required before reboot consideration |
| `STARTUP_GRACE_SECONDS` | `60` | Prevents action immediately after container startup |
| `POST_REBOOT_GRACE_SECONDS` | `480` | Allows eight minutes for the gateway to reconnect |
| `REBOOT_COOLDOWN_SECONDS` | `1800` | Prevents another reboot for 30 minutes |
| `MAX_REBOOTS_PER_24H` | `3` | Maximum non-forced reboots in a rolling day |
| `PROBE_TIMEOUT_SECONDS` | `5` | Timeout for each connectivity endpoint |
| `MINIMUM_SUCCESSFUL_PROBES` | `2` | Successful probes required to consider internet online |

The app creates `/data/watchdog.env` with all supported settings. `.env.example` is an annotated reference for that generated file.

## API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/` | Built-in dashboard |
| `GET` | `/healthz` | Process health |
| `GET` | `/api/status` | Current watchdog state and probe results |
| `GET` | `/api/config` | Non-secret effective configuration |
| `GET` | `/api/events?limit=10` | Recent event history |
| `POST` | `/api/check` | Run one check without allowing a reboot |
| `POST` | `/api/check/series` | Run repeated checks without allowing a reboot |
| `POST` | `/api/gateway/test` | Test gateway reachability and login |
| `POST` | `/api/gateway/login` | Authenticate and optionally save the gateway login |
| `DELETE` | `/api/gateway/login` | Forget the saved gateway login |
| `POST` | `/api/reboot` | Request a manual reboot |

## Common commands

Start or apply configuration changes:

```bash
docker compose up -d
```

Rebuild after changing source code:

```bash
docker compose up -d --build
```

Follow logs:

```bash
docker compose logs -f tmhi-watchdog
```

Restart:

```bash
docker compose restart tmhi-watchdog
```

Stop:

```bash
docker compose down
```

Remove the container and its database volume:

```bash
docker compose down -v
```

> [!CAUTION]
> `docker compose down -v` permanently deletes the event-history database.

## Updating

Source build:

```bash
git pull
docker compose up -d --build
```

Prebuilt image:

```bash
git pull
docker compose -f deploy/docker-compose.ghcr.yml pull
docker compose -f deploy/docker-compose.ghcr.yml up -d
```

## Troubleshooting

### Reset generated settings

If you want the app to recreate its managed settings file with defaults:

```bash
docker compose exec tmhi-watchdog \
  sh -c "mv /data/watchdog.env /data/watchdog.env.bad"
docker compose restart tmhi-watchdog
```

### `sqlite3.OperationalError: unable to open database file`

The recommended Compose file uses a named volume and should avoid this problem. Confirm you are using the included root file:

```bash
docker compose down --remove-orphans
docker compose up -d --build
```

If you intentionally use `deploy/docker-compose.bind-mount.example.yml`, prepare its host directory first:

```bash
mkdir -p data
sudo chown -R 10001:10001 data
sudo chmod 750 data
```

### Dashboard does not load

```bash
docker compose ps
docker compose logs --tail=100 tmhi-watchdog
curl -i http://127.0.0.1:8088/healthz
sudo ss -ltnp | grep ':8088'
```

If the local curl works but another device cannot connect:

```bash
sudo ufw allow 8088/tcp
```

Use the Docker server's LAN IP from other devices.

### Port 8088 is already used

Set `WEB_PORT` when starting Compose, or edit the `ports` line in `docker-compose.yml`:

```bash
WEB_PORT=8090 docker compose up -d
```

### Gateway login fails

Confirm the gateway address and user in the generated settings file:

```bash
docker compose exec tmhi-watchdog sed -n '1,20p' /data/watchdog.env
```

If you saved the login from the dashboard, use Forget and then Log in again.
Dashboard-saved credentials are stored as `GATEWAY_PASSWORD` in
`/data/watchdog.env`.

Restart after manually editing `/data/watchdog.env`.

### Docker cannot reach the gateway

Test from the host:

```bash
curl -v --max-time 10 \
  "http://192.168.12.1:8080/TMI/v1/gateway/?get=all"
```

An HTTP response such as `200` or `401` proves the gateway route is reachable. A timeout generally indicates routing, VLAN, firewall, or gateway-address issues.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```

Run the app without Docker:

```bash
export PYTHONPATH=src
export DATABASE_PATH=/tmp/tmhi-watchdog.db
export WATCHDOG_ENV_PATH=/tmp/tmhi-watchdog.env
export WATCHDOG_ENABLED=false
uvicorn tmhi_watchdog.main:app --host 0.0.0.0 --port 8088
```

## Security

- Keep the dashboard on your trusted LAN.
- Do not forward port `8088` directly to the internet.
- Never publish `/data/watchdog.env`, Docker secrets, or saved gateway credential files.
- The local gateway API uses unencrypted HTTP, so use it only on a trusted network.
- Passwords are not intentionally logged or stored in SQLite.

## Limitations

- This cannot recover a gateway whose local network or API is completely frozen.
- It cannot help if the Docker host loses power or its LAN connection.
- Gateway firmware updates may alter undocumented local API behavior.
- A large upstream outage can also satisfy the reboot policy.
- Run only one watchdog container per gateway.
- Use only with a gateway you own or are authorized to administer.

## Acknowledgements

The local gateway API behavior was studied using the open-source HINT Control project. See [`docs/ACKNOWLEDGEMENTS.md`](docs/ACKNOWLEDGEMENTS.md).

## License

Released under the MIT License. See [`LICENSE`](LICENSE).

## Disclaimer

TMHI Gateway Watchdog is an unofficial community project and is not affiliated with, endorsed by, or supported by T-Mobile.
