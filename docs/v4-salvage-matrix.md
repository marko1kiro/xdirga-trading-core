# METASCAN V4 Salvage Audit and Provenance Matrix

## Audit basis

- **Fresh repository:** `marko1kiro/xdirga-trading-core`
- **Fresh starting commit:** `619211bb36ba290db8cc18fb9512055b24e8a1c3`
- **Legacy repository:** `sherlymakeup/xdirga-metascan-v4`
- **Legacy branch:** `main`
- **Legacy reviewed commit:** `0fe3b84cb523e62f5d84f7f8d3cc8bf74b9b14e5`
- **Classification vocabulary:** `KEEP / ADAPT / REWRITE / DROP / LATER`
- **Target constraint:** one broker, one account, one symbol, one strategy, one active position, one execution path.

All legacy evidence below is pinned to the full legacy commit shown above. The legacy repository was inspected read-only at that detached commit; branch-tip behavior is not evidence.

## Executive summary

V4 is evidence, not an architecture template. Its strongest salvage value is behavioral: serialized ownership of the MT5 API, strict boot identity checks, explicit unavailable broker facts, durable command/event transitions, an `EXECUTION_UNKNOWN` state, retained execution locks, broker-observed reconciliation verdicts, and fail-closed risk gates. These behaviors should survive, but most implementations require adaptation or rewrite because V4 couples broker polling, command orchestration, transport, UI read models, event publication, risk, recovery, bulk operations, and persistence.

No execution implementation qualifies for wholesale `KEEP`. Positive recommendations retain narrow invariants or patterns only. Broker state remains authoritative for actual positions. A timeout, disconnect, or ambiguous submission must become `EXECUTION_UNKNOWN`; it must never trigger blind resubmission. New execution stays blocked until broker evidence reconciles every unknown or mismatched state.

## Salvage matrix

