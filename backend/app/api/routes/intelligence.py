"""Part 2 endpoints: predictions, bottlenecks, optimization, analytics, reports (thin HTTP layer)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.enums import BottleneckType, ReportType, Severity
from app.schemas.common import ErrorResponse
from app.schemas.intelligence import (
    AnalyticsOut, BottleneckAnalyzeOut, BottleneckAnalyzeRequest, DetectionOut, OptimizationOut,
    OptimizationRunRequest, PredictionEvaluateRequest, PredictionOut, ReportGenerateRequest, ReportOut,
    ReportSummaryOut,
)
from app.services.analytics_service import AnalyticsService
from app.services.bottleneck_service import BottleneckService
from app.services.optimization_service import OptimizationService
from app.services.prediction_service import PredictionService
from app.services.report_service import ReportService

ERR = {404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}}

predictions = APIRouter(prefix="/predictions", tags=["predictions"])
bottlenecks = APIRouter(prefix="/bottlenecks", tags=["bottlenecks"])
optimization = APIRouter(prefix="/optimization", tags=["optimization"])
analytics = APIRouter(prefix="/analytics", tags=["analytics"])
reports = APIRouter(prefix="/reports", tags=["reports"])


@predictions.get("/{queue_id}", response_model=PredictionOut, responses=ERR)
def get_prediction(queue_id: int, store: bool = Query(default=True, description="Persist the prediction record"),
                   db: Session = Depends(get_db)):
    """Predict the waiting time (seconds) for a customer joining the queue now."""
    return PredictionService(db).predict(queue_id, store)


@predictions.get("/{queue_id}/history", response_model=list[dict], responses=ERR)
def prediction_history(queue_id: int, limit: int = Query(default=50, ge=1, le=500),
                       offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
    return PredictionService(db).list_predictions(queue_id, limit, offset)


@predictions.post("/evaluate", responses=ERR)
def evaluate_predictions(payload: PredictionEvaluateRequest, db: Session = Depends(get_db)):
    """Compare stored predictions with observed waits (MAE, RMSE, error), or backtest on history."""
    return PredictionService(db).evaluate(
        payload.queue_id, payload.mode, payload.prediction_ids,
        [a.model_dump() for a in payload.actuals] if payload.actuals else None, payload.max_match_gap_seconds)


@bottlenecks.get("", response_model=list[DetectionOut])
def list_bottlenecks(
    queue_id: int | None = Query(default=None, gt=0), counter_id: int | None = Query(default=None, gt=0),
    severity: Severity | None = None, bottleneck_type: BottleneckType | None = None,
    limit: int = Query(default=100, ge=1, le=1000), offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return BottleneckService(db).list(queue_id, counter_id, severity.value if severity else None,
                                      bottleneck_type.value if bottleneck_type else None, limit, offset)


@bottlenecks.post("/analyze", response_model=BottleneckAnalyzeOut, status_code=status.HTTP_201_CREATED, responses=ERR)
def analyze_bottlenecks(payload: BottleneckAnalyzeRequest, db: Session = Depends(get_db)):
    return BottleneckService(db).analyze(payload.queue_id, payload.window_minutes, payload.lookback_minutes, payload.as_of)


@optimization.post("/run", response_model=OptimizationOut, status_code=status.HTTP_201_CREATED, responses=ERR)
def run_optimization(payload: OptimizationRunRequest, db: Session = Depends(get_db)):
    return OptimizationService(db).run(payload)


@optimization.get("/{optimization_id}", response_model=OptimizationOut, responses=ERR)
def get_optimization(optimization_id: int, db: Session = Depends(get_db)):
    return OptimizationService(db).get(optimization_id)


def _filters(
    queue_id: int | None = Query(default=None, gt=0), counter_id: int | None = Query(default=None, gt=0),
    start_date: datetime | None = Query(default=None, description="ISO-8601; naive values are UTC"),
    end_date: datetime | None = Query(default=None, description="ISO-8601; naive values are UTC"),
    tz_offset_minutes: int = Query(default=0, ge=-720, le=840, description="Bucket alignment offset from UTC"),
):
    return dict(queue_id=queue_id, counter_id=counter_id, start=start_date, end=end_date,
                tz_offset_minutes=tz_offset_minutes)


@analytics.get("/overview", response_model=AnalyticsOut, responses=ERR)
def analytics_overview(f: dict = Depends(_filters), compare_previous: bool = False, db: Session = Depends(get_db)):
    return AnalyticsService(db).run("overview", compare=compare_previous, **f)


@analytics.get("/arrivals", response_model=AnalyticsOut, responses=ERR)
def analytics_arrivals(f: dict = Depends(_filters), granularity: Literal["hour", "day"] = "hour",
                       db: Session = Depends(get_db)):
    return AnalyticsService(db).run("arrivals", granularity=granularity, **f)


@analytics.get("/waiting-times", response_model=AnalyticsOut, responses=ERR)
def analytics_waiting(f: dict = Depends(_filters), granularity: Literal["hour", "day"] = "hour",
                      db: Session = Depends(get_db)):
    return AnalyticsService(db).run("waiting-times", granularity=granularity, **f)


@analytics.get("/utilization", response_model=AnalyticsOut, responses=ERR)
def analytics_utilization(f: dict = Depends(_filters), granularity: Literal["hour", "day"] = "hour",
                          db: Session = Depends(get_db)):
    return AnalyticsService(db).run("utilization", granularity=granularity, **f)


@analytics.get("/peak-hours", response_model=AnalyticsOut, responses=ERR)
def analytics_peak_hours(f: dict = Depends(_filters), db: Session = Depends(get_db)):
    return AnalyticsService(db).run("peak-hours", **f)


@reports.get("", response_model=list[ReportSummaryOut])
def list_reports(report_type: ReportType | None = None, queue_id: int | None = Query(default=None, gt=0),
                 limit: int = Query(default=50, ge=1, le=500), offset: int = Query(default=0, ge=0),
                 db: Session = Depends(get_db)):
    return ReportService(db).list(report_type.value if report_type else None, queue_id, limit, offset)


@reports.post("/generate", response_model=ReportOut, status_code=status.HTTP_201_CREATED, responses=ERR)
def generate_report(payload: ReportGenerateRequest, db: Session = Depends(get_db)):
    return ReportService(db).generate(payload)


@reports.get("/{report_id}", response_model=ReportOut, responses=ERR)
def get_report(report_id: int, db: Session = Depends(get_db)):
    return ReportService(db).get(report_id)


@reports.get("/{report_id}/export", responses={**ERR, 501: {"model": ErrorResponse}})
def export_report(report_id: int, format: Literal["json", "csv", "pdf"] = "csv", db: Session = Depends(get_db)):
    body, media, filename = ReportService(db).export(report_id, format)
    return Response(content=body, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
