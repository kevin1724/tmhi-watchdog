# Project structure

```text
tmhi-watchdog/
├── src/tmhi_watchdog/       Python application package
│   ├── main.py              FastAPI app and API routes
│   ├── watchdog.py          Outage state machine and reboot safeguards
│   ├── gateway.py           T-Mobile gateway login and reboot client
│   ├── connectivity.py      Independent internet connectivity probes
│   ├── storage.py           SQLite event history
│   ├── config.py            Environment-based configuration
│   ├── models.py            Runtime data models
│   ├── cli.py               Diagnostic command-line tools
│   └── static/              Built-in dashboard assets
├── tests/                   Automated tests
├── deploy/                  Optional deployment examples
├── scripts/                 Repository helper scripts
├── docs/                    Additional project documentation
├── .github/                 CI, container publishing, and issue templates
├── Dockerfile               Production container image
├── docker-compose.yml       Recommended source-build deployment
├── .env.example             Safe configuration template
└── README.md                Installation and usage guide
```

The project uses a `src/` layout so imports always resolve from the installed application package instead of accidentally importing duplicate files from the repository root.