| Candidate | Source Path | Source Symbol | Source Commit | Classification | Evidence | Reason | Dependencies | Safety Invariants | Migration Risk | Timing | Proposed Fresh Destination |
|---|---|---|---|---|---|---|---|---|---|---|---|
| MT5 API ownership and lifecycle | `backend/src/metascan/mt5/gateway.py`; `backend/src/metascan/mt5/handoff.py`; `backend/tests/test_mt5_lifecycle.py`; `backend/tests/test_mt5_gateway_thread.py` | `Mt5Gateway`, `LatestFrameSlot`, `submit_command()`, `_drain_commands()` | `0fe3b84cb523e62f5d84f7f8d3cc8bf74b9b14e5` | ADAPT | One gateway thread performs boot, polling, queued calls, and shutdown. Tests prohibit MT5 imports outside the gateway and verify thread ownership. | Retain single-owner serialization; replace arbitrary callable submission and V4 event-loop coupling with a minimal typed broker interface. | Python threads/queues, asyncio handoff, internal metrics/clocks/types, `MetaTrader5` at runtime. | One owner for all MT5 calls; orderly shutdown; no concurrent broker mutation path. | MEDIUM — sound boundary, coupled handoff/API. | Phase 1: broker foundation | `src/xdirga_trading_core/broker/mt5_gateway.py` |
| MT5 boot identity and symbol validation | `backend/src/metascan/mt5/gateway.py`; `backend/src/metascan/mt5/symbols.py`; `backend/tests/test_mt5_boot_verify.py`; `backend/tests/test_mt5_symbols.py`; `backend/tests/test_mt5_none_errors.py` | `GatewayConfig`, `Mt5Gateway._boot()`, `resolve_symbol()` | `0fe3b84cb523e62f5d84f7f8d3cc8bf74b9b14e5` | ADAPT | Initialization verifies login, trial/live environment, hedging mode, symbol visibility/tradeability, tick size/value, volume bounds, stops, freeze level, and filling mode; failures abort boot. | Keep checks needed by the configured account and single symbol; remove watchlist/general-product surface. | MT5 account/symbol APIs, gateway config, symbol/type modules. | Account/environment mismatch, unavailable account, non-tradeable symbol, or invalid sizing metadata blocks trading. | LOW — narrow checks are directly useful. | Phase 1: broker foundation | `src/xdirga_trading_core/broker/mt5_gateway.py` |
| Broker snapshots and unavailable-state semantics | `backend/src/metascan/mt5/gateway.py`; `backend/src/metascan/mt5/types.py`; `backend/src/metascan/mt5/consumer.py` | `Mt5Gateway._one_cycle()`, `BrokerStateFrame`, `BrokerStateConsumer.process_frame()` | `0fe3b84cb523e62f5d84f7f8d3cc8bf74b9b14e5` | ADAPT | Polls positions, account, ticks, and metadata into immutable frames. `positions_get() is None` with an error sets `positions_unavailable=True`, rather than representing an empty book. Consumer degrades readiness on failures/staleness and quarantines foreign magic. | Preserve explicit availability and freshness facts in a much smaller snapshot consumed by reconciliation and risk. | MT5 polling, clocks, mapping types, event bus/dashboard consumer in V4. | Unknown broker data is never interpreted as no position; broker snapshot outranks local assumptions; foreign magic is never managed. | MEDIUM — semantics useful, consumer is broadly coupled. | Phase 1: broker foundation | `src/xdirga_trading_core/broker/snapshot.py` |
| Singular MT5 order submission | `backend/src/metascan/mt5/gateway.py`; `backend/tests/test_mt5_mutation_seam.py` | `mutation()`, `_mutation_on_gateway_thread()`, `_checked_send()`, `_normalize_partial()` | `0fe3b84cb523e62f5d84f7f8d3cc8bf74b9b14e5` | REWRITE | Builds entry/close/partial-close/protection/cancel requests, calls `order_check` before `order_send`, records verification context, and validates partial volume with `Decimal`. Some non-entry operations send when `order_check` is unavailable. | Preserve serialized send, preflight policy, ownership checks, and exact volume rules; implement only the V1 singular path. Do not copy broad mutation dispatch or unavailable-check bypass. | MT5 constants/results, symbol metadata, pipeline command kinds, in-memory verification context. | Persist intent before send; validate ownership immediately before mutation; ambiguous response is unknown; no automatic resend; positive retcode alone is not final proof. | HIGH — money-moving code and completion semantics are unsafe to copy directly. | Phase 2: singular execution | `src/xdirga_trading_core/execution/service.py` |
| Execution identity and provenance | `backend/src/metascan/journal/schema.sql`; `backend/src/metascan/journal/db.py`; `backend/src/metascan/pipeline/request.py`; `backend/src/metascan/mt5/gateway.py`; `backend/src/metascan/pipeline/pending_intent.py` | `commands`, `command_transitions`, `entry_intents`, `Journal.commit_bundle()`, `register_entry_intent()`, `update_entry_intent()` | `0fe3b84cb523e62f5d84f7f8d3cc8bf74b9b14e5` | REWRITE | Stores command, client request, idempotency and correlation IDs, canonical request JSON, transitions, and entry order/deal/position tickets. Entry matching uses magic, symbol, a 17-character command prefix, and broker tickets. Non-entry pending intents are memory-only. | Retain identity fields and atomic intent/event principle; create a generic durable attempt record for every supported mutation, including account, symbol, magic, request hash, submit time, and broker IDs. | SQLite journal, Pydantic request models, event bus, pipeline state model, MT5 comments/history. | Every submission has auditable immutable identity; same idempotency key cannot represent a different request; provenance survives restart. | HIGH — current provenance is asymmetric and weakly correlated. | Phase 2: before first order send | `src/xdirga_trading_core/execution/models.py`; `src/xdirga_trading_core/persistence/execution_store.py` |
| `EXECUTION_UNKNOWN` transition and no-blind-retry lock | `backend/src/metascan/pipeline/command_pipeline.py`; `backend/tests/test_sp5_behavioral_e2e.py`; `backend/tests/test_sp5_r5_entry_unknown.py`; `backend/tests/test_sp5_uncertainty_contract.py`; `backend/tests/test_pd0_p0_tripwires.py` | `TERMINAL`, `_unknown()`, `_unknown_internal()`, `_verification_unresolved()`, `_verification_unresolved_internal()` | `0fe3b84cb523e62f5d84f7f8d3cc8bf74b9b14e5` | REWRITE | Timeout, disconnect, or result without a retcode transitions to literal `EXECUTION_UNKNOWN`, emits a reconciliation issue and critical alert, retains target/entry scope, and verifies broker state. Unresolved verification leaves the lock held. | This is mandatory V1 behavior, but the state machine should be isolated from V4's large command pipeline and all unknown attempts must be durable. | Async pipeline, event bus, risk config timeouts, pending registry, journal, gateway verification. | Never retry ambiguous submission; retain block across restart; reconcile before another execution decision; unresolved means blocked, not failed or completed. | HIGH — correct policy, incomplete durability and heavy coupling. | Phase 2: before first order send | `src/xdirga_trading_core/execution/state_machine.py` |
| Broker-proven execution verdicts | `backend/src/metascan/pipeline/command_pipeline.py`; `backend/src/metascan/mt5/gateway.py`; `backend/tests/test_sp5_verification_verdict.py`; `backend/tests/test_sp5_temporal_verification_budget.py` | `verdict()`, `_temporal_verify()`, `Mt5Gateway.verify()`, `_verify_on_gateway_thread()` | `0fe3b84cb523e62f5d84f7f8d3cc8bf74b9b14e5` | ADAPT | Verdicts use position absence, reduced volume, expected SL/TP, order absence, or correlated entry position. Verification polls until a bounded deadline and preserves unknown when required broker domains are unavailable. | Retain action-specific proof rules; narrow to V1 action and anchor broker history queries to durable submit identity/time, not a fixed recent window. | Pipeline kinds, gateway snapshots/orders/deals, async timing, transient verification context. | Broker observation determines completion; unavailable evidence cannot prove success or rejection; timeout leaves unknown. | MEDIUM — rules are useful; evidence windows/context need redesign. | Phase 2: execution verification | `src/xdirga_trading_core/reconciliation/verdicts.py` |
| Startup and ongoing minimal reconciliation | `backend/src/metascan/pipeline/command_pipeline.py`; `backend/src/metascan/mt5/consumer.py`; `backend/tests/test_sp5_r5_recovery_rehydration.py`; `backend/tests/test_mt5_deal_reconciliation.py`; `backend/tests/test_mt5_external_close.py`; `backend/tests/test_mt5_external_partial.py`; `backend/tests/test_mt5_external_modify.py`; `backend/tests/test_mt5_diff_positions.py` | `_recover_entry_intents()`, `_recovery_verify_internal()`, `BrokerStateConsumer._reconcile_closed_position()`, `process_frame()` | `0fe3b84cb523e62f5d84f7f8d3cc8bf74b9b14e5` | REWRITE | Rehydrates unresolved entry intents, re-verifies them, diffs broker positions, and uses deal history for observed closes. Reconciliation may abandon close lookup after four frames or ten seconds and has no durable discrepancy workflow. | Build a minimal startup coordinator: read unresolved attempts, fetch authoritative account/positions/orders/recent deals, match owned artifacts, persist discrepancies, and block execution until proven resolution. | Journal, consumer state/read model, event bus, MT5 history, pending registries. | Broker positions are authoritative; mismatch, history failure, unknown execution, or unmatched owned artifact blocks new trading; no time-based silent abandonment. | HIGH — essential behavior is fragmented and incomplete. | Phase 3: before restart-safe trading | `src/xdirga_trading_core/reconciliation/coordinator.py` |
| Fail-closed entry risk admission | `backend/src/metascan/pipeline/risk_gate.py`; `backend/src/metascan/pipeline/risk_config.py`; `backend/src/metascan/pipeline/facts.py`; `backend/tests/test_sp5_risk_gate.py`; `backend/tests/test_sp5_r5_risk_config_validation.py` | `run_gates()`, `classify()`, `RiskConfig`, `RuntimeFactsProvider.snapshot()` | `0fe3b84cb523e62f5d84f7f8d3cc8bf74b9b14e5` | REWRITE | Entry gates require allowed symbol, ready runtime, entries enabled, no safety halt, fresh account/tick/metadata, exposure limits, daily-loss threshold, hard stop, and valid sizing data; sizing floors volume. Some config fields are duplicated or not enforced. | Preserve deny-by-default checks in one small broker-derived timestamped snapshot; include only V1-enforced limits. Remove dormant config. | Pydantic config/request models, runtime facts, pipeline state, Decimal sizing. | Missing, stale, invalid, mismatched, or uncertain facts reject entry; unknown execution or active/mismatched position rejects entry; hard stop is mandatory. | HIGH — safety policy is good but current wiring/config is inconsistent. | Phase 4: before strategy activation | `src/xdirga_trading_core/risk/gate.py` |
| Persistence transaction and append-only audit pattern | `backend/src/metascan/journal/schema.sql`; `backend/src/metascan/journal/db.py`; `backend/tests/test_commit_before_publish.py`; `backend/tests/test_command_tx.py`; `backend/tests/test_sp5_persistence.py`; `backend/tests/test_sp5_durable_entry_intent.py` | `events`, `commands`, `command_transitions`, `Journal._writer_loop()`, `commit_bundle()`, `commit_internal_bundle()` | `0fe3b84cb523e62f5d84f7f8d3cc8bf74b9b14e5` | ADAPT | SQLite uses one writer, WAL, foreign keys, append-only triggers, unique idempotency keys, and atomic event/command transition commits. It uses `synchronous=NORMAL`; mutable runtime state and entry-only intents remain. | Reuse narrow SQLite transaction patterns, not schema. Define durability explicitly for pre-send intents and fail closed on persistence errors. | Python `sqlite3`, threads/queues, pipeline request models, event envelope models. | Intent is durable before broker call; audit transitions are append-only; persistence failure blocks execution; idempotency collision cannot alter intent. | MEDIUM — proven primitives, unsuitable schema/durability defaults. | Phase 1: persistence foundation | `src/xdirga_trading_core/persistence/sqlite_store.py` |
| Gateway and safety tests as behavioral specifications | `backend/tests/test_mt5_lifecycle.py`; `backend/tests/test_mt5_gateway_thread.py`; `backend/tests/test_mt5_boot_verify.py`; `backend/tests/test_mt5_none_errors.py`; `backend/tests/test_mt5_foreign_magic.py`; `backend/tests/test_sp5_behavioral_e2e.py`; `backend/tests/test_sp5_r5_entry_unknown.py`; `backend/tests/test_sp5_verification_verdict.py`; `backend/tests/test_sp5_temporal_verification_budget.py`; `backend/tests/test_mt5_deal_reconciliation.py`; `backend/tests/test_commit_before_publish.py`; `backend/tests/test_command_tx.py` | Test modules and fake MT5 fixtures | `0fe3b84cb523e62f5d84f7f8d3cc8bf74b9b14e5` | ADAPT | Tests exercise MT5 thread ownership, boot rejection, `None` versus empty broker results, foreign magic, unknown/no resend/lock retention, broker verdicts, deal reconciliation, and commit-before-publish. All execution uses fakes. | Translate the smallest invariant-focused cases to fresh interfaces; do not copy fixtures tied to V4 architecture. Add broker-terminal integration evidence only when a safe test environment exists. | Pytest, asyncio, Pydantic, extensive V4 fake gateway/event/journal scaffolding. | Tests must assert no resend, durable unknown after restart, broker authority, fail-closed unavailable facts, and atomic intent-before-send. | LOW — specifications are valuable; fixtures are not. | Alongside Phases 1–4 | `tests/` beside each fresh component |
| Bulk close/cancel and emergency orchestration | `backend/src/metascan/pipeline/command_pipeline.py`; `backend/tests/test_sp5_bulk_emergency.py` | `_bulk()`, `_execute_child()`, `_unknown_bulk()`, `_emergency()` | `0fe3b84cb523e62f5d84f7f8d3cc8bf74b9b14e5` | LATER | Sweeps broker artifacts, filters by magic, fans out child mutations, rescans, and escalates unknown/remaining items. | V1 needs one active position and one execution path. Fan-out multiplies ambiguous outcomes and blast radius. Retain only immediate halt/block semantics now. | Full pipeline, event bus, bulk child state, gateway sweep, magic filtering. | If introduced, each child needs independent durable identity and reconciliation; emergency begins by blocking entries. | HIGH — broad money-moving fan-out. | Post-V1; only after singular path proven | N/A |
| Web API, SSE, dashboard, and frontend cockpit | `backend/src/metascan/api/`; `backend/src/metascan/sse/`; `frontend/` | API routers, SSE transport, frontend application | `0fe3b84cb523e62f5d84f7f8d3cc8bf74b9b14e5` | LATER | Provides control/read transport and product UI around runtime events and dashboard state. | No direct value to the minimal trading core; importing it would force transport and read-model architecture prematurely. | FastAPI, Uvicorn, Pydantic, Structlog, frontend toolchain and UI packages. | No mutation transport before execution safety is independently proven. | HIGH — large unrelated dependency and architecture burden. | Post-core operator-interface phase | N/A |
| Generic arbitrary-call MT5 queue | `backend/src/metascan/mt5/gateway.py` | `submit_command(fn)` | `0fe3b84cb523e62f5d84f7f8d3cc8bf74b9b14e5` | DROP | Any caller can enqueue an arbitrary callable that executes on the privileged MT5 thread. | Keep serialization internally, but expose only typed, auditable operations. | Python `Callable`, futures, queue. | Every broker call must have a known operation, validated input, and audit identity. | HIGH — bypasses narrow broker boundary. | NOT PLANNED | N/A |
| V4 broker comment calibration marker | `backend/src/metascan/mt5/gateway.py` | `_mutation_on_gateway_thread()` entry comment: `CALIBRATE-SP6` | `0fe3b84cb523e62f5d84f7f8d3cc8bf74b9b14e5` | DROP | Entry comment concatenates `command_id[:17]` with a release/calibration marker. | It is not stable provenance, truncates identity, and risks collisions. Fresh broker comments need a deliberately specified compact identifier mapped to a durable full record. | MT5 broker comment length/format. | Broker correlation must resolve uniquely to immutable local provenance. | MEDIUM — weak identity can mis-correlate execution. | NOT PLANNED | N/A |
| Mutable unaudited runtime-state table | `backend/src/metascan/journal/schema.sql`; `backend/src/metascan/pipeline/command_pipeline.py` | `runtime_state`, `_persist_runtime_state()`, `_recover_runtime_state()` | `0fe3b84cb523e62f5d84f7f8d3cc8bf74b9b14e5` | DROP | Halt/entry flags are overwritten key/value rows; persistence exceptions are swallowed. | A safety state that silently fails to persist cannot be trusted. Use auditable transitions and block on write failure if V1 needs persisted controls. | SQLite journal and command pipeline. | Failure to persist a halt/uncertainty state must fail closed, never continue silently. | HIGH — can lose safety state across restart. | NOT PLANNED in this form | N/A |

