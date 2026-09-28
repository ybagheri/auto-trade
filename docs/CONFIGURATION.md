# Configuration

Runtime configuration currently comes from environment variables with safe defaults. `.env.example` is a template; credentials must never be committed.

| Variable | Default | Purpose |
| --- | --- | --- |
| `AUTO_TRADE_TERMINAL_PATH` | Alpari demo terminal | MT5 executable identity |
| `AUTO_TRADE_DATA_PATH` | specified MT5 data directory | terminal data identity |
| `AUTO_TRADE_INSTANCE_NAME` | `Alpari-MT5-Demo` | instance selection hint matched against the MT5 window title |
| `AUTO_TRADE_SIGNAL_DIR` | `signals` | local signal directory |
| `AUTO_TRADE_LOG_DIR` | `logs` | rotating logs |
| `AUTO_TRADE_DRY_RUN` | `true` | prevents final execution |
| `AUTO_TRADE_DEMO_ONLY` | `true` | rejects non-demo account snapshots |
| `AUTO_TRADE_ALLOWED_SYMBOLS` | `EURUSD,XAUUSD,YM` | symbol whitelist |
| `AUTO_TRADE_MAX_VOLUME` | `1.0` | maximum request volume |
| `AUTO_TRADE_MAX_ORDERS_PER_MINUTE` | `5` | rate limit |
| `AUTO_TRADE_SIGNAL_EXPIRATION_SECONDS` | `10` | default signal lifetime |
| `AUTO_TRADE_HTTP_SIGNAL_URL` | unset | loopback URL of the optional authenticated HTTP signal source |
| `AUTO_TRADE_HTTP_SIGNAL_TOKEN` | unset | bearer token for that source; never logged, never committed |

`config/default.yaml` documents the intended human-readable shape. The current implementation does not parse YAML; do not assume a YAML edit changes runtime behavior.

## Safety defaults

Keep dry-run and demo-only enabled. An environment variable is not a substitute for account and terminal verification. The real adapter must fail closed when account type, terminal identity, or execution result is uncertain.

A configured HTTP signal source does not weaken any of this. It is a pull-only client: it must be a loopback URL, it must present its token, it refuses a redirect off loopback, and a fetched signal still passes the same gates as a signal file. See [signal protocol](SIGNAL_PROTOCOL.md).
