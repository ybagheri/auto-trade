# Architecture

The project is organized around dependency inversion and an execution state machine.

```text
SignalProvider -> TradeSignal -> RiskEngine -> ExecutionWorkflow
                                      |
                                      v
                         TradingTerminalAdapter
                                      |
                                      v
                         MT5 UI -> Verification
```

- `domain`: typed models, enums, exceptions, and protocols.
- `application`: risk decisions, state transitions, and workflow orchestration.
- `infrastructure`: configuration, file signals, Windows discovery, and audit logging.
- `adapters`: dry-run and currently unavailable desktop terminal implementations.
- `cli`: diagnostics and safe one-signal commands.

Business logic does not import Windows UI code. A future desktop UI and the CLI must call the same application workflow.
