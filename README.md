# traider

A hub for using an AI CLI (Claude Code, OpenCode, Cowork, Gemini CLI,
Cursor, Aider, …) to gain financial insights and help make trading
decisions.

`traider` itself doesn't trade. It's a **collection of MCP servers**
that expose read-only market data, account data, and analytics as
tools the model can call. You keep every decision; the model fetches,
compiles, parses, and explains.

See [AGENTS.md](AGENTS.md) for the hub's north star — what belongs
here, what doesn't, and how to navigate the per-server docs.

## Layout

```
traider/
├── AGENTS.md                 # hub north star (load into your AI CLI)
├── README.md                 # this file
├── mcp_servers/
│   ├── docker-compose.yml    # one service per server (optional)
│   └── schwab_connector/     # Schwab Trader API (incl. its Dockerfile)
└── logs/                     # per-server runtime logs (cwd-relative)
```

Each server under `mcp_servers/` is its own installable package with
its own `README.md`, `AGENTS.md`, and `pyproject.toml`.

## Available MCP servers

| Server                                             | What it gives the model                                                          | Details                                                            |
|----------------------------------------------------|----------------------------------------------------------------------------------|--------------------------------------------------------------------|
| [`schwab_connector`](mcp_servers/schwab_connector) | Quotes, OHLCV history, TA-Lib indicators, movers, instruments, hours, accounts, return/risk/correlation/regime/pair-spread analytics | [README](mcp_servers/schwab_connector/README.md) · [AGENTS](mcp_servers/schwab_connector/AGENTS.md) |

More servers (other brokers, data vendors, news/sentiment, on-chain,
research tools) will be added over time. The pattern stays the same:
one subdirectory per server, independently installable.

## Quickstart

You'll install or run one or more MCP servers, start each one, and
point your AI CLI at them. Each server's own `README.md` has the full
setup — the steps below are the short path for the Schwab connector.

The flow is:

