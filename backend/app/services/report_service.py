from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFoundError, UnprocessableError
from app.core.jsonutil import json_safe
from app.engines import report_engine as re_
from app.models import OptimizationResult, Queue, Report, ReportType, SimulationRun, utcnow
from app.services.analytics_service import AnalyticsService
from app.services.bottleneck_service import BottleneckService
from app.services.optimization_service import OptimizationService
from app.services.prediction_service import PredictionService


class NotAvailable(AppError):
    status_code = 501
    code = "export_unavailable"


def _rows(d: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    return [{"metric": k, "value": d.get(k)} for k in keys]


class ReportService:
    def __init__(self, db: Session):
        self.db = db

    def _queue(self, queue_id: int | None) -> Queue:
        if queue_id is None:
            raise UnprocessableError("queue_id is required for this report type", "queue_id_required")
        q = self.db.get(Queue, queue_id)
        if q is None:
            raise NotFoundError(f"Queue {queue_id} not found", "queue_not_found")
        return q

    def _queue_performance(self, req) -> tuple[str, dict, bool, str, int | None]:
        q = self._queue(req.queue_id)
        a = AnalyticsService(self.db).run("overview", q.id, None, req.start_date, req.end_date, "hour",
                                          req.tz_offset_minutes, compare=True)
        syn = a["meta"]["contains_synthetic_data"] or q.is_synthetic
        tabs = {"hourly_performance": re_.table(a["tables"].get("hourly", [])),
                "daily_performance": re_.table(a["tables"].get("daily", [])),
                "counter_utilization": re_.table(a["tables"].get("by_counter", []))}
        comp = a["summary"].get("comparison", {})
        if comp.get("available"):
            tabs["previous_period_comparison"] = re_.table(
                [{"metric": k, **{x: v[x] for x in ("current", "previous", "change", "change_pct", "verdict")}}
                 for k, v in comp["metrics"].items()])
        data = {"summary": a["summary"]["kpis"] | {"queue_name": q.name, "filters": a["filters"]}, "tables": tabs,
                "details": {"charts": a["charts"], "comparison": comp, "notes": a["meta"]["notes"]}}
        return f"Queue performance: {q.name}", data, syn, ("synthetic" if syn else "recorded"), q.id

    def _simulation(self, req) -> tuple[str, dict, bool, str, int | None]:
        if req.simulation_id is None:
            raise UnprocessableError("simulation_id is required", "simulation_id_required")
        run = self.db.get(SimulationRun, req.simulation_id)
        if run is None:
            raise NotFoundError(f"Simulation {req.simulation_id} not found", "simulation_not_found")
        res = run.results or {}
        keys = ["total_arrivals", "total_served", "customers_remaining", "abandoned", "avg_waiting_time",
                "p95_waiting_time", "max_waiting_time", "avg_queue_length", "max_queue_length", "avg_service_time",
                "avg_utilization", "throughput"]
        data = {"summary": {"simulation_id": run.id, "name": run.name, "seed": run.seed, "time_unit": "minutes",
                            **{k: res.get(k) for k in keys}},
                "tables": {"configuration": re_.table(_rows(run.configuration, *run.configuration.keys())),
                           "counters": re_.table(res.get("counters", [])),
                           "theoretical": re_.table(_rows(res.get("theoretical", {}), *(res.get("theoretical") or {}).keys()))},
                "details": {"configuration": run.configuration, "results": res}}
        return f"Simulation results: {run.name or run.id}", data, True, "simulation", None

    def _prediction(self, req) -> tuple[str, dict, bool, str, int | None]:
        q = self._queue(req.queue_id)
        svc = PredictionService(self.db)
        stored = svc.evaluate(q.id, "stored")
        back = svc.evaluate(q.id, "backtest")
        bt = back["backtest"]
        tr = bt["training_report"]
        vm = tr.get("validation_metrics") or {}
        tabs = {"stored_predictions": re_.table(stored.get("predictions", [])),
                "holdout_metrics_by_method": re_.table([{"method": m, **v} for m, v in vm.items()]),
                "baseline_history_metrics": re_.table(_rows(bt["baseline_metrics_all_history"],
                                                            *bt["baseline_metrics_all_history"].keys()))}
        data = {"summary": {"queue_name": q.name, "units": "seconds", "stored_predictions_evaluated": stored["predictions_evaluated"],
                            "stored_metrics": stored["metrics"], "model_status": tr.get("status"),
                            "selected_method": tr.get("selected"), "selection_reason": tr.get("reason"),
                            "usable_backtest_samples": bt["usable_samples"]},
                "tables": tabs, "details": {"stored": stored, "backtest": back}}
        return f"Prediction evaluation: {q.name}", data, q.is_synthetic, ("synthetic" if q.is_synthetic else "recorded"), q.id

    def _bottleneck(self, req) -> tuple[str, dict, bool, str, int | None]:
        q = self._queue(req.queue_id)
        res = BottleneckService(self.db).analyze(q.id, req.window_minutes, req.lookback_minutes)
        det = res["detections"]
        data = {"summary": {"queue_name": q.name, "detections": len(det),
                            "by_severity": {s: sum(1 for d in det if d["severity"] == s)
                                            for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW")},
                            "window_minutes": res["window_minutes"], "as_of": res["by_queue"][0]["as_of"]},
                "tables": {"detections": re_.table([{k: d[k] for k in ("detection_id", "bottleneck_type", "severity",
                                                                       "counter_id", "explanation", "operational_impact",
                                                                       "recommendation", "detection_timestamp")} for d in det])},
                "details": res}
        return f"Bottleneck analysis: {q.name}", data, q.is_synthetic, ("synthetic" if q.is_synthetic else "recorded"), q.id

    def _optimization(self, req) -> tuple[str, dict, bool, str, int | None]:
        if req.optimization_id is None:
            raise UnprocessableError("optimization_id is required", "optimization_id_required")
        o = OptimizationService(self.db).get(req.optimization_id)
        imp = o["estimated_improvement"]
        cands = (o["details"] or {}).get("candidates", [])
        data = {"summary": {"optimization_id": o["optimization_id"], "queue_id": o["queue_id"],
                            "is_improvement": imp["is_improvement"],
                            "avg_wait_current_min": imp["avg_waiting_time_min"]["current"],
                            "avg_wait_proposed_min": imp["avg_waiting_time_min"]["proposed"],
                            "wait_reduction_percent": imp["avg_waiting_time_min"]["percent_reduction"],
                            "cost_change_per_hour": imp["cost_per_hour"]["change"], "explanation": o["explanation"],
                            "optimality": (o["details"] or {}).get("optimality")},
                "tables": {"allocation_comparison": re_.table([
                    {"allocation": "current", **{k: o["current_metrics"].get(k) for k in (
                        "avg_waiting_time_min", "p95_waiting_time_min", "avg_utilization", "utilization_imbalance", "cost_per_hour")},
                     "counters": len(o["current_allocation"]["counters"]), "policy": o["current_allocation"]["assignment_policy"]},
                    {"allocation": "proposed", **{k: o["proposed_metrics"].get(k) for k in (
                        "avg_waiting_time_min", "p95_waiting_time_min", "avg_utilization", "utilization_imbalance", "cost_per_hour")},
                     "counters": len(o["proposed_allocation"]["counters"]), "policy": o["proposed_allocation"]["assignment_policy"]}]),
                    "candidates_evaluated": re_.table(cands)},
                "details": o}
        return f"Optimization comparison #{o['optimization_id']}", data, True, "simulation", o["queue_id"]

    def generate(self, req) -> dict[str, Any]:
        builders = {ReportType.QUEUE_PERFORMANCE.value: self._queue_performance,
                    ReportType.SIMULATION_RESULTS.value: self._simulation,
                    ReportType.PREDICTION_EVALUATION.value: self._prediction,
                    ReportType.BOTTLENECK_ANALYSIS.value: self._bottleneck,
                    ReportType.OPTIMIZATION_COMPARISON.value: self._optimization}
        title, data, syn, origin, queue_id = builders[req.report_type.value](req)
        params = req.model_dump(mode="json", exclude_none=True)
        data = {"meta": re_.make_meta(req.report_type.value, title, syn, origin, params), **json_safe(data)}
        row = Report(report_type=req.report_type.value, title=title, queue_id=queue_id, report_data=json_safe(data),
                     contains_synthetic_data=syn, created_at=utcnow())
        self.db.add(row)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.to_dict(row)

    @staticmethod
    def to_dict(r: Report, include_data: bool = True) -> dict[str, Any]:
        d = {"report_id": r.id, "report_type": r.report_type, "title": r.title, "queue_id": r.queue_id,
             "contains_synthetic_data": r.contains_synthetic_data, "created_at": r.created_at}
        if include_data:
            d["report_data"] = r.report_data
        return json_safe(d)

    def _get(self, report_id: int) -> Report:
        r = self.db.get(Report, report_id)
        if r is None:
            raise NotFoundError(f"Report {report_id} not found", "report_not_found")
        return r

    def get(self, report_id: int) -> dict[str, Any]:
        return self.to_dict(self._get(report_id))

    def list(self, report_type: str | None = None, queue_id: int | None = None, limit: int = 50, offset: int = 0):
        stmt = select(Report).order_by(Report.id.desc()).limit(limit).offset(offset)
        if report_type:
            stmt = stmt.where(Report.report_type == report_type)
        if queue_id is not None:
            stmt = stmt.where(Report.queue_id == queue_id)
        return [self.to_dict(r, include_data=False) for r in self.db.scalars(stmt).all()]

    def export(self, report_id: int, fmt: str) -> tuple[bytes, str, str]:
        r = self._get(report_id)
        name = f"linezero-report-{r.id}-{r.report_type}"
        if fmt == "json":
            import json
            return json.dumps(r.report_data, indent=2).encode(), "application/json", f"{name}.json"
        if fmt == "csv":
            return re_.to_csv(r.report_data).encode("utf-8"), "text/csv; charset=utf-8", f"{name}.csv"
        if fmt == "pdf":
            try:
                return re_.to_pdf(r.report_data), "application/pdf", f"{name}.pdf"
            except re_.PdfUnavailable as exc:
                raise NotAvailable(str(exc), "pdf_unavailable")
        raise UnprocessableError("format must be json, csv or pdf", "invalid_export_format")