## Explicit do-not-copy list

1. Do not copy `CommandPipeline`; it combines orchestration, state transitions, risk, recovery, persistence, event publication, bulk commands, and emergency behavior.
2. Do not copy direct `COMPLETED` transitions from positive MT5 retcodes for non-entry mutations. Broker-observed effect is required.
3. Do not copy swallowed persistence exceptions in halt, intent, release, or recovery paths.
4. Do not copy entry-only durable intents plus memory-only close/partial/modify provenance.
5. Do not copy `command_id[:17]` or `CALIBRATE-SP6` as execution identity.
6. Do not copy the fixed ten-second deal-history verification window; anchor queries to durable submission provenance and broker constraints.
7. Do not copy reconciliation abandonment after a small frame/time budget without durable unresolved state.
8. Do not copy `submit_command(Callable)` as a public privileged gateway seam.
9. Do not copy dynamic, undeclared `MetaTrader5` import behavior or select dependencies during this package.
10. Do not copy unenforced or duplicated risk configuration fields.
11. Do not copy mutable unaudited runtime safety state.
12. Do not copy V4 API, SSE, dashboard, frontend, multi-command, or bulk architecture into the core.
13. Do not treat V4 design/prompts as evidence where runtime code and tests do not implement the claim.
14. Do not copy any source file wholesale. Re-express only approved narrow behavior against fresh interfaces.

