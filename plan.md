# Remora Framework v8.0 — Deep Audit & Refined Implementation Blueprint
## Critical Analysis, Vulnerability Remediation & Complete System Architecture

---

## Part I: Forensic Audit of the Original Plan

### 1.1 — Identified Loopholes (Severity-Ranked)

| # | Loophole | Severity | Impact |
|---|---|---|---|
| L-01 | **Memory budget unvalidated** — 9000 instruments × 6-float ring buffer × 10K capacity = ~4.3 GB just for tick buffers, before candles, signals, SQLite page cache | CRITICAL | OOM kill on 24 GB VPS |
| L-02 | **SQLite single-writer bottleneck** — WriteQueue batches at 50 ms but 9000 instruments × 5-min boundary = ~30 writes/sec sustained, plus OB/cycloid/swing/smart upserts. BEGIN IMMEDIATE serialises everything | CRITICAL | Write latency > 500 ms triggers DB circuit breaker, halting ingestion |
| L-03 | **No Angel One session lifecycle management** — TOTP auth, feed token TTL (~6 hr), API key rotation, 02:00 IST server reset are mentioned but no state machine governs them | CRITICAL | Silent feed death mid-session |
| L-04 | **Ring buffer overflow is silent** — producer (WebSocket) can outpace consumer (aggregator) during 09:15 open burst; dropped ticks corrupt candle OHLCV without any alert | HIGH | Wrong signals from corrupt candles |
| L-05 | **nb_prob freshness gate uses wall-clock** — 5-minute staleness check assumes system clock is synchronised; NTP drift on cheap VPS can be 2–5 seconds | HIGH | Valid predictions rejected or stale ones accepted |
| L-06 | **Kelly-LVaR denominator collapse** — when σ_5m → 0 (pre-open, illiquid stocks), f_lvar → ∞; no floor guard specified | HIGH | Infinite position size on illiquid names |
| L-07 | **Correlation veto is O(n²) per scan** — with 20 open positions, 190 pairwise Pearson computations every 30 s on 50-bar windows; not cached | MEDIUM | Scan cycle exceeds 30 s budget |
| L-08 | **Config hot-reload has no atomicity** — YAML file watcher triggers per-file reload; a strategy reading config mid-reload gets mixed old/new values | MEDIUM | Inconsistent gate thresholds within one scan |
| L-09 | **No signal deduplication across process restarts** — alerted dictionary is in-memory; crash + restart re-fires all signals from the current scan window | MEDIUM | Duplicate orders on recovery |
| L-10 | **No market-phase awareness** — NSE pre-open (09:00–09:15), continuous (09:15–15:30), closing (15:30–15:40) have different order types and price bands | MEDIUM | Order rejections during wrong phase |
| L-11 | **VIX source single point of failure** — yfinance ^INDIAVIX can timeout or return stale data; fallback is "last known" which could be hours old | MEDIUM | Circuit breakers operating on stale regime data |
| L-12 | **No order modification path** — trailing SL requires modifying the SL-L order price; Angel One API has modifyOrder but no state machine transition defined | MEDIUM | Trailing stop never actually trails |
| L-13 | **tmpfs data loss on power failure** — /dev/shm is volatile; SSD archive sync is every 5 minutes; up to 5 min of candles lost | MEDIUM | Gap in candle history on reboot |
| L-14 | **No corporate action handling** — stock splits, bonuses, dividends change price levels; OB zones become meaningless | LOW | False signals on ex-dividend dates |
| L-15 | **No backtesting harness** — 9 strategies go straight to paper trading with no historical validation | LOW | Unknown expectancy before capital risk |

### 1.2 — Identified Vulnerabilities

| # | Vulnerability | Attack/Failure Vector | Mitigation |
|---|---|---|---|
| V-01 | **Angel One API key in .env** — readable by any process on the VPS | Privilege escalation, container escape | Fernet-encrypted secrets file with 0600 permissions; decrypt at runtime in memory only |
| V-02 | **SQLite injection via dynamic table names** — archiver and sync use string interpolation for table names | Malformed config value executes arbitrary SQL | Strict regex whitelist `^[a-zA-Z0-9_]+$` on all table identifiers |
| V-03 | **Unbounded asyncio.Queue in crypto sidecar** — if DB is offline, queue grows until OOM | Memory exhaustion | Bounded queue with explicit drop policy and counter metric |
| V-04 | **No TLS pinning for Angel One WebSocket** — MITM on VPS network could inject fake ticks | Data integrity compromise | Certificate verification enforced; reject self-signed certs |
| V-05 | **Log files contain ticker-level P&L** — if VPS is shared or logs are shipped externally, trading alpha leaks | Intellectual property theft | Log encryption at rest; no external log shipping without redaction |
| V-06 | **YAML config writable by any user** — if file permissions are loose, a rogue process can change risk parameters | Unauthorised parameter injection | Config files owned by root, read-only for the trading user; validate checksums at load |

### 1.3 — Missing Components (Not in Original Plan)

1. **Pre-market initialisation state machine** — sequence of boot steps with dependency gates
2. **Market phase manager** — tracks NSE trading phases, gates order types per phase
3. **Instrument universe selector** — criteria for choosing which 9000 instruments to subscribe
4. **Position reconciliation engine** — startup check against broker's position book
5. **Order modification state machine** — trailing SL, partial fill handling
6. **Drawdown-based strategy disabler** — auto-disable a strategy after N consecutive losses
7. **Performance attribution engine** — per-strategy P&L, Sharpe, drawdown tracking
8. **Capacity planning model** — mathematical proof that 24 GB is sufficient
9. **Disaster recovery runbook** — what to do when everything fails
10. **Formal testing pyramid** — unit → integration → replay → paper → live

---

## Part II: Refined Directory Structure

```
remora_engine/
│
├── docker-compose.yml
├── Dockerfile
├── Makefile
├── .env.example
├── .env.encrypted                    # Fernet-encrypted secrets (0600)
├── requirements.txt
├── pyproject.toml                    # Build config, tool settings
├── README.md
│
├── config/                           # ═══ YAML CONTROL CENTER ═══
│   ├── system.yaml                   # Global: timezone, paths, RAM budget
│   ├── ingestion.yaml                # WebSocket, ring buffer, candle agg
│   ├── execution.yaml                # Order routing, buffers, cooldowns
│   ├── risk.yaml                     # Kelly-LVaR, VIX tiers, heat limits
│   ├── database.yaml                 # All DB paths, WAL params, sync
│   ├── circuit_breakers.yaml         # Kill switch, health thresholds
│   ├── logging.yaml                  # Levels, rotation, retention
│   ├── instruments.yaml              # Universe selection criteria
│   ├── market_phases.yaml            # NSE phase timings, order type gates
│   ├── parameters_live.yaml          # Hot-swappable runtime params
│   ├── backtest.yaml                 # Backtest harness configuration
│   └── strategies/                   # Per-strategy YAML (9 files)
│       ├── s1_structural_hvfvg.yaml
│       ├── s2_momentum_pairing.yaml
│       ├── s3_golden_confluence.yaml
│       ├── s4_runway_momentum.yaml
│       ├── s5_volatility_squeeze.yaml
│       ├── s6_cycloid_kinematic.yaml
│       ├── s7_entropy_harvester.yaml
│       ├── s8_zone_decay_sniper.yaml
│       └── s9_stop_hunt_fade.yaml
│
├── src/
│   ├── __init__.py
│   │
│   ├── core/                         # ── Foundational Infrastructure ──
│   │   ├── config_manager.py         # Atomic YAML load, hot-reload, checksum
│   │   ├── constants.py              # Enums: SignalType, OrderState, MarketPhase
│   │   ├── exceptions.py             # 12-class exception hierarchy
│   │   ├── event_bus.py              # In-process pub/sub (asyncio)
│   │   ├── health.py                 # Heartbeat writer, liveness, staleness
│   │   ├── clock.py                  # NTP-synced monotonic clock wrapper
│   │   ├── secrets.py                # Fernet decrypt, env-var fallback
│   │   ├── lifecycle.py              # System state machine (BOOT→READY→TRADING→EOD→SHUTDOWN)
│   │   └── market_phase.py           # NSE phase tracker (pre-open/continuous/closing)
│   │
│   ├── ingestion/                    # ── Layer 1: Hot Path ──
│   │   ├── angel_session.py          # TOTP auth, token lifecycle, 02:00 reset
│   │   ├── angel_websocket.py        # Single WS, chunked subscribe, reconnect
│   │   ├── ring_buffer.py            # Lock-free numpy ring with overflow detection
│   │   ├── candle_aggregator.py      # Tick→5m OHLCV, phase-aware boundaries
│   │   ├── tick_validator.py         # Corrupt tick filter (zero price, volume spikes)
│   │   ├── tick_reconciliation.py    # Clock drift, stale tick detection
│   │   ├── write_queue.py            # Batched atomic writer, dead-letter queue
│   │   └── local_bus.py              # RAM-disk SQLite interface, param hot-swap
│   │
│   ├── signals/                      # ── Layer 2: Intelligence ──
│   │   ├── base_scanner.py           # Abstract scanner contract
│   │   ├── order_block_detector.py   # HV+FVG detection, mitigation tracking
│   │   ├── cycloid_engine.py         # 5 setups (A–E), vectorised
│   │   ├── swing_engine.py           # Structural breakout, bull_pct
│   │   ├── smart_block_engine.py     # Order flow delta, POC, YZ vol
│   │   ├── volatility_core.py        # EWRV, Yang-Zhang, dynamic τ
│   │   ├── delta_core.py             # Percentile ranking, OFI, velocity
│   │   ├── quant_predictive.py       # Naive Bayes probability gate
│   │   ├── zone_decay.py             # Kaplan-Meier survival model
│   │   └── strategies/
│   │       ├── strategy_registry.py  # Dynamic loader from YAML, priority arbitration
│   │       ├── strategy_lifecycle.py # Per-strategy enable/disable/drawdown tracking
│   │       ├── s1_structural_hvfvg.py
│   │       ├── s2_momentum_pairing.py
│   │       ├── s3_golden_confluence.py
│   │       ├── s4_runway_momentum.py
│   │       ├── s5_volatility_squeeze.py
│   │       ├── s6_cycloid_kinematic.py
│   │       ├── s7_entropy_harvester.py
│   │       ├── s8_zone_decay_sniper.py
│   │       └── s9_stop_hunt_fade.py
│   │
│   ├── execution/                    # ── Layer 3: Action ──
│   │   ├── execution_engine.py       # 30s scan loop, signal arbitration
│   │   ├── order_state_machine.py    # Full FSM: 9 states, 14 transitions
│   │   ├── order_executor.py         # Async queue daemon, rate limiter
│   │   ├── order_modifier.py         # Trailing SL modification path
│   │   ├── paper_trader.py           # Simulated fills, slippage model
│   │   ├── exit_gate.py              # TP, trailing, EOD, time-based exits
│   │   ├── broker_adapter.py         # Abstract broker interface
│   │   ├── angel_adapter.py          # Angel One SmartAPI implementation
│   │   ├── margin_calculator.py      # Pre-trade margin validation
│   │   └── position_reconciler.py    # Startup position sync with broker
│   │
│   ├── risk/                         # ── Risk Kernel ──
│   │   ├── kelly_lvar.py             # Position sizing with floor guards
│   │   ├── portfolio_heat.py         # Gross exposure, η_t tracking
│   │   ├── correlation_veto.py       # Cached Pearson matrix, incremental update
│   │   ├── vix_regime.py             # Multi-source VIX, tiered response
│   │   ├── circuit_breaker.py        # Priority-ordered breaker cascade
│   │   ├── drawdown_guard.py         # Per-strategy and global drawdown limits
│   │   └── exposure_aggregator.py    # Real-time gross/net exposure
│   │
│   ├── calibration/                  # ── Self-Optimising Loop (Deterministic) ──
│   │   ├── telemetry_collector.py    # MFE/MAE/PnL exhaust on trade close
│   │   ├── variance_profiler.py      # MAE drift detection, failure probability
│   │   ├── regime_calibrator.py      # EWRV-based threshold adjustment
│   │   ├── parameter_hotswap.py      # YAML runtime parameter updates
│   │   └── calibration_audit.py      # Log all parameter changes with provenance
│   │
│   ├── persistence/                  # ── Database Layer ──
│   │   ├── db_manager.py             # SQLAlchemy ORM, BIGINT PKs, quoted keywords
│   │   ├── db_health_monitor.py      # P95 latency circuit breaker
│   │   ├── archiver.py               # EOD SSD archival, VACUUM, 14-day retention
│   │   ├── sync_worker.py            # SQLite→MySQL hourly watermark sync
│   │   └── replay_engine.py          # Morning boot: SSD→RAM-disk replay
│   │
│   ├── monitoring/                   # ── Observability ──
│   │   ├── metrics.py                # Counters, gauges, histograms (Prometheus-style)
│   │   ├── telegram_alerts.py        # Critical alerts only, rate-limited
│   │   ├── audit_logger.py           # Trade audit trail, tamper-evident
│   │   └── capacity_monitor.py       # RAM, disk, CPU tracking with thresholds
│   │
│   └── backtest/                     # ── Historical Validation ──
│       ├── data_loader.py            # Load archived candles from SSD
│       ├── replay_simulator.py       # Replay candles through strategy gates
│       ├── fill_simulator.py         # Simulate fills with slippage model
│       ├── performance_report.py     # Sharpe, drawdown, MFE/MAE per strategy
│       └── parameter_sweep.py        # Grid search over YAML parameter ranges
│
├── tests/
│   ├── unit/                         # Isolated component tests
│   │   ├── test_ring_buffer.py
│   │   ├── test_candle_aggregator.py
│   │   ├── test_kelly_lvar.py
│   │   ├── test_ewrv.py
│   │   ├── test_delta_core.py
│   │   ├── test_order_state_machine.py
│   │   ├── test_config_manager.py
│   │   └── test_strategies/          # One file per strategy
│   ├── integration/                  # Multi-component tests
│   │   ├── test_ingestion_pipeline.py
│   │   ├── test_signal_to_execution.py
│   │   ├── test_risk_cascade.py
│   │   └── test_config_hotreload.py
│   ├── replay/                       # Historical data replay tests
│   │   ├── test_s1_replay.py
│   │   └── test_s7_replay.py
│   └── fixtures/                     # Synthetic candle/tick data
│       ├── sample_candles.py
│       └── sample_order_blocks.py
│
├── scripts/
│   ├── start_all.sh                  # Dependency-safe, phase-gated startup
│   ├── stop_all.sh                   # Graceful drain, SIGTERM→SIGKILL escalation
│   ├── health_check.sh               # Docker HEALTHCHECK compatible
│   ├── pre_market_init.py            # Pre-open sequence: replay, subscribe, validate
│   ├── eod_shutdown.py               # 15:35 IST: archive, VACUUM, P&L summary
│   ├── paper_audit.py                # Sharpe/drawdown from paper logs
│   ├── db_analysis.py                # Record count validation
│   ├── position_reconcile.py         # Manual position sync check
│   └── capacity_check.py             # Validate RAM/disk before market open
│
├── migrations/
│   ├── 001_hot_db_schema.sql
│   ├── 002_archive_schema.sql
│   ├── 003_mysql_tables.sql
│   └── 004_live_parameters_seed.sql
│
├── data/                             # Mounted volumes
│   ├── hot/                          # → /dev/shm (tmpfs, 512 MB cap)
│   ├── archive/                      # SSD persistent
│   └── logs/                         # All log files, rotated
│
└── docs/
    ├── architecture.md
    ├── runbook.md                    # Disaster recovery procedures
    ├── strategies.md                 # Mathematical specifications
    ├── capacity_model.md             # RAM/CPU/disk budget proof
    └── testing_guide.md              # Testing pyramid methodology
```

