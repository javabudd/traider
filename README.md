# tos-connector

Read-only Schwab Trader API bridge exposed as an MCP server for Claude.
See [AGENTS.md](AGENTS.md) for how the code is organized and what to
watch out for.

## What this MCP server can do

Once the server is running and Claude is connected, Claude gets three
tools. All are **read-only** — no orders, no alerts, no writes.

### `get_quote(symbol, field="LAST")`

A single snapshot field for one symbol. Handy for a quick "what's SPY
trading at right now."

- `symbol` — any symbol Schwab accepts: equities (`AAPL`), ETFs
  (`SPY`), futures (`/ES`), indices (`$SPX`), or 21-char OSI options
  (`SPY   250321C00500000`).
- `field` — either a friendly alias or a native Schwab key. Aliases:
  `LAST`, `BID`, `ASK`, `VOLUME`, `MARK`, `OPEN`, `HIGH`, `LOW`,
  `CLOSE`, `NET_CHANGE`, `PERCENT_CHANGE`, `BID_SIZE`, `ASK_SIZE`.
  Anything else is passed straight through to the Schwab quote object
  (e.g. `lastPrice`, `quoteTime`, `52WeekHigh`).

Returns a string (empty if the field isn't present).

### `get_quotes(symbols, fields=None)`

Batched version of `get_quote`. Use this whenever Claude needs more
than one symbol or more than one field — one HTTP call instead of N.

- `symbols` — list of tickers.
- `fields` — list of aliases or native keys. If omitted, each symbol's
  entry is the full Schwab `quote` object (useful when Claude wants
  to browse what's available).

Returns `{symbol: {field: value}}`.

### `get_price_history(symbol, period_type="year", period=1, frequency_type="daily", frequency=1, ...)`

OHLCV candles for charting or lookback analysis. Defaults give **one
year of daily bars** (the "yearly chart, daily candles" case).

Response shape is Schwab's native format:

```json
{
  "symbol": "SPY",
  "empty": false,
  "candles": [
    {"open": 512.3, "high": 513.9, "low": 511.0,
     "close": 513.2, "volume": 78234100, "datetime": 1708992000000}
  ]
}
```

`datetime` is epoch milliseconds (UTC).

Valid `period_type` / `period` / `frequency_type` / `frequency`
combinations — Schwab rejects the rest with a 400:

| `period_type` | `period`              | `frequency_type`          | `frequency`       |
|---------------|-----------------------|---------------------------|-------------------|
| `day`         | 1, 2, 3, 4, 5, 10     | `minute`                  | 1, 5, 10, 15, 30  |
| `month`       | 1, 2, 3, 6            | `daily`, `weekly`         | 1                 |
| `year`        | 1, 2, 3, 5, 10, 15, 20| `daily`, `weekly`, `monthly` | 1              |
| `ytd`         | 1                     | `daily`, `weekly`         | 1                 |

You can also pass `start_date` / `end_date` as epoch milliseconds —
they override `period` when set. `need_extended_hours_data=True`
includes pre/post-market candles; `need_previous_close=True` adds the
prior session's close to the response.

### Things worth knowing

- **Freshness.** Quotes are real-time during RTH (or as close as the
  Schwab API gets). Outside RTH, `lastPrice` may be stale — pre/post
  fields live under different keys in the quote JSON, so ask for them
  explicitly.
- **Options.** Use the 21-character OSI format
  (`SPY   250321C00500000`, with padded spaces), not dotted TOS
  notation.
- **Rate limits.** Schwab enforces per-endpoint quotas. If you hit
  one, the tool raises (HTTP 429) — the server won't silently retry.
- **Token expiry.** Access tokens auto-refresh. Refresh tokens die
  after ~7 days of inactivity — if you see `SchwabAuthError`, re-run
  `tos-connector auth`.

## Setup

### 1. Install conda

If you don't already have it, install **Miniforge** (community conda
distribution, permissive license, fast solver):

- macOS / Linux / WSL:
  ```bash
  curl -L -O "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
  bash Miniforge3-$(uname)-$(uname -m).sh
  ```
- Windows: download the installer from
  <https://github.com/conda-forge/miniforge/releases/latest> and run it.

Miniconda works fine too if you already have it —
<https://docs.conda.io/en/latest/miniconda.html>.

Restart your shell (or `source ~/.bashrc` / `source ~/.zshrc`) so
`conda` is on your PATH.

### 2. Create the `tos` environment

The project always uses an env named `tos`, pinned to Python 3.13:

```bash
conda create -n tos python=3.13
conda activate tos
```

Every subsequent command in this repo (including `pip install`,
`tos-connector`, any test runner) assumes this env is active.

### 3. Install the package

```bash
conda activate tos
pip install -e .
```

### 4. Register a Schwab developer app

The connector authenticates as an OAuth app you own on the Schwab
developer portal. You need to create that app once before anything
else works.

1. **Create a developer account** at <https://developer.schwab.com>
   and sign in. Your Schwab brokerage login works here.
2. **Create a new app** from the Dashboard. You'll be asked for:
   - **App name** and **description** — free text, shown only to you.
   - **API products** — select **Accounts and Trading Production**
     and **Market Data Production**. (The connector is read-only, but
     the Trader product is what exposes `/marketdata/v1/quotes`.)
   - **Callback URL** — must be HTTPS and must match
     `SCHWAB_CALLBACK_URL` exactly, including trailing slash.
     `https://127.0.0.1` is the simplest choice and is what the auth
     flow assumes by default.
3. **Submit for approval.** New apps start in `Approved - Pending`
   and have to flip to `Ready For Use` before the keys work. This
   usually takes a few minutes to a couple of days; you can't
   shortcut it. If `tos-connector auth` returns `invalid_client`,
   the app is still pending.
4. **Copy the App Key and Secret** from the app's detail page once it
   is `Ready For Use`. The key is public-ish (it's the OAuth
   `client_id`); the secret must be kept private — don't paste it
   into chat, logs, or anything committed to git.
5. **Rotating credentials.** If you regenerate the secret in the
   portal, existing tokens are invalidated — you'll need to re-run
   `tos-connector auth`.

### 5. Configure Schwab credentials

Either export the vars directly:

```bash
export SCHWAB_APP_KEY=...
export SCHWAB_APP_SECRET=...
export SCHWAB_CALLBACK_URL=https://127.0.0.1   # must match the app reg
```

…or drop them in a `.env` file at the repo root (gitignored, loaded
automatically on startup):

```
SCHWAB_APP_KEY=...
SCHWAB_APP_SECRET=...
SCHWAB_CALLBACK_URL=https://127.0.0.1
```

### 6. Authorize once, then run the server

```bash
tos-connector auth             # browser flow, paste redirected URL
tos-connector                  # start the MCP server on stdio
```

Or expose it over HTTP for remote MCP clients:

```bash
tos-connector --transport streamable-http --port 8765
```

### `tos-connector auth` vs `tos-connector` — when to run which

- **`tos-connector auth`** is the interactive OAuth bootstrap. It
  opens your browser, you log into Schwab, and you paste the redirect
  URL back into the terminal. It writes `schwab-token.json` (access +
  refresh token) and exits. Run it:
  - the **first time** you set up the repo;
  - any time **`tos-connector` prints `SchwabAuthError`** (the
    refresh token is dead — happens after ~7 days of no use, or if
    you revoke the app);
  - after **rotating** `SCHWAB_APP_KEY` / `SCHWAB_APP_SECRET`, since
    tokens are bound to the app registration.
- **`tos-connector`** (no subcommand) starts the MCP server. It reuses
  the token file written by `auth` and refreshes the access token on
  its own as needed. This is the one Claude actually talks to — leave
  it running in a terminal while you use the connector. You do **not**
  need to re-run `auth` each session; only when the refresh token
  itself has expired.

Tokens are persisted to `~/.tos-connector/schwab-token.json`
(overridable via `SCHWAB_TOKEN_FILE`). Access tokens auto-refresh;
refresh tokens expire ~7 days and require re-running
`tos-connector auth`.
