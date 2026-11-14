"""Report structure + CSV / PDF rendering (pure).

report_data = {meta, summary, tables: {name: {columns, rows}}, details}
Every report states when it was generated and whether the data is synthetic / simulated.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any

PDF_MAX_ROWS = 60


class PdfUnavailable(RuntimeError):
    pass


def flatten(d: Any, prefix: str = "") -> list[tuple[str, Any]]:
    """Nested dict -> [(dotted.key, scalar)]; lists of scalars are joined, lists of dicts are skipped (use tables)."""
    out: list[tuple[str, Any]] = []
    if not isinstance(d, dict):
        return out
    for k, v in d.items():
        if isinstance(v, dict):
            out += flatten(v, f"{prefix}{k}.")
        elif isinstance(v, list):
            if all(not isinstance(i, (dict, list)) for i in v):
                out.append((f"{prefix}{k}", ", ".join(map(str, v))))
        else:
            out.append((f"{prefix}{k}", v))
    return out


def table(rows: list[dict[str, Any]], columns: list[str] | None = None) -> dict[str, Any]:
    cols = columns or (list(rows[0].keys()) if rows else [])
    return {"columns": cols, "rows": [[_cell(r.get(c)) for c in cols] for r in rows]}


def _cell(v: Any) -> Any:
    if isinstance(v, (dict, list)):
        return str(v)
    return v


def make_meta(report_type: str, title: str, synthetic: bool, origin: str, parameters: dict[str, Any]) -> dict[str, Any]:
    notice = {
        "synthetic": "SYNTHETIC DATA: generated for demonstration/testing; not real customer activity.",
        "simulation": "SIMULATED DATA: produced by the discrete-event simulation engine; not real customer activity.",
        "recorded": "Based on recorded queue data.",
    }[origin if origin in ("synthetic", "simulation") else "recorded"]
    return {"report_type": report_type, "title": title, "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_origin": origin, "contains_synthetic_data": synthetic, "data_notice": notice,
            "parameters": parameters}


def to_csv(data: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["section", "key", "value"])
    for k, v in flatten(data.get("meta", {})):
        w.writerow(["meta", k, v])
    for k, v in flatten(data.get("summary", {})):
        w.writerow(["summary", k, v])
    for name, t in (data.get("tables") or {}).items():
        w.writerow([])
        w.writerow([f"table: {name}"])
        w.writerow(t["columns"])
        w.writerows(t["rows"])
    return buf.getvalue()


def to_pdf(data: dict[str, Any]) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:  # pragma: no cover
        raise PdfUnavailable("PDF export requires the 'reportlab' package") from exc
    styles = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24)
    meta = data.get("meta", {})
    esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    story: list[Any] = [Paragraph(esc(meta.get("title", "LineZero report")), styles["Title"]),
                        Paragraph(f"Generated: {esc(meta.get('generated_at'))}", styles["Normal"]),
                        Paragraph(f"<b>{esc(meta.get('data_notice', ''))}</b>", styles["Normal"]), Spacer(1, 10)]

    def grid(rows: list[list[Any]], header: bool = True) -> Table:
        cells = [[Paragraph(esc("" if c is None else (f"{c:.4g}" if isinstance(c, float) else c)), styles["BodyText"])
                  for c in r] for r in rows]
        t = Table(cells, repeatRows=1 if header else 0)
        st = [("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]
        if header:
            st.append(("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey))
        t.setStyle(TableStyle(st))
        return t

    summary = flatten(data.get("summary", {}))
    if summary:
        story += [Paragraph("Summary", styles["Heading2"]), grid([["Metric", "Value"]] + [[k, v] for k, v in summary[:80]])]
    for name, t in (data.get("tables") or {}).items():
        story += [Spacer(1, 10), Paragraph(esc(name.replace("_", " ").title()), styles["Heading2"])]
        rows = t["rows"][:PDF_MAX_ROWS]
        if not t["columns"]:
            story.append(Paragraph("(empty)", styles["Normal"]))
            continue
        story.append(grid([t["columns"]] + rows))
        if len(t["rows"]) > PDF_MAX_ROWS:
            story.append(Paragraph(f"Showing {PDF_MAX_ROWS} of {len(t['rows'])} rows; export CSV/JSON for all rows.",
                                   styles["Italic"]))
    doc.build(story)
    return buf.getvalue()