### Key Structural Changes from Original

| Change | Reason |
|---|---|
| Added `core/lifecycle.py` | System-level state machine was completely absent |
| Added `core/market_phase.py` | NSE phases gate order types; original had zero phase awareness |
| Added `core/clock.py` | NTP drift was identified as Loophole L-05 |
| Added `ingestion/tick_validator.py` | Corrupt tick filtering was absent |
| Added `ingestion/angel_session.py` | TOTP/token lifecycle was scattered and incomplete |
| Added `execution/order_modifier.py` | Trailing SL requires modifyOrder; original had no path |
| Added `execution/margin_calculator.py` | Pre-trade margin validation was missing |
| Added `execution/position_reconciler.py` | No startup position sync existed |
| Added `risk/drawdown_guard.py` | Per-strategy auto-disable was absent |
| Added `risk/exposure_aggregator.py` | Real-time gross/net exposure was implicit, not tracked |
| Added `calibration/calibration_audit.py` | Parameter changes need provenance for compliance |
| Added `backtest/` entire directory | No backtesting existed in original plan |
| Added `config/instruments.yaml` | Universe selection was hardcoded |
| Added `config/market_phases.yaml` | Phase timings need to be configurable |
| Added `config/backtest.yaml` | Backtest parameters need configuration |

---

## Part III: Core Logics — Deep Architectural Specification

### 3.1 — System Lifecycle State Machine

The entire system operates through a deterministic finite state machine. No component may act outside its authorised phase.

```
                    ┌──────────┐
         ┌─────────│  COLD    │←────────────────────────┐
         │         │  BOOT    │                         │
         │         └────┬─────┘                         │
         │              │ Replay SSD→RAM                │
         │              │ Validate configs              │
         │              │ Decrypt secrets               │
         │              ▼                               │
         │         ┌──────────┐                         │
         │         │  INIT    │                         │
         │         │  PRE-    │                         │
         │         │  MARKET  │                         │
         │         └────┬─────┘                         │
         │              │ Angel session auth            │
         │              │ WebSocket subscribe           │
         │              │ Position reconciliation       │
         │              │ Margin validation             │
         │              ▼                               │
         │         ┌──────────┐    09:15 IST            │
         │         │  MARKET  │────────────────┐        │
         │         │  OPEN    │                │        │
         │         └────┬─────┘                │        │
         │              │                      │        │
         │              ▼                      │        │
         │         ┌──────────┐                │        │
    FATAL│         │  ACTIVE  │◄───────┐       │        │
    ERROR│         │  TRADING │        │       │        │
         │         └────┬─────┘        │       │        │
         │              │              │       │        │
         │              │  15:15 IST   │       │        │
         │              ▼              │       │        │
         │         ┌──────────┐        │       │        │
         │         │  WIND    │        │       │        │
         │         │  DOWN    │────────┘       │        │
         │         └────┬─────┘  (no new       │        │
         │              │         entries)     │        │
         │              │  15:30 IST           │        │
         │              ▼                      │        │
         │         ┌──────────┐                │        │
         │         │  EOD     │                │        │
         │         │  CLOSE   │                │        │
         │         └────┬─────┘                │        │
         │              │ Archive to SSD       │        │
         │              │ VACUUM RAM-disk      │        │
         │              │ P&L summary          │        │
         │              ▼                      │        │
         │         ┌──────────┐                │        │
         └────────►│  SHUTDOWN│────────────────┘        │
                   └──────────┘                         │
                        │                               │
                        └───────────────────────────────┘
```

**Critical rules:**
- No order placement allowed outside ACTIVE_TRADING
- No new entries after WIND_DOWN begins (15:15 IST)
- Exit management continues through WIND_DOWN
- EOD_CLOSE forces all remaining positions closed at market
- FATAL_ERROR from any state goes to SHUTDOWN with emergency position flatten
- State transitions are written to RAM-disk for crash recovery

### 3.2 — Market Phase Manager

NSE has distinct trading phases with different order type permissions:

| Phase | Time (IST) | Allowed Order Types | System Behaviour |
|---|---|---|---|
| Pre-open | 09:00–09:15 | LIMIT only (no SL) | Subscribe WS, replay history, no signals |
| Continuous | 09:15–15:30 | LIMIT, SL-L, MARKET | Full signal scanning + execution |
| Closing | 15:30–15:40 | LIMIT only | No new entries, exit management only |
| Post-close | 15:40+ | None | Archive, VACUUM, shutdown |
| Wind-down | 15:15–15:30 | All types | No new entries, manage exits only |

The phase manager is a singleton that all components query before any action. It uses monotonic clock (not wall clock) to avoid NTP drift issues.

### 3.3 — Memory Budget Model (24 GB VPS)

This is the capacity proof that was missing from the original plan:

| Component | Memory Estimate | Calculation |
|---|---|---|
| Python interpreter + base imports | ~200 MB | Fixed |
| Ring buffer (9000 instruments) | ~432 MB | 9000 × 10K ticks × 6 floats × 8 bytes |
| Candle aggregator working set | ~50 MB | 9000 × 20 candles × 6 fields |
| SQLite RAM-disk (WAL + pages) | ~512 MB | Capped via config |
| Signal engine working memory | ~300 MB | 9 strategies × numpy arrays |
| Risk kernel (correlation matrix) | ~50 MB | 20×20 positions × 50-bar windows |
| Execution engine + order queue | ~100 MB | Queue depth × order objects |
| Calibration loop | ~100 MB | Telemetry deques (100 per strategy) |
| OS + Docker overhead | ~2 GB | Kernel, cgroups, Docker daemon |
| **Safety headroom** | **~2 GB** | OOM prevention buffer |
| **Total** | **~5.7 GB** | Well within 24 GB |

**Conclusion:** The original plan's memory concern is manageable IF the ring buffer capacity is reduced from 10,000 to 2,000 ticks per instrument (sufficient for 5-min candle aggregation at normal tick rates) and the instrument universe is limited to 2,000 actively traded names rather than all 9,000. The config must enforce these caps.

**Revised ring buffer sizing:**
- 2,000 instruments × 2,000 ticks × 6 × 8 bytes = ~192 MB
- This is sustainable and leaves ample headroom

### 3.4 — Instrument Universe Selection

The original plan assumed 9,000 instruments. This is neither necessary nor efficient. The universe selector should filter based on:

**Tier 1 (Core — always subscribed):** Nifty 50 constituents
**Tier 2 (Extended — subscribed if RAM allows):** Nifty Next 50 + top 100 by average daily volume
**Tier 3 (Opportunistic — subscribed on demand):** Stocks that had ZONE_DECAY_WARNING or stop-hunt signals in the last 3 sessions

Selection criteria stored in `config/instruments.yaml`:
- Minimum average daily volume (e.g., 500K shares)
- Minimum average daily turnover (e.g., ₹5 crore)
- Maximum bid-ask spread (e.g., 0.10%)
- Exclusion: stocks in ban period, stocks with pending corporate actions
- Rebalance frequency: weekly, pre-market Sunday

### 3.5 — Data Ingestion Pipeline — Refined Logic

**Problem with original:** Single WebSocket → single ring buffer → single aggregator → single WriteQueue. This is a serial pipeline that can stall.

**Refined architecture:**

```
Angel One WebSocket
        │
        ▼
  ┌─────────────┐
  │  Tick       │  Filter: zero price, negative volume,
  │  Validator  │  timestamp > 60s stale, price > 20% band
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐
  │  Ring       │  Capacity: 2000 per instrument
  │  Buffer     │  Overflow: DROP_OLDEST + increment counter
  │  (numpy)    │  Alert if overflow_rate > 100/sec
  └──────┬──────┘
         │  Poll every 10ms
         ▼
  ┌─────────────┐
  │  Candle     │  Aggregate ticks → 5m OHLCV
  │  Aggregator │  Volume delta from bid/ask classification
  │             │  Phase-aware boundaries (pre-open ticks excluded)
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐
  │  Write      │  Batch: 50ms window OR 200 rows
  │  Queue      │  BEGIN IMMEDIATE transaction
  │             │  Dead-letter queue for failed writes
  │             │  Order state BYPASSES queue (sync write)
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐
  │  RAM-disk   │  /dev/shm/remora/remora_hot.db
  │  SQLite     │  WAL mode, synchronous=NORMAL
  │  (Hot Bus)  │  busy_timeout=30s
  └─────────────┘
```

**Tick validation rules (missing from original):**
1. Reject if price ≤ 0 or price is NaN
2. Reject if volume < 0
3. Reject if timestamp differs from server time by > 60 seconds
4. Reject if price is outside ±20% of previous tick (circuit band protection)
5. Reject if instrument token is not in subscribed universe
6. Log all rejections with reason code for debugging

**Ring buffer overflow policy:**
- When buffer is full, overwrite oldest tick (ring semantics)
- Increment an overflow counter per instrument
- If overflow rate exceeds 100 ticks/second for any instrument, emit WARNING
- If overflow rate exceeds 1000 ticks/second, emit CRITICAL and consider unsubscribing that instrument temporarily

### 3.6 — Angel One Session Lifecycle

This was severely underspecified in the original. The complete state machine:

```
  ┌──────────┐
  │  LOGGED  │
  │  OUT     │
  └────┬─────┘
       │  TOTP generation (pyotp) + API key + client ID
       ▼
  ┌──────────┐
  │  AUTH    │──── Auth failure ──→ RETRY (max 3, then HALT)
  │  PENDING │
  └────┬─────┘
       │  Session token + feed token received
       ▼
  ┌──────────┐
  │  SESSION │──── Token TTL check every 5 minutes
  │  ACTIVE  │──── If TTL < 30 min → refresh
  └────┬─────┘
       │  WebSocket connect + chunked subscribe
       ▼
  ┌──────────┐
  │  FEED    │──── Stale > 5s → RECONNECT
  │  LIVE    │──── 02:00 IST server reset → FULL_RECONNECT
  └────┬─────┘
       │  SIGTERM or market close
       ▼
  ┌──────────┐
  │  DRAIN   │  Wait 8 seconds for final tick flush
  │  & CLOSE │  Explicit close_connection()
  └──────────┘
```

**Critical implementation details:**
- TOTP must be generated fresh at each auth attempt (30-second window)
- Feed token has a TTL of approximately 6 hours; schedule proactive refresh at 5 hours
- The 02:00 IST Angel One server reset must trigger a full reconnect cycle, not an internal retry
- `MAX_RETRY_ATTEMPT = 0` on the SmartWebSocketV2 library to force external reconnection (as documented in v7.3.8 fix)
- Chunked subscription: exactly 500 tokens per batch, 250ms gap between batches
- A `_did_subscribe` guard flag prevents duplicate subscription on reconnect (v7.3.8 Token Doubling fix)

