# Changelog

## SLA & Customer Experience Intelligence (unreleased)

See `docs/SLA_INTELLIGENCE.md`.

### Added
- Operator-defined SLA targets per queue and service class (`sla_policies`), editable in the UI.
- Exact breach probability per waiting customer (Safe / At risk / Critical / Breached) reusing the prediction engine's quantities; live monitoring table.
- Backend-computed compliance score (current, historical, overall, predicted) with Wilson intervals and trend.
- SLA recommendations validated by the existing intervention/simulation engines, optionally sent to the approval workflow.
- `/api/v1/sla/*` endpoints; "SLA Intelligence" page; SLA card on the server dashboard.
- Alembic migration `0004_sla_intelligence`: table `sla_policies` and one nullable column `queue_entries.service_class`.

### Changed
- `POST /queues/{id}/entries` accepts an optional body `{"service_class": ...}`; omitting it behaves as before.
- `tests/test_database.py`: the head-revision test now expects `0004` and checks the chain 0004 to 0001. No other existing test was modified.

## 2.0.0: Adaptive Intelligence (unreleased)

Adds the closed loop *operational data → self-learning twin → risk detection → intervention proposals → operator approval → outcome evaluation → recalibration*. See `docs/ADAPTIVE_INTELLIGENCE.md`.

### Added
- Calibration engine with chronological validation, a "better than incumbent" gate, append-only versions, rollback, drift detection and prediction-error tracking.
- Operational risk engine: 7 categories with documented formulas and evidence-based confidence; stored risk events.
- Intervention engine: candidate generation, common-random-number simulation, cost model, net-value ranking, deterministic explanation, operator approval workflow.
- Outcome learning: before/after observation, verification labels (verified real / synthetic / operator reported), learning statistics.
- Operations overview and an automatic-stages cycle endpoint.
- Frontend sections: Adaptive Intelligence, Operational Risk Radar, Autonomous Interventions, Outcome Learning.
- Alembic migration `0003_adaptive_intelligence` (four new tables, nothing existing altered).
- Backend, unit and end-to-end tests for all of the above.

### Changed
- `GET /twin/live/{queue_id}` has an additive `active_calibration` field.
- `tests/test_database.py`: the head-revision test now expects `0003` (plus a migration-chain check). No other existing test was modified.

### Not changed
- Existing endpoints, tables and browser demo mode.