## Dependency and architecture burden summary

V4's backend declares Python 3.12, Pydantic, FastAPI, Uvicorn, and Structlog; it also uses SQLite from the standard library. Production code dynamically imports `MetaTrader5`, but the inspected `backend/pyproject.toml` does not declare that package. The frontend and web transport add a separate product/toolchain burden unrelated to the minimal core.

The main burden is internal coupling rather than library count:

- `CommandPipeline` owns too many safety-critical responsibilities.
- `BrokerStateConsumer` mixes broker diffing, health, dashboard state, alerts, pending intent enrichment, close provenance, and reconciliation.
- Journal code imports pipeline request models.
- MT5 mapping imports pipeline outcome concepts.
- Recovery durability covers entries but not every mutation.
- Broker evidence, transient verification context, and local event/read models are intertwined.

The fresh core should introduce only four narrow responsibilities when their phases arrive: typed MT5 gateway, durable execution store/state machine, broker-authoritative reconciliation coordinator, and fail-closed risk gate. WP-00A selects no dependency and creates none of these components.

## Proposed salvage order

1. **Phase 1 — broker and persistence foundations:** adapt single-thread MT5 ownership, strict boot checks, explicit unavailable snapshots, magic isolation, and SQLite atomic/append-only principles.
2. **Phase 2 — one singular execution path:** rewrite durable provenance and the execution state machine before enabling `order_send`; encode `EXECUTION_UNKNOWN`, no resend, retained lock, and broker-proven completion.
3. **Phase 3 — restart-safe reconciliation:** rewrite startup reconciliation around unresolved attempts and authoritative account/position/order/deal snapshots; persist discrepancies and block until proven resolution.
4. **Phase 4 — entry risk admission:** rewrite the minimal gate over a fresh broker-derived snapshot; reject stale, invalid, unavailable, unknown, mismatched, or already-exposed state.
5. **Alongside each phase:** adapt only the relevant V4 tests as behavioral specifications using fresh fakes and interfaces.
6. **Post-V1 only:** consider bulk emergency execution, operator API, SSE, dashboard, or UI after the singular core is proven.