### 3.7 — Order State Machine (Complete)

The original plan had PENDING→FILLED→CLOSED. The actual Angel One order lifecycle requires 9 states and 14 transitions:

```
                    ┌─────────────┐
                    │  CREATED    │  Signal approved by risk kernel
                    └──────┬──────┘
                           │ submit to queue
                           ▼
                    ┌─────────────┐
                    │  QUEUED     │  Waiting in OrderExecutor queue
                    └──────┬──────┘
                           │ placeOrder API call
                           ▼
                    ┌─────────────┐
              ┌─────│  SUBMITTED  │─────┐
              │     └──────┬──────┘     │
              │            │            │
         API error    Angel ack    API timeout
              │            │            │
              ▼            ▼            ▼
       ┌──────────┐ ┌──────────┐ ┌──────────┐
       │ REJECTED │ │  OPEN    │ │  UNKNOWN │──→ Reconcile
       └──────────┘ └────┬─────┘ └──────────┘   on restart
                         │
                    ┌────┴────┐
                    │         │
               Partial     Full fill
               fill           │
                    │         │
                    ▼         ▼
             ┌──────────┐ ┌──────────┐
             │ PARTIAL  │ │  FILLED  │
             │ _FILLED  │ └────┬─────┘
             └────┬─────┘      │
                  │            │ SL-L placed
                  │            ▼
                  │     ┌──────────┐
                  └────►│  BRACKET │  Entry + SL-L active
                        │  ACTIVE  │
                        └────┬─────┘
                             │
                    ┌────────┼────────┐
                    │        │        │
               TP hit   SL hit   EOD close
                    │        │        │
                    ▼        ▼        ▼
              ┌──────────────────────────┐
              │        CLOSED            │
              │  (with close_reason:     │
              │   TP / SL / EOD /       │
              │   TRAIL / REGIME_HALT / │
              │   MANUAL)               │
              └──────────────────────────┘
```

**Additional states for robustness:**
- `CANCEL_PENDING` — when cancel request sent but not yet acknowledged
- `MODIFY_PENDING` — when trailing SL modification sent
- `UNKNOWN` — when API timeout leaves state ambiguous; must reconcile with broker on next poll

**Transition rules:**
- No transition skips states (CREATED cannot jump to FILLED)
- Every transition is written to RAM-disk synchronously (bypasses WriteQueue)
- Every transition emits an event on the internal event bus
- REJECTED and UNKNOWN states trigger the reconciliation engine

### 3.8 — Signal Priority Arbitration

When multiple strategies fire for the same ticker in the same scan cycle, the original plan had no arbitration. The refined logic:

**Priority order (highest first):**
1. S9 — FADING_STOP_HUNT (adversarial, time-critical, short-lived opportunity)
2. S8 — ZONE_DECAY_SNIPER (zone collapse is irreversible, must act now)
3. S7 — ENTROPY_HARVESTER (grid boundaries are fleeting)
4. S1 — STRUCTURAL_HV_FVG (institutional footprint, high conviction)
5. S2 — MOMENTUM_PAIRING (breakout confirmation)
6. S3 — GOLDEN_CONFLUENCE (triple intersection, rare but high quality)
7. S4 — RUNWAY_MOMENTUM (pure breakout)
8. S5 — VOLATILITY_SQUEEZE (compression→expansion)
9. S6 — CYCLOID_KINEMATIC (standalone kinematic, lowest conviction)

**Arbitration rules:**
- Only ONE signal per ticker per scan cycle
- If two signals of the same priority fire, prefer the one with higher nb_prob
- If nb_prob is equal, prefer the one with larger runway%
- The losing signal is logged as `ARBITRATION_LOST` for audit
- Directional conflict: if S1 fires LONG and S9 fires SHORT for same ticker, S9 wins (adversarial trumps directional) but BOTH are logged

### 3.9 — Execution Engine Scan Cycle (Refined 30-Second Loop)

```
Every 30 seconds:
│
├── Phase 0: Pre-flight checks
│   ├── Verify market phase == CONTINUOUS
│   ├── Check GLOBAL_HALT flag in RAM-disk
│   ├── Check broker circuit breaker state
│   ├── Fetch live India VIX (yfinance, with fallback)
│   └── If any check fails → skip scan, log reason
│
├── Phase 1: Refresh local caches
│   ├── Load unmitigated Order Blocks from RAM-disk
│   ├── Load latest quant_predictive_signals (nb_prob)
│   ├── Load latest cycloid/swing/smart signals
│   ├── Compute delta percentiles for session
│   └── Compute EWRV for all tracked instruments
│
├── Phase 2: Run strategy scanners (parallel, isolated)
│   ├── S1 scanner → list[S1Signal]
│   ├── S2 scanner → list[S2Signal]
│   ├── ... (all 9, each in try/except)
│   └── Collect all valid signals
│
├── Phase 3: Signal arbitration
│   ├── Group signals by ticker
│   ├── Apply priority arbitration per ticker
│   └── Produce final signal list (max 1 per ticker)
│
├── Phase 4: Risk kernel validation (per signal)
│   ├── Kelly-LVaR position sizing
│   ├── Portfolio heat check (η_t < 0.50)
│   ├── Correlation veto (r > 0.70 against open positions)
│   ├── VIX regime gate
│   ├── Per-strategy drawdown check
│   ├── Cooldown check (60 min per ticker)
│   └── Margin sufficiency check
│
├── Phase 5: Order submission
│   ├── Build trade dict with all parameters
│   ├── Submit to OrderExecutor queue (non-blocking)
│   └── Log ENTER signal with full context
│
├── Phase 6: Exit management
│   ├── Check all open positions
│   ├── TP hit? → close
│   ├── Trailing SL update needed? → modify order
│   ├── EOD approaching? → force close at 15:20
│   └── Time exit at 15:15
│
└── Phase 7: Telemetry
    ├── Record scan latency
    ├── Update MFE/MAE for open positions
    ├── Write heartbeat to RAM-disk
    └── Emit metrics
```

---

## Part IV: Mathematical Foundations — Complete Specification

### 4.1 — EWRV (Exponentially Weighted Realized Variance)

**Purpose:** Replace static ATR with a decay-weighted variance measure that adapts to the market's "speed of information."

**Formula:**
σ²_{t,i} = λ · σ²_{t-1,i} + (1-λ) · r²_{t,i}

Where:
- λ = 0.94 (RiskMetrics standard, optimised for 1-day variance decay)
- r_{t,i} = ln(P_t / P_{t-1}) is the log return
- Computed over 5-minute close prices

**Dynamic confirmation window τ:**
τ_{i,t} = τ_min + (τ_max - τ_min) · exp(-κ · σ²_{t,i} / σ̄²_i)

Where:
- τ_min = 5 minutes (high volatility → fast confirmation)
- τ_max = 20 minutes (low volatility → allow accumulation time)
- κ = 0.30 (sensitivity parameter, hot-swappable)
- σ̄²_i = mean EWRV over the session

**Outlier clipping (Election Day / extreme events):**
Returns r_t are clipped to ±5 × MAD (Median Absolute Deviation) before EWRV computation to prevent halt-auction gaps from corrupting the volatility surface.

**Edge cases to handle:**
- First candle of session: no prior return → use SSD archive replay data
- Zero-return candles: r = 0 contributes nothing; this is correct
- σ̄²_i = 0 (all candles identical): fall back to τ = (τ_min + τ_max) / 2

### 4.2 — Kelly-LVaR Position Sizing

**Three independent constraints intersected:**

**Constraint 1: Fractional Kelly**
f_raw = (p(b+1) - 1) / b