1. **Configure credentials** (shared by both run modes).
2. **Run the server(s)** — either with [Docker](#run-with-docker-recommended)
   (recommended) or [directly on the host](#run-on-the-host-alternative).
3. **[Wire the server into your AI CLI](#connect-your-ai-cli).**

### Configure credentials

Both run modes read credentials from a `.env` at the repo root
(gitignored, loaded on startup). Compose also reads it via
`env_file: ../.env` in `mcp_servers/docker-compose.yml`.

For the Schwab connector, see its
[README](mcp_servers/schwab_connector/README.md#5-configure-schwab-credentials)
for the app-registration walkthrough.

```
SCHWAB_APP_KEY=...
SCHWAB_APP_SECRET=...
SCHWAB_CALLBACK_URL=https://127.0.0.1
```

Never commit this file or paste its contents into logs or chat.

### Run with Docker (recommended)

Each MCP server ships a `Dockerfile` next to its code, and
`mcp_servers/docker-compose.yml` wires them all together. You skip
installing conda and the C deps (TA-Lib, …) on your host.

**1. Build the images**

```bash
cd mcp_servers
docker compose build
```

**2. One-time OAuth (per server that needs it)**

Run the server's auth subcommand interactively. The token file is
written to `~/.schwab-connector/` on the host (mounted into the
container), so a later `docker compose up` reuses it, and so does the
host `schwab-connector` CLI if you also use it outside Docker.

```bash
docker compose run --rm schwab-connector schwab-connector auth
```

You'll paste the Schwab callback URL back into the terminal, same as
the non-Docker flow (the container never has to receive the callback
itself — it's a copy-paste from your browser).

**3. Start the servers**

```bash
docker compose up -d
```

Each server exposes its MCP endpoint on a fixed port:

| Server              | URL                     |
|---------------------|-------------------------|
| `schwab-connector`  | `http://localhost:8765` |

Wire the URL into your AI CLI using the **HTTP** examples in
[Connect your AI CLI](#connect-your-ai-cli) below. Logs land in
`./logs/` on the host.

**4. Stop / rebuild**

```bash
docker compose down                   # stop everything
docker compose up -d schwab-connector # start just one server
docker compose build --no-cache       # after changing a Dockerfile
```

### Run on the host (alternative)

If you'd rather run servers directly on your machine — no Docker —
use a shared conda env.

**1. Create the conda env**

All Python in this repo uses a conda env named `traider`, pinned to
Python 3.13:

```bash
conda create -n traider python=3.13
conda activate traider
```

**2. Install the server(s) you want**

```bash
pip install -e ./mcp_servers/schwab_connector
```

**3. One-time auth, then run the server**

```bash
schwab-connector auth    # one-time browser OAuth flow
schwab-connector         # starts the MCP server on stdio
```

Or over HTTP for remote MCP clients:

```bash
schwab-connector --transport streamable-http --port 8765
```

Then see [Connect your AI CLI](#connect-your-ai-cli) — use the
**stdio** form for a direct host run, or the **HTTP** form when you
start the server with `--transport streamable-http`.

## Connect your AI CLI

Once a server is running — either on the host (stdio) or in Docker
(HTTP on `localhost:8765/mcp`) — register it with your CLI using one
of the recipes below. Examples use the Schwab connector; swap the
name/URL for any other server in the hub.

### Claude Code

`claude mcp add` writes to your Claude config; no JSON editing. Add
`--scope user` to make it available across all projects, or
`--scope project` to check it into `.mcp.json` for teammates. Default
scope (`local`) is this project only.

**Stdio (host install):**

```bash
claude mcp add --transport stdio schwab-connector -- schwab-connector
```

The `--` separates `claude mcp add` flags from the command that
launches the server.

**HTTP (Docker, or any streamable-http server):**

```bash
claude mcp add --transport http schwab-connector http://localhost:8765/mcp
```

Use `--header "Authorization: Bearer …"` if the endpoint needs auth
(the servers in this hub don't).

Verify with `claude mcp list`, then restart the CLI session.

### OpenCode

Edit `opencode.json` in the repo root (project-local) or
`~/.config/opencode/opencode.json` (user-wide). MCP servers live
under the top-level `mcp` key.

**Stdio (host install):**

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "schwab-connector": {
      "type": "local",
      "command": ["schwab-connector"],
      "enabled": true
    }
  }
}
```

**HTTP (Docker, or any streamable-http server):**

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "schwab-connector": {
      "type": "remote",
      "url": "http://localhost:8765/mcp",
      "enabled": true
    }
  }
}
```

Use `{env:VAR_NAME}` inside `headers` for auth tokens when you need
them.

### Gemini CLI

Edit `.gemini/settings.json` in the repo root (project) or
`~/.gemini/settings.json` (user). MCP servers live under
`mcpServers`.

**Stdio (host install):**

```json
{
  "mcpServers": {
    "schwab-connector": {
      "command": "schwab-connector"
    }
  }
}
```

If the server needs env vars injected, use `"env": { "KEY": "$KEY" }`
— Gemini CLI does **not** auto-load `.env`, so either export the
vars in your shell first or put the literal values in `env`.

**HTTP (Docker, or any streamable-http server):**

```json
{
  "mcpServers": {
    "schwab-connector": {
      "httpUrl": "http://localhost:8765/mcp"
    }
  }
}
```

Add `"headers": { "Authorization": "Bearer $TOKEN" }` if the endpoint
requires auth.

## What this hub will and won't do

- **Will.** Fetch, align, and compute on market data. Explain what
  the numbers say. Flag regime shifts, correlations, mean-reversion
  setups, realized-vol outliers, fundamental outliers — all of it
  read-only, all of it for the user to act on.
- **Won't.** Place orders, create alerts, make writes to any
  brokerage or external service. Ship "auto-trader" features.
  Silently retry past a 429 or paper over a failing dependency.
  Store credentials in the repo or in logs.

See [AGENTS.md](AGENTS.md) for the full set of hub-wide constraints
(which every MCP server in this repo inherits).