## Unresolved questions

These questions require Project Director or later design-package ownership; they are not placeholders for WP-00A implementation.

1. **Owner: Project Director — scope:** Which single mutation is the first V1 execution path: entry, close, or another explicitly bounded operation?
2. **Owner: execution design package — proof:** For each eventual action, which broker facts constitute completion: position/order snapshot, deal history, or both?
3. **Owner: broker design package — account mode:** Must V1 support only hedging, or also netting? V4 rejects non-hedging accounts.
4. **Owner: persistence design package — durability:** Is SQLite `synchronous=FULL` sufficient for pre-send intent durability, and what backup/schema-version policy is required?
5. **Owner: operations design package — unresolved state:** What authenticated manual procedure can resolve an execution that broker evidence cannot conclusively classify?
6. **Owner: risk design package — daily loss:** How will day boundary, starting equity/balance, deposits, withdrawals, and broker deal history establish authoritative daily loss?
7. **Owner: broker validation package — real integration:** Which test account, terminal version, broker retcodes, history latency, and process-restart cases must be validated before non-simulated execution?
8. **Owner: Project Director — emergency scope:** Is emergency close in V1, or is V1 limited to fail-closed halt plus manual broker action?

## Out-of-scope findings

### OUT-OF-SCOPE FINDING

- **Severity:** HIGH
- **Location:** `backend/src/metascan/pipeline/command_pipeline.py` — `_execute()` and `_execute_child()`
- **Description:** Positive MT5 retcodes complete non-entry mutations without broker-state proof.
- **Recommendation:** Address only in the future singular execution design; require action-specific broker evidence before completion.