Where:
- p = win probability (from Variance Profiler's sliding window, last 100 trades)
- b = average reward/risk ratio (MFE / |MAE|)
- Applied as Quarter-Kelly: f_kelly = 0.25 × f_raw

**Floor guard (missing from original):**
- If p ≤ 0 or b ≤ 0, f_kelly = 0 (no trade)
- If f_raw < 0, f_kelly = 0 (negative edge → no trade)
- Maximum f_kelly capped at 0.10 (10% of capital, regardless of Kelly output)

**Constraint 2: Liquidity Value at Risk**
f_lvar = VaR_Budget / (z_{0.95} · σ_{5m} · √78 · Capital)

Where:
- VaR_Budget = 0.02 × Capital (2% maximum equity at risk)
- z_{0.95} = 1.645
- σ_{5m} = standard deviation of 5-minute returns
- √78 scales 5-minute volatility to full trading day (78 five-minute bars in 6.5 hours)

**Floor guard (critical, missing from original):**
- If σ_{5m} < 0.0001, clamp to 0.0001 (prevent division explosion)
- If σ_{5m} > 0.03, clamp to 0.03 (election day ceiling)

**Constraint 3: Portfolio Heat Scaling**
f_deploy = f_raw × (1 - η_t)

Where η_t = gross_exposure / total_capital

**Final deployment:**
f_final = min(f_kelly × f_dd, f_lvar, hard_cap)

Where:
- f_dd = drawdown scaling factor (1.0 if no drawdown, linearly decreasing to 0.5 at 2% drawdown)
- hard_cap = 0.35 (never more than 35% of capital in one trade)

**Quantity calculation:**
Q = floor(f_final × Capital × Leverage / Price)

Where Leverage = 5 (Angel One intraday margin multiplier)

**Validation:**
- Q must be ≥ 1 (minimum 1 share)
- Q × Price must be ≥ ₹5,000 (minimum order value)
- Q × Price must be ≤ 35% of capital
- If any validation fails, Q = 0 and trade is skipped

### 4.3 — Yang-Zhang Volatility (Strategy 5)

**Purpose:** Capture overnight + intraday variance for squeeze detection.

YZ = √(V_overnight + k · V_close + (1-k) · V_rs)

Where:
- V_overnight = Var(ln(O_t / C_{t-1}))
- V_close = Var(ln(C_t / O_t))
- V_rs = Mean(ln(H_t/C_t)·ln(H_t/O_t) + ln(L_t/C_t)·ln(L_t/O_t)) (Rogers-Satchell)
- k = 0.34 / (1.34 + (n+1)/(n-1))

**Compression detection:** YZ_t < YZ_{t-1} < YZ_{t-2} for ≥ 3 consecutive bars
**Expansion trigger:** YZ_t ≥ 1.5 × mean(YZ over session)
**Confirmation:** Delta_growth ≥ 1.20× (institutional absorption during squeeze)

### 4.4 — Order Flow Imbalance (OFI) & Iceberg Detection

OFI = ΔV_bid - ΔV_ask / Total_Volume

**Iceberg detection conditions:**
- OFI > τ_OFI (configurable, default 0.10)
- Price velocity = |ΔPrice| / ΔTime < 0.0005
- Volume is significantly above average

**Interpretation:** High OFI with near-zero price velocity proves a hidden institutional limit order is absorbing all incoming market orders without moving price.

### 4.5 — Kaplan-Meier Survival (Strategy 8: Zone Decay)

**Purpose:** Model the probability that a structural zone (Order Block) survives additional price tests.

S(t) = Π_{i: t_i ≤ t} (1 - d_i / n_i)

Where:
- t_i = time of i-th zone test
- d_i = number of zones that failed at time t_i
- n_i = number of zones at risk just before t_i

**Implementation in Remora:**
- Track all Order Blocks that have been tested (price touched the zone)
- A zone "fails" when price closes through it (mitigation)
- Compute survival probability for each active zone
- If survival_prob < threshold (default 0.05, hot-swappable), emit ZONE_DECAY_WARNING

### 4.6 — Naive Bayes Probability Gate (Quant Predictive)

**Purpose:** Provide a probabilistic regime classification to gate directional strategies.

**Features used (deterministic, no ML training at runtime):**
- EWRV ratio (current vs mean)
- Delta percentile rank
- Volume ratio (current vs SMA-20)
- Price position relative to VWAP
- Time of day (categorical: open, mid, close)

**Gate logic:**
- If nb_prob > 0.60 → directional strategies (S1-S6) are enabled
- If nb_prob ≤ 0.55 → entropy regime; S7 (Entropy Harvester) is enabled
- If 0.55 < nb_prob ≤ 0.60 → transitional; all strategies operate with reduced sizing

**Freshness constraint:**
- nb_prob must be < 5 minutes old
- If stale → BYPASS (do not veto, but log warning)
- If no data at all → BYPASS with reduced position sizing (50% of normal)

### 4.7 — Runway Calculation

Runway% = ((Supply_low - Price_breakout) / Price_breakout) × 100

**Special cases:**
- If no Bearish OB exists above breakout price → Runway = INFINITE
- INFINITE runway triggers 50% risk weight (vs standard 20%)
- If Runway% < 5.0% → trade is VETOED regardless of other signal quality

**For SHORT signals:**
Runway% = ((Price_breakout - Demand_high) / Price_breakout) × 100
- If no Bullish OB exists below breakout price → Runway = INFINITE

### 4.8 — Volatility Z-Score (Cycloid Mean Reversion)

Z = (ln(σ²_current) - ln(σ²_mean)) / σ_historical

**Interpretation:**
- Z > 3.0 → 99.87th percentile anomaly → directional move is exhausting → mean reversion imminent
- Only valid when nb_prob < 0.55 (boxed/entropy market)
- NEVER use during macro breakouts (FOMC, election results, budget day)

---

## Part V: Risk Management — Complete Methodology

### 5.1 — Five-Layer Risk Defence

```
Layer 1: PRE-TRADE (Before order enters queue)
├── Kelly-LVaR sizing with floor guards
├── Portfolio heat check (η_t < 50%)
├── Correlation veto (Pearson r > 0.70)
├── VIX regime gate
├── Per-strategy drawdown check
├── Cooldown enforcement (60 min per ticker)
└── Margin sufficiency pre-validation

Layer 2: ORDER PLACEMENT (At broker API boundary)
├── Rate limiter (3 orders/second token bucket)
├── LIMIT buffer (dynamic, 0.05%–0.50%)
├── SL-L bracket immediate placement
├── Max slippage guard (1.0% in paper mode)
└── Broker health circuit breaker (3 consecutive errors)

Layer 3: POSITION MANAGEMENT (While position is open)
├── MFE/MAE tracking every 30 seconds
├── Trailing SL activation at +1R
├── Trailing distance: MFE - 0.5R
├── Take profit at 2R
├── EOD force close at 15:20 IST
└── Time exit at 15:15 IST

Layer 4: PORTFOLIO LEVEL (Aggregate)
├── Max gross exposure: 50% of capital
├── Max daily loss: 3% of capital → HALT ALL
├── Max daily trades: 20
├── Correlation matrix across all open positions
└── VIX tiered response (see below)

Layer 5: SYSTEM LEVEL (Kill switches)
├── GLOBAL_HALT flag in RAM-disk (< 1ms activation)
├── Broker circuit breaker (3 errors → read-only mode)
├── DB circuit breaker (P95 > 500ms → exponential backoff)
├── Ingestion watchdog (5s stale → failover)
└── Manual kill via Streamlit dashboard or config flag
```

### 5.2 — VIX Tiered Response Matrix

| VIX Level | Tier | Action | Affected Strategies |
|---|---|---|---|
| < 12 | CALM | All strategies active, standard sizing | All |
| 12–15 | NORMAL | All strategies active, standard sizing | All |
| 15–20 | CAUTION | Restrict universe to Nifty 50 only | S1-S6 restricted; S7-S9 continue |
| 20–25 | ELEVATED | Restrict to top 20 Nifty names, reduce sizing by 50% | All reduced |
| 25–30 | HIGH | New entries halted, manage exits only | None (exit only) |
| > 30 | CRITICAL | Total halt, flatten all positions | None (emergency close) |

**Hysteresis:** To prevent flip-flopping, each tier has a 2-point hysteresis band. E.g., entering CAUTION at VIX > 15, exiting CAUTION only when VIX < 13.

**VIX source fallback chain:**
1. yfinance ^INDIAVIX (primary)
2. Angel One VIX API (if available)
3. Last known VIX (with staleness warning if > 30 minutes old)
4. Manual override via INDIA_VIX_OVERRIDE env variable
5. If all fail → assume VIX = 20 (CAUTION tier, conservative default)

### 5.3 — Per-Strategy Drawdown Guard

Each strategy maintains its own performance tracker:

| Metric | Threshold | Action |
|---|---|---|
| Consecutive losses | ≥ 5 | Disable strategy for rest of session |
| Session P&L | < -1.5% of capital allocated to strategy | Disable for rest of session |
| Rolling Sharpe (20 trades) | < 0 | Reduce sizing by 50% |
| Rolling Sharpe (20 trades) | < -0.5 | Disable for rest of week |
| Max drawdown (20 trades) | > 3% | Disable until manual review |

Re-enablement requires:
- Manual override via config change, OR
- Next trading session starts with clean state (auto-reset at EOD)

### 5.4 — Correlation Veto — Optimised Implementation

**Problem with original:** Computing Pearson correlation for all open positions every 30 seconds is O(n²) with 50-bar windows.

**Refined approach:**
- Maintain a cached correlation matrix, updated incrementally
- Only recompute when a new position is opened or an existing one closes
- Use the last 50 five-minute returns for each instrument
- Pre-compute the correlation of new candidate against all open positions BEFORE the scan cycle
- Store in a dictionary: `{(ticker_a, ticker_b): (r, computed_at)}`
- Invalidate cache entry if either ticker's candle data updates

**Veto rule:** If |r| > 0.70 for ANY pair (new_candidate, existing_position), the new entry is vetoed.

### 5.5 — Margin Pre-Validation

Before any order is submitted to Angel One:

1. Fetch available margin via `rmsLimit()` API
2. Compute required margin: (Quantity × Price) / Leverage
3. Add 10% buffer for price movement between signal and fill
4. If required > available → skip trade, log `MARGIN_INSUFFICIENT`
5. Cache margin for 60 seconds to avoid excessive API calls
6. If margin API fails → use last known margin with 20% haircut

---

## Part VI: Error Handling & Resilience Patterns

### 6.1 — Exception Hierarchy

```
RemoraError (base)
├── ConfigValidationError        # YAML parse/schema failure
├── DomainViolationError         # Math constraint violated (ob_high < ob_low)
├── IngestionError               # WebSocket, ring buffer, candle issues
│   ├── TickValidationError      # Corrupt tick rejected
│   ├── RingBufferOverflowError  # Buffer capacity exceeded
│   └── CandleAggregationError   # OHLCV formation failure
├── ExecutionError               # Order lifecycle failures
│   ├── OrderRejectedError       # Broker rejected order
│   ├── OrderTimeoutError        # No response from broker
│   ├── MarginInsufficientError  # Pre-trade margin check failed
│   └── OrderStateError          # Invalid state transition
├── RiskBreachError              # Risk limit violated
│   ├── PortfolioHeatError       # Gross exposure exceeded
│   ├── CorrelationVetoError     # Pairwise correlation too high
│   └── DrawdownLimitError       # Strategy or global drawdown hit
├── CircuitBreakerTrippedError   # Any circuit breaker activated
├── DataStalenessError           # Data exceeds freshness threshold
├── BrokerConnectionError        # Angel One API unreachable
└── PhaseViolationError          # Action attempted outside valid market phase
```

### 6.2 — Error Handling Strategy per Component

| Component | Error Type | Response | Recovery |
|---|---|---|---|
| WebSocket | Connection lost | Log, wait 2s, full reconnect | Automatic, max ∞ retries |
| WebSocket | Auth failure | Log, retry 3×, then HALT | Manual intervention |
| Ring buffer | Overflow | Drop oldest, increment counter | Automatic |
| WriteQueue | SQLite lock | Retry with exponential backoff (2^n, max 300s) | Automatic |
| WriteQueue | Dead letter | Move to DLQ table, continue | Manual review at EOD |
| Strategy scanner | Any exception | Isolate in try/except, log, continue other strategies | Automatic |
| Order executor | API timeout | Mark order UNKNOWN, reconcile on next cycle | Semi-automatic |
| Order executor | 3 consecutive errors | Trip breaker, disable execution, cancel in-flight | Manual restart |
| Risk kernel | VIX fetch failure | Use last known, apply 20% haircut to sizing | Automatic |
| Config loader | YAML parse error | Keep last valid config, log CRITICAL | Manual fix |
| Config loader | Hot-reload race | Atomic swap: load into temp dict, then swap reference | Automatic |

### 6.3 — Graceful Degradation Hierarchy

When components fail, the system degrades in priority order:

```
Level 0: FULL OPERATION
  All 9 strategies, live execution, full risk kernel

Level 1: REDUCED STRATEGIES
  One or more strategies disabled due to drawdown
  Remaining strategies continue normally

Level 2: PAPER MODE FALLBACK
  Broker circuit breaker tripped
  All signals logged as PAPER, no live orders
  Automatic: execution_enabled → False

Level 3: READ-ONLY MONITORING
  DB circuit breaker tripped OR ingestion stalled
  No new signals, no orders
  Monitor existing positions only

Level 4: EMERGENCY FLATTEN
  VIX > 30 OR global drawdown > 3%
  Close all positions at market
  No new entries

Level 5: SHUTDOWN
  Fatal error OR manual kill
  Cancel all open orders
  Close all positions if possible
  Archive state to SSD
  Exit
```

### 6.4 — Crash Recovery Procedure

**Scenario: VPS reboots mid-session**

1. Docker restarts all containers (restart: unless-stopped)
2. Lifecycle state machine reads last state from SSD archive
3. Pre-market init sequence runs:
   a. Replay last 4 hours of candles from SSD → RAM-disk
   b. Reconnect Angel One WebSocket
   c. Re-subscribe instruments in chunks
   d. **Position reconciliation:** Query Angel One positions API, compare with RAM-disk live_orders table
   e. For any position in broker but not in RAM-disk → add to tracking
   f. For any position in RAM-disk but not in broker → mark as CLOSED (broker auto-squared)
4. Resume scanning from current market phase
5. Signal deduplication: Load all previously fired signals from SSD archive into alerted dictionary

---

## Part VII: Debugging Methodology

### 7.1 — Structured Log Format

Every log line follows a deterministic pipe-delimited format:

```
TIMESTAMP | LEVEL | COMPONENT | EVENT | TICKER | KEY=VALUE pairs
```

Examples:
```
2026-07-29 09:30:15 | INFO | s1_scanner | ENTER_STRUCTURAL | RELIANCE | ob_id=42 | type=Bullish | confirming=CYCLOID | conf_price=2920.00 | dyn_window=8.3min | runway=INFINITE | nb_prob=0.72
2026-07-29 09:30:15 | INFO | order_exec | ORDER_PLACED | RELIANCE | angel_order_id=230423000012345 | qty=50 | side=BUY | type=LIMIT | price=2921.46
2026-07-29 09:30:16 | WARN | risk_kernel | VETO_CORRELATION | INFY | r_with_RELIANCE=0.82 | threshold=0.70
```

### 7.2 — Debugging Decision Trees

**Problem: No signals firing**

```
Check 1: Is ingestion alive?
  → tail -f data/logs/ingestion.log
  → Look for "CANDLE_FLUSH" events
  → If none → WebSocket issue → check angel_session state

Check 2: Are candles being written?
  → sqlite3 /dev/shm/remora/remora_hot.db "SELECT COUNT(*) FROM live_candles WHERE ts > strftime('%s','now') - 600"
  → If 0 → WriteQueue issue → check for "database is locked" errors

Check 3: Are strategies enabled?
  → Check each strategy YAML: enabled: true
  → Check GLOBAL_HALT flag: SELECT value FROM live_parameters WHERE key='GLOBAL_HALT'
  → If 1.0 → kill switch is active

Check 4: Is nb_prob gating blocking everything?
  → grep "NB_GATE_REJECT" data/logs/signals.log
  → If all rejected → check quant_predictive_signals table freshness

Check 5: Is VIX halting entries?
  → grep "VIX_HALT" data/logs/risk_kernel.log
  → If VIX > 30 → all entries blocked by design
```

**Problem: Orders placed but not filling**

```
Check 1: Order type and price
  → grep "ORDER_PLACED" data/logs/execution_v2.log
  → Verify LIMIT price includes buffer (signal ± 0.05%)
  → If price is too far from market → order sits unfilled

Check 2: Market phase
  → Is it pre-open (09:00-09:15)? SL orders not allowed
  → Is it closing (15:30+)? Only LIMIT allowed

Check 3: Instrument liquidity
  → Check bid-ask spread for the ticker
  → If spread > 0.10%, LIMIT at 0.05% buffer will not fill
  → Solution: Dynamic limit buffer should have widened

Check 4: Angel One API response
  → grep "ORDER_RESPONSE" data/logs/execution_v2.log
  → Check for error codes: 200 = success, others = rejection reason
```

**Problem: High slippage in paper mode**

```
Check 1: Signal staleness
  → Compare signal timestamp with current candle timestamp
  → If > 2 minutes old → signal is stale, price has moved

Check 2: Volume at signal time
  → Low volume → wide spreads → high slippage expected
  → Check if VIX > 15 (spreads widen)

Check 3: Max slippage guard
  → Is MAX_SLIPPAGE_PCT = 1.0% enforced?
  → grep "PAPER_REJECT" data/logs/execution_v2.log
  → Fills > 1% should be rejected, not logged

Check 4: Direction-aware slippage calculation
  → LONG: slippage = fill_price - signal_price (positive = adverse)
  → SHORT: slippage = signal_price - fill_price (positive = adverse)
  → Verify formula in paper_trader logic
```

### 7.3 — Health Check Endpoints (Docker HEALTHCHECK)

Each container exposes a health check script:

```
healthy:
  - RAM-disk file exists and is writable
  - Last heartbeat < 5 seconds old
  - WebSocket connected (or reconnecting)
  - WriteQueue depth < 1000
  - No circuit breaker tripped

unhealthy:
  - RAM-disk missing or read-only
  - Heartbeat stale > 30 seconds
  - WebSocket disconnected > 60 seconds
  - WriteQueue depth > 5000
  - Broker circuit breaker tripped
```

Docker compose health check:
```yaml
healthcheck:
  test: ["CMD", "/app/scripts/health_check.sh"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 60s
```

### 7.4 — Pre-Market Validation Checklist

Run automatically at 08:45 IST every trading day:

| Check | Pass Criteria | Action on Fail |
|---|---|---|
| SSD archive exists | File present, > 0 bytes | Abort, alert |
| RAM-disk writable | Write + read test file | Abort, alert |
| Angel One auth | Successful TOTP + session | Retry 3×, then abort |
| Instrument tokens | > 0 tokens resolved | Abort, alert |
| Config checksums | All YAML files match expected hash | Warn, use defaults |
| NTP sync | Clock drift < 1 second | Warn, use monotonic clock |
| Disk space (SSD) | > 5 GB free | Warn, clean old archives |
| RAM available | > 8 GB free | Warn, reduce universe |
| Previous session archived | EOD archive completed | Warn, run manual archive |
| VIX data accessible | yfinance returns data | Use fallback |

---

## Part VIII: 7-Day Implementation Plan (Refined)

### Day 1: Foundation, Config, and Core Infrastructure

| Block | Task | Deliverable |
|---|---|---|
| Morning | Dockerfile, docker-compose.yml, requirements.txt | Buildable container |
| Morning | All 15+ YAML config files | Complete control plane |
| Morning | config_manager.py with atomic hot-reload, checksum validation | Config system |
| Afternoon | exceptions.py (12 classes), constants.py (all enums) | Type system |
| Afternoon | clock.py (monotonic + NTP check), lifecycle.py (state machine) | Core infra |
| Afternoon | market_phase.py, secrets.py, health.py | Core infra |
| Evening | event_bus.py (asyncio pub/sub) | Communication backbone |
| Evening | Unit tests for config loader, lifecycle, market phase | Validation |
| Evening | Verify Docker build + boot + config load | Smoke test |

**Day 1 gate:** Container boots, loads all YAML, lifecycle state machine reaches INIT, market phase tracker returns correct phase for current time.

### Day 2: Data Ingestion Pipeline

| Block | Task | Deliverable |
|---|---|---|
| Morning | ring_buffer.py with overflow detection, tick_validator.py | Tick processing |
| Morning | angel_session.py (TOTP, token lifecycle, reconnect FSM) | Broker auth |
| Morning | angel_websocket.py (single WS, chunked subscribe, drain) | Data feed |
| Afternoon | candle_aggregator.py (phase-aware, volume delta) | Candle formation |
| Afternoon | write_queue.py (batched, dead-letter, sync bypass) | Write path |
| Afternoon | local_bus.py (RAM-disk SQLite, WAL, param hot-swap) | Hot bus |
| Evening | tick_reconciliation.py, replay_engine.py | State recovery |
| Evening | Integration test: simulated ticks → candles → RAM-disk | Pipeline validation |

**Day 2 gate:** Simulated tick stream produces correct 5-minute candles in RAM-disk. WriteQueue batches correctly. Replay from SSD populates RAM-disk.

### Day 3: Mathematical Engines

| Block | Task | Deliverable |
|---|---|---|
| Morning | volatility_core.py (EWRV, Yang-Zhang, dynamic τ, outlier clipping) | Vol engine |
| Morning | delta_core.py (percentile ranking, OFI, velocity, fallback logic) | Flow engine |
| Morning | order_block_detector.py (HV+FVG, mitigation tracking, freshness) | OB engine |
| Afternoon | cycloid_engine.py (5 setups, vectorised, relative basis) | Kinematic engine |
| Afternoon | swing_engine.py (breakout, bull_pct, runway) | Structure engine |
| Afternoon | smart_block_engine.py (delta, POC, YZ vol) | Order flow engine |
| Evening | quant_predictive.py (Naive Bayes gate, freshness, bypass) | Regime gate |
| Evening | zone_decay.py (Kaplan-Meier survival) | Decay engine |
| Evening | Unit tests for all math (known inputs → expected outputs) | Math validation |

**Day 3 gate:** Each engine produces correct output for synthetic candle data. EWRV matches hand-calculated values. Kelly sizing produces expected quantities.

### Day 4: The 9 Strategies

| Block | Task | Deliverable |
|---|---|---|
| Morning | base_scanner.py (abstract contract), strategy_registry.py (YAML loader) | Framework |
| Morning | S1 (Structural HV+FVG), S2 (Momentum Pairing) | Directional |
| Morning | S3 (Golden Confluence), S4 (Runway Momentum) | Directional |
| Afternoon | S5 (Volatility Squeeze), S6 (Cycloid Kinematic) | Directional |
| Afternoon | S7 (Entropy Harvester), S8 (Zone Decay Sniper) | Adversarial |
| Afternoon | S9 (Stop-Hunt Fade) | Adversarial |
| Evening | strategy_lifecycle.py (per-strategy drawdown tracking, auto-disable) | Lifecycle |
| Evening | Signal priority arbitration logic | Arbitration |
| Evening | Unit tests: each strategy with synthetic data, gate pass/fail | Strategy validation |

**Day 4 gate:** All 9 strategies fire correctly on synthetic data. Gates veto correctly. Arbitration resolves conflicts. Drawdown guard disables after 5 consecutive losses.

### Day 5: Execution Engine & Risk Kernel

| Block | Task | Deliverable |
|---|---|---|
| Morning | order_state_machine.py (9 states, 14 transitions) | Order FSM |
| Morning | order_executor.py (async queue, rate limiter, token bucket) | Order daemon |
| Morning | order_modifier.py (trailing SL modification) | Modification path |
| Afternoon | broker_adapter.py (abstract), angel_adapter.py (SmartAPI) | Broker layer |
| Afternoon | margin_calculator.py, position_reconciler.py | Pre-trade checks |
| Afternoon | paper_trader.py (slippage model, fill simulation) | Paper mode |
| Evening | kelly_lvar.py (with all floor guards), portfolio_heat.py | Sizing |
| Evening | correlation_veto.py (cached matrix), vix_regime.py (multi-source) | Risk gates |
| Evening | circuit_breaker.py (priority cascade), drawdown_guard.py | Breakers |
| Evening | exit_gate.py (TP, trailing, EOD, time exit) | Exit management |

**Day 5 gate:** Paper mode produces correct slippage logs. Kelly sizing matches hand calculations. Circuit breakers trip and recover correctly. Order state machine transitions are valid.

### Day 6: Execution Engine Integration & Calibration Loop

| Block | Task | Deliverable |
|---|---|---|
| Morning | execution_engine.py (30s scan loop, 7 phases) | Main engine |
| Morning | Wire all 9 strategies → risk kernel → order executor | Full pipeline |
| Morning | Signal-to-order integration test | Pipeline test |
| Afternoon | telemetry_collector.py (MFE/MAE on trade close) | Telemetry |
| Afternoon | variance_profiler.py (MAE drift, failure probability) | Calibration |
| Afternoon | regime_calibrator.py (EWRV threshold adjustment) | Calibration |
| Afternoon | parameter_hotswap.py, calibration_audit.py | Hot-swap |
| Evening | archiver.py (EOD, VACUUM, 14-day retention) | Archival |
| Evening | sync_worker.py (watermark delta sync) | Sync |
| Evening | Full integration test: tick → signal → risk → paper order | End-to-end |

**Day 6 gate:** Complete pipeline runs end-to-end in paper mode. Calibration loop adjusts parameters based on synthetic telemetry. EOD archive completes.

### Day 7: Hardening, Testing, Backtest & Deployment

| Block | Task | Deliverable |
|---|---|---|
| Morning | Monitoring: metrics.py, telegram_alerts.py, audit_logger.py | Observability |
| Morning | capacity_monitor.py (RAM, disk, CPU tracking) | Resource guard |
| Morning | Backtest framework: data_loader, replay_simulator, fill_simulator | Backtest |
| Afternoon | Run backtest on 10 sessions of archived data | Validation |
| Afternoon | Performance report: Sharpe, drawdown, MFE/MAE per strategy | Report |
| Afternoon | Parameter sweep on S1 and S7 | Optimisation |
| Evening | All unit tests, integration tests, replay tests | Test suite |
| Evening | Docker compose final validation, health checks | Deployment |
| Evening | Runbook documentation, disaster recovery procedures | Documentation |
| Evening | Paper trading dry run (full session simulation) | Final gate |

**Day 7 gate:** All tests pass. Backtest produces Sharpe > 1.0 on historical data. Paper mode runs a full simulated session without errors. Docker stack starts cleanly with health checks.

---

## Part IX: Docker Orchestration (Refined)

### Container Topology

```yaml
# docker-compose.yml structure (conceptual)
services:
  remora-ingest:
    # WebSocket, ring buffer, candle aggregator, WriteQueue
    # tmpfs: /dev/shm/remora (512 MB)
    # restart: unless-stopped
    # healthcheck: heartbeat freshness

  remora-engine:
    # Execution engine, strategies, risk kernel, order executor
    # Depends on: remora-ingest (healthy)
    # Reads: RAM-disk (read-only for candles, read-write for orders)
    # restart: unless-stopped

  remora-calibration:
    # Variance profiler, regime calibrator, parameter hotswap
    # Depends on: remora-engine (healthy)
    # Reads: RAM-disk telemetry
    # restart: unless-stopped

  remora-archiver:
    # EOD archival, SSD sync, VACUUM
    # Runs as cron-like scheduler within container
    # Depends on: remora-ingest (healthy)
    # restart: unless-stopped

  remora-monitor:
    # Health checks, Telegram alerts, capacity monitoring
    # Reads: logs, RAM-disk heartbeat
    # restart: unless-stopped
```

### Volume Mounts

```
/dev/shm/remora → remora-ingest:/dev/shm/remora (tmpfs, 512m)
./data/archive → remora-archiver:/app/data/archive (SSD)
./data/logs → all containers:/app/data/logs (shared)
./config → all containers:/app/config (read-only)
```

### Resource Limits

```
remora-ingest:    cpus: 1.0, memory: 4G
remora-engine:    cpus: 2.0, memory: 8G
remora-calibration: cpus: 0.5, memory: 2G
remora-archiver:  cpus: 0.5, memory: 1G
remora-monitor:   cpus: 0.25, memory: 512M
Total:            4.25 CPUs, 15.5 GB (within 24 GB VPS)
```

---

## Part X: Testing Pyramid

### Level 1: Unit Tests (Target: 200+ tests)

| Component | Test Focus | Count |
|---|---|---|
| Ring buffer | Push, get_and_clear, overflow, wrap-around | 15 |
| Candle aggregator | Tick grouping, phase boundaries, volume delta | 20 |
| EWRV | Known series → expected variance, outlier clipping | 10 |
| Kelly-LVaR | Edge cases: p=0, b=0, σ→0, σ→∞, negative edge | 15 |
| Order state machine | All 14 valid transitions, 10 invalid transitions rejected | 24 |
| Config manager | Load, hot-reload, atomic swap, missing keys, checksums | 12 |
| Each strategy (×9) | Gate pass, gate fail, dedup, cooldown, direction | 90 |
| Delta core | Percentile, OFI, velocity, thin pool fallback | 12 |
| Zone decay | Survival curve, threshold crossing | 8 |

### Level 2: Integration Tests (Target: 30+ tests)

| Pipeline | Test Focus |
|---|---|
| Tick → Ring → Candle → RAM-disk | End-to-end data flow |
| RAM-disk → Strategy → Signal | Signal generation from real candles |
| Signal → Risk → Order Queue | Full pre-trade pipeline |
| Config change → Strategy behaviour | Hot-reload propagation |
| Circuit breaker trip → Recovery | Breaker cascade |
| Crash → Restart → Reconciliation | State recovery |

### Level 3: Replay Tests (Target: 10+ scenarios)

| Scenario | Data Source | Validation |
|---|---|---|
| Normal trading day | 10 sessions archived | Signal count, P&L |
| High VIX day (VIX > 25) | Election day data | Halt triggers |
| Low volume day | Diwali session | Thin pool handling |
| Stock split day | Corporate action data | OB zone adjustment |
| WebSocket disconnect | Injected failure | Reconnect + recovery |

### Level 4: Paper Trading (10 sessions minimum)

| Metric | Pass Threshold |
|---|---|
| Annualised Sharpe | > 1.0 |
| Maximum drawdown | < 2.0% |
| Mean absolute slippage | < 0.05% |
| Win rate | > 45% |
| Signal-to-order latency | < 1 second |
| Scan cycle P95 | < 45 seconds |

**Only when ALL paper thresholds pass for 10 consecutive sessions should ANGEL_EXECUTION_ENABLED be set to 1.**

---

## Part XI: Configuration Hot-Swap Protocol

### Atomic Reload Procedure

1. File watcher detects change in any YAML file
2. Load the changed file into a temporary dictionary
3. Validate all required keys against schema
4. Validate all values against type and range constraints
5. Compute new merged config in a separate dictionary
6. **Atomic swap:** Replace the active config reference with the new dictionary in a single assignment (Python's GIL guarantees atomicity of reference assignment)
7. Notify all registered callbacks (strategies, risk kernel, execution engine)
8. Log the change with before/after diff

### Runtime Parameter Hot-Swap (RAM-disk)

For parameters that change during the session (via calibration loop):

1. Calibration actor computes new value
2. Validate against hard bounds [0.001, 1.0]
3. Validate against per-parameter bounds from YAML
4. Write to RAM-disk `live_parameters` table with BEGIN IMMEDIATE
5. Execution engine reads at top of every 30-second scan cycle
6. No restart required; takes effect within one scan cycle
7. All changes logged to calibration_audit with provenance (who, why, when)

---

## Part XII: Remaining Open Questions

These require decisions before implementation begins:

| # | Question | Options | Recommendation |
|---|---|---|---|
| 1 | Instrument universe size | 500 / 1000 / 2000 / 9000 | Start with 500 (Nifty 500), expand after stability |
| 2 | Ring buffer capacity per instrument | 500 / 1000 / 2000 / 10000 | 2000 (sufficient for 5-min aggregation) |
| 3 | MySQL remote sync | Keep / Drop (SQLite only) | Drop for v1; add later if needed |
| 4 | Paper trading duration before live | 5 / 10 / 20 sessions | 10 sessions minimum |
| 5 | Strategy enablement at launch | All 9 / Subset | Start with S1, S2, S7 only; add others after validation |
| 6 | Trailing SL implementation | Modify order / Track internally | Track internally (avoid API rate limits), execute at EOD or SL hit |
| 7 | VIX polling frequency | 30s / 60s / 5min | 60s (balance freshness vs API load) |
| 8 | Log retention | 7 / 14 / 30 days | 14 days (align with archive retention) |

---

This refined plan addresses all 15 loopholes, 6 vulnerabilities, and 10 missing components identified in the original blueprint. The architecture is now deterministic, reproducible, and fully implementable within a 24 GB RAM, no-GPU, Dockerized Linux VPS using Angel One SmartAPI — with zero dependency on LLM, RAG, or Ollama components.



# Remora Framework v8.0 — Dual-Database Architecture
## Complete Schema Specification: Local Hot Bus + Remote MySQL Data Lake

---

## Part I: Deep Analysis of the Dual-Database Architecture

### 1.1 — Why Two Databases

The original blueprint had a fatal flaw: the execution engine read signals from remote MySQL databases (PRIMARY, FLUX, ARIS, SMART) over WAN connections. This created three failure modes documented in the knowledge base:

1. **Slippage Poisoning** — Remote DB latency of ~80–120 ms caused signals to fire 1–2 candles late. Fix: repoint all execution-critical reads to the local RAM-disk (v7.1.0).
2. **MySQL 2013 Errors** — `pymysql.err.OperationalError: (2013, "Lost connection to MySQL server during query")` stalled the main pipeline during high-frequency periods like the 09:15 IST open. Fix: decouple MySQL from the hot path entirely (v7.3.5, FIX-007).
3. **Data Loss on tmpfs Wipe** — July 1–3, 2026: WAL files locked by root permission bug caused the EOD migrator to crash silently. RAM-disk was wiped on reboot. Three days of raw tick data were permanently lost. Fix: enforce permission hygiene, NVMe mirroring, and watermark-based sync (v7.2.3).

The corrected architecture is a **Write-Back** model:

```
                    WRITE PATH
                    ══════════
Angel WebSocket ──► Ring Buffer ──► Candle Aggregator
                                         │
                                         ▼
                                  ┌─────────────┐
                                  │  WriteQueue  │  Batch: 50ms / 200 rows
                                  │  (in-proc)   │  BEGIN IMMEDIATE
                                  └──────┬──────┘
                                         │
                          ┌──────────────┼──────────────┐
                          ▼              ▼              ▼
                   ┌────────────┐ ┌──────────┐  ┌──────────────┐
                   │ LOCAL HOT  │ │ NVMe     │  │ REMOTE MySQL │
                   │ BUS        │ │ Mirror   │  │ DATA LAKE    │
                   │ (tmpfs)    │ │ (SSD)    │  │ (WAN)        │
                   │ SQLite/    │ │ Check-   │  │ Hourly       │
                   │ DuckDB     │ │ point    │  │ Watermark    │
                   │            │ │ loop     │  │ Sync         │
                   │ LATENCY:   │ │ LATENCY: │  │ LATENCY:     │
                   │ < 1 ms     │ │ ~5 ms    │  │ ~50-200 ms   │
                   │            │ │          │  │ (async,      │
                   │ READ:      │ │ RECOVERY:│  │  fire-and-   │
                   │ execution  │ │ crash    │  │  forget)     │
                   │ engine     │ │ replay   │  │              │
                   └────────────┘ └──────────┘  └──────────────┘

                    READ PATH
                    ═════════
Execution Engine ──► LOCAL HOT BUS ONLY (sub-ms)
Momentum Hunters ──► LOCAL HOT BUS ONLY
Calibration Loop ──► LOCAL HOT BUS ONLY
Streamlit Dashboard ──► LOCAL HOT BUS + MySQL (historical)
EOD Archiver ──► LOCAL HOT BUS ──► SSD Archive ──► MySQL
```

**Critical rule:** The execution engine, all 9 strategy scanners, and the risk kernel read **exclusively** from the local hot bus. MySQL is never on the critical path during market hours.

### 1.2 — Table Ownership Map

Each table has exactly **one writer** to prevent the "Token Doubling" class of bugs documented in v7.3.8:

| Table | Writer | Readers |
|---|---|---|
| `live_candles` | Candle Aggregator (via WriteQueue) | All 9 strategies, risk kernel, calibration |
| `order_blocks` | OB Detector (via WriteQueue) | S1, S4, S7, S8 |
| `cycloid_signals` | Cycloid Engine (via WriteQueue) | S1, S3, S6, S8, S9 |
| `swing_breakouts` | Swing Engine (via WriteQueue) | S1, S2, S3, S4 |
| `smart_blocks` | Smart Block Engine (via WriteQueue) | S2, S3, S5, S9 |
| `quant_predictive_signals` | Quant Engine (via WriteQueue) | S1, S2, S7, regime gates |
| `statistical_anomalies` | Zone Decay Analyst (via WriteQueue) | S8 |
| `live_orders` | Order Executor (**sync bypass**, not WriteQueue) | Execution engine, exit gate, audit |
| `live_parameters` | Calibration loop (**separate lock**) | Execution engine, risk kernel |
| `system_heartbeat` | Ingestion daemon (1s interval) | Health monitor, failover watchdog |
| `trade_telemetry` | Order Executor on CLOSED state | Variance Profiler, calibration |
| `dead_letter_queue` | WriteQueue (on write failure) | Manual review, debugging |
| `sync_watermarks` | Sync Worker | Sync Worker, audit |

### 1.3 — ACID Compliance Matrix

| ACID Property | Local Hot Bus (SQLite) | Local Hot Bus (DuckDB) | Remote MySQL |
|---|---|---|---|
| **Atomicity** | `BEGIN IMMEDIATE` per WriteQueue batch. All-or-nothing. Order state transitions use synchronous writes that bypass the queue. | Implicit per-statement atomicity. Batch inserts wrapped in explicit transactions. | InnoDB transactions. `INSERT ON DUPLICATE KEY UPDATE` is atomic per row. Bulk upserts wrapped in single transaction. |
| **Consistency** | Python-level domain validation before any write: `ob_high > ob_low`, `high >= max(open, close)`, `low <= min(open, close)`, prices > 0, non-NaN. Violations raise `DomainViolationError` and route to dead-letter queue. | Same Python-level validation. DuckDB constraints as secondary guard. | Same Python-level validation. `CHECK` constraints on critical columns. `NOT NULL` on all required fields. |
| **Isolation** | WAL mode: readers never block writers, writers never block readers. Single-writer guarantee via WriteQueue serialization. `busy_timeout = 30000`. | MVCC: multiple readers, single writer. No locking contention by design. | `REPEATABLE READ` isolation level. `NullPool` or `QueuePool` with fresh connections. No shared session across threads. |
| **Durability** | `PRAGMA synchronous = NORMAL` on tmpfs (fsync is meaningless on RAM-backed filesystem). NVMe checkpoint loop every 60 seconds. SSD archive sync every 5 minutes. | In-memory with NVMe mirroring loop. Checkpoint to disk every 60 seconds. | `innodb_flush_log_at_trx_commit = 2` (flush to OS cache, fsync once per second). `innodb_buffer_pool_size = 4 GB`. Binary logging enabled for point-in-time recovery. |

### 1.4 — Corruption Prevention Strategy

Based on every corruption event documented in the knowledge base:

| Corruption Event | Root Cause | Prevention in Schema |
|---|---|---|
| BIGINT overflow (FIX-001) | INT(11) max ~2.1B; 63-bit pseudo-random IDs exceed it | All `id` columns are `BIGINT` in both SQLite and MySQL |
| INTERVAL keyword (FIX-004) | MySQL rejects unquoted reserved words | Column renamed to `candle_interval` everywhere; ORM uses `quote=True` as belt-and-suspenders |
| WAL permission deadlock (v7.2.1) | root:root ownership on `/dev/shm/remora_hot.db` blocked ubuntu user | Schema init script runs `chown ubuntu:ubuntu` on DB directory; Docker runs as non-root |
| Silent data loss July 1–3 | WAL locked, migrator crashed, tmpfs wiped | NVMe checkpoint loop + watermark sync + EOD archive before VACUUM |
| Stale OB zones (v7.3.0) | 75% of OBs were >30 days old | `OB_MAX_AGE_DAYS` filter in queries; `created_at` indexed for range scans |
| Duplicate OB signals (v7.2.9) | Multiple OBs for same price zone with different IDs | Dedup key uses `ob_low`/`ob_high` rounded to tick size, not `ob_id` |
| dp80 = -inf veto (FIX-005) | Empty percentile pool produced infinity | Schema stores `delta_percentile_80` as nullable; application checks for NULL before comparison |

---

## Part II: Local Hot Bus Schema — SQLite (Primary Recommendation)

### 2.1 — Pragma Configuration

These pragmas are set at connection time, not stored in the schema. They are critical for ACID on tmpfs.

```
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 30000;
PRAGMA cache_size = -64000;
PRAGMA temp_store = MEMORY;
PRAGMA mmap_size = 268435456;
PRAGMA wal_autocheckpoint = 1000;
PRAGMA foreign_keys = ON;
```

**Rationale for each:**

| Pragma | Value | Why |
|---|---|---|
| `journal_mode` | `WAL` | Readers never block writers. Critical for concurrent scan + write. |
| `synchronous` | `NORMAL` | On tmpfs, `FULL` adds a useless fsync syscall to a RAM-backed filesystem. `NORMAL` is mathematically identical on memory partitions. |
| `busy_timeout` | `30000` | 30 seconds. Resolves `database is locked` crashes during market sweeps (v7.2.4 fix). |
| `cache_size` | `-64000` | 64 MB page cache. Prevents repeated disk reads on hot tables. |
| `temp_store` | `MEMORY` | Temp tables and sorts in RAM, not on tmpfs-backed temp files. |
| `mmap_size` | `268435456` | 256 MB memory-mapped I/O for read-heavy scan cycles. |
| `wal_autocheckpoint` | `1000` | Checkpoint WAL every 1000 pages. Prevents WAL file from growing unbounded. |
| `foreign_keys` | `ON` | Enforce referential integrity at the database level as a secondary guard. |

### 2.2 — Complete SQLite DDL

```sql
-- ═══════════════════════════════════════════════════════════════
-- REMORA HOT BUS — SQLite Schema
-- Location: /dev/shm/remora/remora_hot.db
-- Engine: SQLite 3.x, WAL mode
-- Purpose: Sub-millisecond hot-path reads for execution engine
-- ═══════════════════════════════════════════════════════════════

-- ─────────────────────────────────────────────────────────────────
-- TABLE 1: live_candles
-- Writer: Candle Aggregator (via WriteQueue)
-- Readers: All 9 strategies, risk kernel, calibration, EWRV engine
-- Write frequency: ~2000 rows per 5-minute boundary
-- Read frequency: Every 30-second scan cycle
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS live_candles (
    id              BIGINT PRIMARY KEY,
    ticker          TEXT    NOT NULL,
    candle_interval TEXT    NOT NULL DEFAULT '5m',
    ts              BIGINT  NOT NULL,
    open            REAL    NOT NULL,
    high            REAL    NOT NULL,
    low             REAL    NOT NULL,
    close           REAL    NOT NULL,
    volume          BIGINT  NOT NULL DEFAULT 0,
    vwap_price      REAL,
    delta           REAL    DEFAULT 0,
    delta_pct       REAL,
    created_at      BIGINT  NOT NULL DEFAULT (strftime('%s','now')),
    updated_at      BIGINT  NOT NULL DEFAULT (strftime('%s','now')),

    CHECK (high >= open AND high >= close),
    CHECK (low  <= open AND low  <= close),
    CHECK (open > 0 AND high > 0 AND low > 0 AND close > 0),
    CHECK (volume >= 0)
);

CREATE INDEX IF NOT EXISTS idx_candles_ticker_ts
    ON live_candles (ticker, ts);
CREATE INDEX IF NOT EXISTS idx_candles_ts
    ON live_candles (ts);
CREATE INDEX IF NOT EXISTS idx_candles_ticker_interval_ts
    ON live_candles (ticker, candle_interval, ts);


-- ─────────────────────────────────────────────────────────────────
-- TABLE 2: order_blocks
-- Writer: OB Detector (via WriteQueue)
-- Readers: S1, S4, S7, S8, Runway Calculator
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS order_blocks (
    id                  BIGINT PRIMARY KEY,
    ticker              TEXT    NOT NULL,
    ts                  BIGINT  NOT NULL,
    ob_type             TEXT    NOT NULL CHECK (ob_type IN ('Bullish', 'Bearish')),
    ob_high             REAL    NOT NULL,
    ob_low              REAL    NOT NULL,
    is_high_volume      INTEGER NOT NULL DEFAULT 0 CHECK (is_high_volume IN (0, 1)),
    fvg_size            REAL    DEFAULT 0,
    fvg_gap_high        REAL,
    fvg_gap_low         REAL,
    delta               REAL    DEFAULT 0,
    mitigation_status   TEXT    NOT NULL DEFAULT 'Unmitigated'
                        CHECK (mitigation_status IN ('Unmitigated', 'Mitigated', 'Consumed')),
    mitigation_ts       BIGINT,
    retest_count        INTEGER NOT NULL DEFAULT 0,
    survival_prob       REAL    DEFAULT 1.0,
    decay_rate          REAL,
    source_candle_id    BIGINT,
    created_at          BIGINT  NOT NULL DEFAULT (strftime('%s','now')),
    updated_at          BIGINT  NOT NULL DEFAULT (strftime('%s','now')),

    CHECK (ob_high > ob_low),
    CHECK (ob_high > 0 AND ob_low > 0),
    CHECK (survival_prob >= 0.0 AND survival_prob <= 1.0)
);

CREATE INDEX IF NOT EXISTS idx_ob_ticker_type_status
    ON order_blocks (ticker, ob_type, mitigation_status);
CREATE INDEX IF NOT EXISTS idx_ob_ts
    ON order_blocks (ts);
CREATE INDEX IF NOT EXISTS idx_ob_unmitigated
    ON order_blocks (ticker, mitigation_status, ts)
    WHERE mitigation_status = 'Unmitigated';
CREATE INDEX IF NOT EXISTS idx_ob_created
    ON order_blocks (created_at);


-- ─────────────────────────────────────────────────────────────────
-- TABLE 3: cycloid_signals
-- Writer: Cycloid Engine (via WriteQueue)
-- Readers: S1, S3, S6, S8, S9
-- Signal types: LONG_REVERSAL, LONG_BREAKOUT, EXHAUSTION_EXIT,
--               SHORT_REVERSAL, SHORT_BREAKOUT
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cycloid_signals (
    id                  BIGINT PRIMARY KEY,
    ticker              TEXT    NOT NULL,
    ts                  BIGINT  NOT NULL,
    signal_type         TEXT    NOT NULL CHECK (signal_type IN (
                            'LONG_REVERSAL', 'LONG_BREAKOUT',
                            'EXHAUSTION_EXIT', 'SHORT_REVERSAL',
                            'SHORT_BREAKOUT')),
    contact_price       REAL    NOT NULL,
    confidence          REAL    DEFAULT 0.0,
    v_body              REAL,
    v_upper             REAL,
    v_lower             REAL,
    candle_id           BIGINT,
    direction           TEXT    CHECK (direction IN ('LONG', 'SHORT', NULL)),
    created_at          BIGINT  NOT NULL DEFAULT (strftime('%s','now')),

    CHECK (contact_price > 0)
);

CREATE INDEX IF NOT EXISTS idx_cycloid_ticker_ts
    ON cycloid_signals (ticker, ts);
CREATE INDEX IF NOT EXISTS idx_cycloid_type_ts
    ON cycloid_signals (signal_type, ts);
CREATE INDEX IF NOT EXISTS idx_cycloid_ticker_type_ts
    ON cycloid_signals (ticker, signal_type, ts);


-- ─────────────────────────────────────────────────────────────────
-- TABLE 4: swing_breakouts
-- Writer: Swing Engine (via WriteQueue)
-- Readers: S1, S2, S3, S4
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS swing_breakouts (
    id                  BIGINT PRIMARY KEY,
    ticker              TEXT    NOT NULL,
    ts                  BIGINT  NOT NULL,
    direction           TEXT    NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
    breakout_price      REAL    NOT NULL,
    bull_pct            REAL,
    bear_pct            REAL,
    swing_high          REAL,
    swing_low           REAL,
    runway_pct          REAL,
    source_candle_id    BIGINT,
    created_at          BIGINT  NOT NULL DEFAULT (strftime('%s','now')),

    CHECK (breakout_price > 0),
    CHECK (bull_pct IS NULL OR (bull_pct >= 0.0 AND bull_pct <= 1.0)),
    CHECK (bear_pct IS NULL OR (bear_pct >= 0.0 AND bear_pct <= 1.0))
);

CREATE INDEX IF NOT EXISTS idx_swing_ticker_ts
    ON swing_breakouts (ticker, ts);
CREATE INDEX IF NOT EXISTS idx_swing_direction_ts
    ON swing_breakouts (direction, ts);
CREATE INDEX IF NOT EXISTS idx_swing_ticker_dir_ts
    ON swing_breakouts (ticker, direction, ts);


-- ─────────────────────────────────────────────────────────────────
-- TABLE 5: smart_blocks
-- Writer: Smart Block Engine (via WriteQueue)
-- Readers: S2, S3, S5, S9
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS smart_blocks (
    id                  BIGINT PRIMARY KEY,
    ticker              TEXT    NOT NULL,
    ts                  BIGINT  NOT NULL,
    delta               REAL    DEFAULT 0,
    poc_price           REAL,
    vwap_price          REAL,
    yz_vol_price        REAL,
    total_volume        BIGINT  DEFAULT 0,
    ofi                 REAL,
    price_velocity      REAL,
    signal_type         TEXT,
    source_candle_id    BIGINT,
    created_at          BIGINT  NOT NULL DEFAULT (strftime('%s','now'))
);

CREATE INDEX IF NOT EXISTS idx_smart_ticker_ts
    ON smart_blocks (ticker, ts);
CREATE INDEX IF NOT EXISTS idx_smart_ts
    ON smart_blocks (ts);
CREATE INDEX IF NOT EXISTS idx_smart_delta_ts
    ON smart_blocks (ticker, delta, ts);


-- ─────────────────────────────────────────────────────────────────
-- TABLE 6: quant_predictive_signals
-- Writer: Quant Engine / Naive Bayes (via WriteQueue)
-- Readers: S1, S2, S7, regime gates, entropy detection
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS quant_predictive_signals (
    id                  BIGINT PRIMARY KEY,
    ticker              TEXT    NOT NULL,
    ts                  BIGINT  NOT NULL,
    nb_prob             REAL    NOT NULL,
    mc_percentile_05    REAL,
    mc_percentile_50    REAL,
    mc_percentile_95    REAL,
    regime_state        TEXT    CHECK (regime_state IN (
                            'TREND', 'ENTROPY', 'TRANSITIONAL', NULL)),
    features_json       TEXT,
    created_at          BIGINT  NOT NULL DEFAULT (strftime('%s','now')),

    CHECK (nb_prob >= 0.0 AND nb_prob <= 1.0)
);

CREATE INDEX IF NOT EXISTS idx_quant_ticker_ts
    ON quant_predictive_signals (ticker, ts);
CREATE INDEX IF NOT EXISTS idx_quant_ts
    ON quant_predictive_signals (ts);


-- ─────────────────────────────────────────────────────────────────
-- TABLE 7: statistical_anomalies
-- Writer: Zone Decay Analyst, Squeeze Hunter (via WriteQueue)
-- Readers: S8, calibration loop, Streamlit dashboard
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS statistical_anomalies (
    id                  BIGINT PRIMARY KEY,
    ticker              TEXT    NOT NULL,
    ts                  BIGINT  NOT NULL,
    anomaly_type        TEXT    NOT NULL CHECK (anomaly_type IN (
                            'ZONE_DECAY_WARNING', 'SQUEEZE_DETECTED',
                            'STOP_HUNT_SWEEP', 'ICEBERG_DETECTED',
                            'CALIBRATION_REQUIRED', 'ENTROPY_SHIFT')),
    survival_prob       REAL,
    zone_ob_id          BIGINT,
    zone_type           TEXT    CHECK (zone_type IN ('Bullish', 'Bearish', NULL)),
    metadata_json       TEXT,
    source_actor        TEXT,
    created_at          BIGINT  NOT NULL DEFAULT (strftime('%s','now')),

    CHECK (survival_prob IS NULL OR (survival_prob >= 0.0 AND survival_prob <= 1.0))
);

CREATE INDEX IF NOT EXISTS idx_anomaly_ticker_type_ts
    ON statistical_anomalies (ticker, anomaly_type, ts);
CREATE INDEX IF NOT EXISTS idx_anomaly_type_ts
    ON statistical_anomalies (anomaly_type, ts);


-- ─────────────────────────────────────────────────────────────────
-- TABLE 8: live_orders
-- Writer: Order Executor (SYNCHRONOUS BYPASS — not via WriteQueue)
-- Readers: Execution engine, exit gate, position reconciler, audit
-- CRITICAL: This table bypasses the WriteQueue because order state
-- transitions require immediate durability.
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS live_orders (
    id                  BIGINT PRIMARY KEY,
    angel_order_id      TEXT,
    ticker              TEXT    NOT NULL,
    ts                  BIGINT  NOT NULL,
    direction           TEXT    NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
    strategy_id         TEXT    NOT NULL,
    gate_rule           TEXT,
    state               TEXT    NOT NULL DEFAULT 'CREATED' CHECK (state IN (
                            'CREATED', 'QUEUED', 'SUBMITTED', 'OPEN',
                            'PARTIAL_FILLED', 'FILLED', 'BRACKET_ACTIVE',
                            'CANCEL_PENDING', 'MODIFY_PENDING',
                            'CANCELLED', 'REJECTED', 'CLOSED', 'UNKNOWN')),
    entry_price         REAL,
    signal_price        REAL,
    sl_price            REAL,
    tp_price            REAL,
    trailing_sl_price   REAL,
    quantity            INTEGER NOT NULL DEFAULT 0,
    filled_quantity     INTEGER DEFAULT 0,
    filled_price        REAL,
    sl_order_id         TEXT,
    entry_order_type    TEXT    DEFAULT 'LIMIT',
    sl_order_type       TEXT    DEFAULT 'SL_LIMIT',
    kelly_fraction      REAL,
    lvar_cap            REAL,
    portfolio_heat      REAL,
    india_vix           REAL,
    nb_prob_at_entry    REAL,
    runway_pct          REAL,
    mfe                 REAL    DEFAULT 0.0,
    mae                 REAL    DEFAULT 0.0,
    execution_ewrv      REAL,
    pnl_points          REAL,
    pnl_inr             REAL,
    close_reason        TEXT    CHECK (close_reason IN (
                            'TP', 'SL', 'TRAIL', 'EOD', 'TIME_EXIT',
                            'REGIME_HALT', 'MANUAL', 'BROKER_SQUARE',
                            NULL)),
    close_ts            BIGINT,
    slippage_pct        REAL,
    fill_quality        TEXT    CHECK (fill_quality IN ('FAVOURABLE', 'ADVERSE', NULL)),
    paper_mode          INTEGER NOT NULL DEFAULT 1 CHECK (paper_mode IN (0, 1)),
    created_at          BIGINT  NOT NULL DEFAULT (strftime('%s','now')),
    updated_at          BIGINT  NOT NULL DEFAULT (strftime('%s','now')),

    CHECK (quantity >= 0),
    CHECK (filled_quantity >= 0 AND filled_quantity <= quantity),
    CHECK (entry_price IS NULL OR entry_price > 0),
    CHECK (signal_price IS NULL OR signal_price > 0)
);

CREATE INDEX IF NOT EXISTS idx_orders_ticker_ts
    ON live_orders (ticker, ts);
CREATE INDEX IF NOT EXISTS idx_orders_state
    ON live_orders (state);
CREATE INDEX IF NOT EXISTS idx_orders_strategy_ts
    ON live_orders (strategy_id, ts);
CREATE INDEX IF NOT EXISTS idx_orders_open
    ON live_orders (state, ticker)
    WHERE state IN ('FILLED', 'BRACKET_ACTIVE', 'PARTIAL_FILLED');
CREATE INDEX IF NOT EXISTS idx_orders_angel_id
    ON live_orders (angel_order_id);


-- ─────────────────────────────────────────────────────────────────
-- TABLE 9: live_parameters
-- Writer: Calibration loop / ADK Governor (SEPARATE LOCK)
-- Readers: Execution engine, risk kernel (every 30s scan cycle)
-- CRITICAL: Uses isolated _param_lock, separate from _hot_lock.
-- INSERT OR IGNORE preserves calibrated values across daemon restarts.
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS live_parameters (
    key         TEXT PRIMARY KEY,
    value       REAL    NOT NULL,
    source      TEXT    DEFAULT 'DEFAULT',
    updated_at  BIGINT  NOT NULL DEFAULT (strftime('%s','now'))
);

-- Seed defaults (INSERT OR IGNORE preserves any ADK-updated values)
INSERT OR IGNORE INTO live_parameters (key, value, source) VALUES
    ('ZONE_DECAY_THRESHOLD',     0.05,   'DEFAULT'),
    ('SURVIVAL_PROB_MIN',        0.05,   'DEFAULT'),
    ('OFI_ICEBERG_TAU',          0.10,   'DEFAULT'),
    ('EWRV_KAPPA',               0.30,   'DEFAULT'),
    ('DYNAMIC_LIMIT_BUFFER',     0.0005, 'DEFAULT'),
    ('MAX_SLIPPAGE_PCT',         1.0,    'DEFAULT'),
    ('GLOBAL_HALT',              0.0,    'DEFAULT'),
    ('NB_PROB_THRESHOLD',        0.60,   'DEFAULT'),
    ('NB_MAX_STALE_MINUTES',     5.0,    'DEFAULT'),
    ('FSH_MIN_CANDLES_BELOW_VWAP', 2.0,  'DEFAULT'),
    ('FSH_MAX_VIX',              22.0,   'DEFAULT'),
    ('RUNWAY_MIN_PCT',           5.0,    'DEFAULT'),
    ('ORDER_COOLDOWN_MINS',      60.0,   'DEFAULT'),
    ('OB_MAX_AGE_DAYS',          10.0,   'DEFAULT'),
    ('OB_TP_R_MULTIPLE',         2.0,    'DEFAULT');


-- ─────────────────────────────────────────────────────────────────
-- TABLE 10: system_heartbeat
-- Writer: Ingestion daemon (every 1 second)
-- Readers: Failover watchdog, health monitor
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS system_heartbeat (
    component       TEXT PRIMARY KEY,
    last_tick_ts    BIGINT  NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'ALIVE'
                    CHECK (status IN ('ALIVE', 'STALE', 'DEAD')),
    metadata_json   TEXT,
    updated_at      BIGINT  NOT NULL DEFAULT (strftime('%s','now'))
);

INSERT OR IGNORE INTO system_heartbeat (component, last_tick_ts, status) VALUES
    ('angel_websocket',   strftime('%s','now'), 'ALIVE'),
    ('candle_aggregator', strftime('%s','now'), 'ALIVE'),
    ('write_queue',       strftime('%s','now'), 'ALIVE'),
    ('execution_engine',  strftime('%s','now'), 'ALIVE');


-- ─────────────────────────────────────────────────────────────────
-- TABLE 11: trade_telemetry
-- Writer: Order Executor on CLOSED state transition
-- Readers: Variance Profiler, Regime Calibrator
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS trade_telemetry (
    id                      BIGINT PRIMARY KEY,
    ticker                  TEXT    NOT NULL,
    strategy_id             TEXT    NOT NULL,
    order_id                BIGINT,
    ts                      BIGINT  NOT NULL,
    mfe                     REAL    DEFAULT 0.0,
    mae                     REAL    DEFAULT 0.0,
    final_pnl               REAL    DEFAULT 0.0,
    final_pnl_pct           REAL    DEFAULT 0.0,
    survival_prob_at_entry  REAL,
    regime_state            REAL,
    nb_prob_at_entry        REAL,
    india_vix_at_entry      REAL,
    kelly_fraction_used     REAL,
    quantity                INTEGER,
    entry_price             REAL,
    exit_price              REAL,
    close_reason            TEXT,
    duration_seconds        INTEGER,
    slippage_pct            REAL,
    created_at              BIGINT  NOT NULL DEFAULT (strftime('%s','now'))
);

CREATE INDEX IF NOT EXISTS idx_telemetry_strategy_ts
    ON trade_telemetry (strategy_id, ts);
CREATE INDEX IF NOT EXISTS idx_telemetry_ts
    ON trade_telemetry (ts);


-- ─────────────────────────────────────────────────────────────────
-- TABLE 12: sync_watermarks
-- Writer: Sync Worker
-- Readers: Sync Worker (idempotent delta sync)
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sync_watermarks (
    pipeline_name   TEXT PRIMARY KEY,
    last_synced_ts  BIGINT  NOT NULL DEFAULT 0,
    rows_synced     BIGINT  NOT NULL DEFAULT 0,
    last_sync_at    BIGINT,
    status          TEXT    DEFAULT 'IDLE'
                    CHECK (status IN ('IDLE', 'SYNCING', 'ERROR')),
    error_message   TEXT,
    updated_at      BIGINT  NOT NULL DEFAULT (strftime('%s','now'))
);

INSERT OR IGNORE INTO sync_watermarks (pipeline_name) VALUES
    ('candles'), ('order_blocks'), ('cycloid_signals'),
    ('swing_breakouts'), ('smart_blocks'), ('quant_signals'),
    ('anomalies'), ('orders'), ('telemetry');


-- ─────────────────────────────────────────────────────────────────
-- TABLE 13: dead_letter_queue
-- Writer: WriteQueue (on failed writes)
-- Readers: Manual review, debugging
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dead_letter_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    target_table    TEXT    NOT NULL,
    operation       TEXT    NOT NULL,
    payload_json    TEXT    NOT NULL,
    error_message   TEXT,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    created_at      BIGINT  NOT NULL DEFAULT (strftime('%s','now'))
);

CREATE INDEX IF NOT EXISTS idx_dlq_created
    ON dead_letter_queue (created_at);
```

### 2.3 — SQLite Locking Architecture

Two independent `threading.RLock` instances protect different table groups:

```
_hot_lock (threading.RLock)
  ├── live_candles
  ├── order_blocks
  ├── cycloid_signals
  ├── swing_breakouts
  ├── smart_blocks
  ├── quant_predictive_signals
  ├── statistical_anomalies
  ├── trade_telemetry
  ├── dead_letter_queue
  └── system_heartbeat

_param_lock (threading.RLock)
  ├── live_parameters
  └── sync_watermarks

_sync_lock (threading.RLock)
  └── live_orders (synchronous bypass writes)
```

**Why three locks:** An ADK Governor write to `live_parameters` must never block the WriteQueue flush thread that processes 2000-ticker candle upserts every 50 ms. Similarly, an order state transition must never wait behind a candle batch commit.

---

## Part III: Local Hot Bus Schema — DuckDB (Alternative)

### 3.1 — When to Use DuckDB Instead of SQLite

| Criterion | SQLite | DuckDB |
|---|---|---|
| Write pattern | High-frequency small writes (candle upserts) | Bulk analytical inserts |
| Read pattern | Point lookups + small range scans | Complex aggregations across columns |
| Concurrency | WAL: 1 writer, N readers | MVCC: 1 writer, N readers |
| Storage model | Row-oriented | Columnar |
| Best for this workload | **Yes** — hot path is OLTP-like | Better for calibration analytics |

**Recommendation:** Use SQLite for the hot bus. Use DuckDB only for the NVMe mirror / analytical layer if you add complex calibration queries later.

### 3.2 — DuckDB DDL (If Chosen)

```sql
-- ═══════════════════════════════════════════════════════════════
-- REMORA HOT BUS — DuckDB Schema (Alternative)
-- Location: duckdb.connect('/dev/shm/remora/remora_hot.duckdb')
-- with NVMe checkpoint loop every 60 seconds
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS live_candles (
    id              BIGINT PRIMARY KEY,
    ticker          VARCHAR(20) NOT NULL,
    candle_interval VARCHAR(8)  NOT NULL DEFAULT '5m',
    ts              BIGINT      NOT NULL,
    open            DOUBLE      NOT NULL,
    high            DOUBLE      NOT NULL,
    low             DOUBLE      NOT NULL,
    close           DOUBLE      NOT NULL,
    volume          BIGINT      NOT NULL DEFAULT 0,
    vwap_price      DOUBLE,
    delta           DOUBLE      DEFAULT 0,
    delta_pct       DOUBLE,
    created_at      BIGINT      NOT NULL,
    updated_at      BIGINT      NOT NULL
);

CREATE INDEX idx_candles_ticker_ts ON live_candles (ticker, ts);

-- Repeat for all other tables with identical column definitions.
-- DuckDB uses VARCHAR(n) instead of TEXT.
-- CHECK constraints are supported.
-- No PRAGMA configuration needed.
-- MVCC is automatic.
```

### 3.3 — NVMe Mirroring Loop (DuckDB-Specific)

Since DuckDB in-memory mode has no durability, a background thread must checkpoint to NVMe SSD:

```
Every 60 seconds:
  1. CHECKPOINT;                          -- Flush to NVMe
  2. Copy /dev/shm/remora/*.duckdb → /data/archive/hot_checkpoint/
  3. Verify file size > 0
  4. Log checkpoint completion
```

---

## Part IV: Remote MySQL Data Lake Schema

### 4.1 — MySQL Server Configuration

```ini
[mysqld]
# InnoDB ACID settings
innodb_flush_log_at_trx_commit = 2
innodb_buffer_pool_size = 4G
innodb_log_file_size = 1G
innodb_file_per_table = 1
innodb_lock_wait_timeout = 30

# Connection settings
max_connections = 200
wait_timeout = 600
interactive_timeout = 600

# Binary logging for point-in-time recovery
log_bin = mysql-bin
binlog_expire_logs_seconds = 604800
binlog_format = ROW

# Character set
character_set_server = utf8mb4
collation_server = utf8mb4_unicode_ci

# Slow query log for debugging
slow_query_log = 1
long_query_time = 2
```

### 4.2 — Complete MySQL DDL

```sql
-- ═══════════════════════════════════════════════════════════════
-- REMORA DATA LAKE — MySQL Schema
-- Engine: InnoDB (ACID)
-- Isolation: REPEATABLE READ
-- Purpose: Durable storage, historical queries, scaling
-- ═══════════════════════════════════════════════════════════════

-- ─────────────────────────────────────────────────────────────────
-- TABLE 1: live_candles
-- Partitioned by month for efficient range scans and pruning
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS live_candles (
    id              BIGINT          NOT NULL,
    ticker          VARCHAR(20)     NOT NULL,
    candle_interval VARCHAR(8)      NOT NULL DEFAULT '5m',
    ts              BIGINT          NOT NULL,
    `open`          DOUBLE          NOT NULL,
    `high`          DOUBLE          NOT NULL,
    `low`           DOUBLE          NOT NULL,
    `close`         DOUBLE          NOT NULL,
    volume          BIGINT          NOT NULL DEFAULT 0,
    vwap_price      DOUBLE          NULL,
    delta           DOUBLE          NULL DEFAULT 0,
    delta_pct       DOUBLE          NULL,
    created_at      BIGINT          NOT NULL,
    updated_at      BIGINT          NOT NULL,
    synced_at       BIGINT          NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uq_candle (ticker, candle_interval, ts),
    INDEX idx_candles_ticker_ts (ticker, ts),
    INDEX idx_candles_ts (ts),
    INDEX idx_candles_synced (synced_at),

    CONSTRAINT chk_candle_prices CHECK (`high` >= `open` AND `high` >= `close`
                                    AND `low` <= `open` AND `low` <= `close`
                                    AND `open` > 0 AND volume >= 0)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  PARTITION BY RANGE (ts) (
    PARTITION p_2026_07 VALUES LESS THAN (1753996800),
    PARTITION p_2026_08 VALUES LESS THAN (1756675200),
    PARTITION p_2026_09 VALUES LESS THAN (1759353600),
    PARTITION p_2026_10 VALUES LESS THAN (1761945600),
    PARTITION p_2026_11 VALUES LESS THAN (1764624000),
    PARTITION p_2026_12 VALUES LESS THAN (1767216000),
    PARTITION p_future  VALUES LESS THAN MAXVALUE
  );


-- ─────────────────────────────────────────────────────────────────
-- TABLE 2: order_blocks
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS order_blocks (
    id                  BIGINT          NOT NULL,
    ticker              VARCHAR(20)     NOT NULL,
    ts                  BIGINT          NOT NULL,
    ob_type             ENUM('Bullish', 'Bearish') NOT NULL,
    ob_high             DOUBLE          NOT NULL,
    ob_low              DOUBLE          NOT NULL,
    is_high_volume      TINYINT(1)      NOT NULL DEFAULT 0,
    fvg_size            DOUBLE          NULL DEFAULT 0,
    fvg_gap_high        DOUBLE          NULL,
    fvg_gap_low         DOUBLE          NULL,
    delta               DOUBLE          NULL DEFAULT 0,
    mitigation_status   ENUM('Unmitigated', 'Mitigated', 'Consumed')
                        NOT NULL DEFAULT 'Unmitigated',
    mitigation_ts       BIGINT          NULL,
    retest_count        INT             NOT NULL DEFAULT 0,
    survival_prob       DOUBLE          NULL DEFAULT 1.0,
    decay_rate          DOUBLE          NULL,
    source_candle_id    BIGINT          NULL,
    created_at          BIGINT          NOT NULL,
    updated_at          BIGINT          NOT NULL,
    synced_at           BIGINT          NULL,

    PRIMARY KEY (id),
    INDEX idx_ob_ticker_type_status (ticker, ob_type, mitigation_status),
    INDEX idx_ob_ts (ts),
    INDEX idx_ob_created (created_at),
    INDEX idx_ob_synced (synced_at),

    CONSTRAINT chk_ob_bounds CHECK (ob_high > ob_low AND ob_high > 0 AND ob_low > 0)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────────
-- TABLE 3: cycloid_signals
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cycloid_signals (
    id                  BIGINT          NOT NULL,
    ticker              VARCHAR(20)     NOT NULL,
    ts                  BIGINT          NOT NULL,
    signal_type         ENUM('LONG_REVERSAL', 'LONG_BREAKOUT',
