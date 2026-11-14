import csv
import io

from app.engines import report_engine as re_


def sample():
    return {"meta": re_.make_meta("queue_performance", "Test", True, "synthetic", {"queue_id": 1}),
            "summary": {"a": 1.5, "nested": {"b": [1, 2]}},
            "tables": {"t": re_.table([{"x": 1, "y": "a,b"}, {"x": 2, "y": None}])}}


def test_meta_flags_synthetic_and_has_timestamp():
    m = sample()["meta"]
    assert m["contains_synthetic_data"] is True and "SYNTHETIC" in m["data_notice"] and m["generated_at"]
    assert "SIMULATED" in re_.make_meta("simulation_results", "s", True, "simulation", {})["data_notice"]


def test_csv_round_trips_tables_and_quotes_commas():
    rows = list(csv.reader(io.StringIO(re_.to_csv(sample()))))
    assert rows[0] == ["section", "key", "value"] and ["summary", "nested.b", "1, 2"] in rows
    i = rows.index(["table: t"])
    assert rows[i + 1] == ["x", "y"] and rows[i + 2] == ["1", "a,b"]
    assert any(r[:2] == ["meta", "data_notice"] for r in rows)


def test_pdf_is_generated():
    pdf = re_.to_pdf(sample())
    assert pdf.startswith(b"%PDF") and len(pdf) > 1000