### OUT-OF-SCOPE FINDING

- **Severity:** HIGH
- **Location:** `backend/src/metascan/pipeline/command_pipeline.py` — `_persist_runtime_state()`, `_unknown_internal()`, `_release()`
- **Description:** Several persistence failures are swallowed, including safety state and intent updates.
- **Recommendation:** Future persistence/execution work must treat failed safety-critical writes as a trading halt.

### OUT-OF-SCOPE FINDING

- **Severity:** HIGH
- **Location:** `backend/src/metascan/pipeline/pending_intent.py`; `backend/src/metascan/journal/schema.sql` — `entry_intents`
- **Description:** Durable unresolved intent coverage is entry-only; other money-moving intents are process memory.
- **Recommendation:** Define one generic durable attempt model before implementing any fresh mutation.

### OUT-OF-SCOPE FINDING

- **Severity:** MEDIUM
- **Location:** `backend/src/metascan/mt5/gateway.py` — `_verify_on_gateway_thread()`
- **Description:** Deal verification queries a moving ten-second window instead of a persisted submission window.
- **Recommendation:** Anchor future reconciliation to durable submit time, account, symbol, magic, request identity, and broker IDs.

### OUT-OF-SCOPE FINDING

- **Severity:** MEDIUM
- **Location:** `backend/src/metascan/mt5/consumer.py` — close reconciliation paths
- **Description:** Reconciliation can stop attempting close-history resolution after four frames or ten seconds and lacks a durable operator-resolution lifecycle.
- **Recommendation:** Persist discrepancies indefinitely until broker proof or explicit authorized resolution.

### OUT-OF-SCOPE FINDING

- **Severity:** MEDIUM
- **Location:** `backend/pyproject.toml`; `backend/src/metascan/composition.py`
- **Description:** Runtime dynamically imports `MetaTrader5`, but the production dependency is not declared in the inspected project metadata.
- **Recommendation:** Select and pin dependencies only in the authorized fresh foundation package, not WP-00A.

### OUT-OF-SCOPE FINDING

- **Severity:** MEDIUM
- **Location:** V4 execution test suite under `backend/tests/`
- **Description:** Execution evidence uses fake MT5 modules; no inspected test proves real terminal, broker, retcode, history-latency, or restart-during-IPC behavior.
- **Recommendation:** Add a separately authorized safe broker-integration validation gate before non-simulated execution.

## WP-00A boundary statement

WP-00A migrated no runtime code. It added no dependency, source module, test, configuration, UI, API, dashboard, broker integration, strategy, risk implementation, persistence implementation, or execution implementation. It does not begin WP-00B and explicitly rejects wholesale V4 migration.
