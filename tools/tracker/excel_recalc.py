#!/usr/bin/env python3
"""Recalculate the tracker in Microsoft Excel, store the values and verify the formulas.

openpyxl writes formulas without results, so anything other than Excel shows them empty.
This opens the workbook in a separate hidden Excel instance, recalculates, and checks:
  * no formula evaluates to an error;
  * DASHBOARD totals and per-phase counts equal counts computed here from MASTER's data;
  * every Status cell on the view sheets equals the task's status in MASTER;
  * CRITICAL_FIXES marks a finding RESOLVED exactly when all its fix tasks are DONE.
Then it saves (unless --check-only), so other viewers see values too.

Requires Windows, Microsoft Excel and pywin32:
    python tools/tracker/excel_recalc.py [--check-only] [workbook]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile
from pathlib import Path

import pythoncom
import pywintypes
import win32com.client

XL_CELL_TYPE_FORMULAS = -4123
XL_ERRORS = 16
DEFAULT = Path(__file__).resolve().parents[2] / "SmartDoc_Master_Implementation_Tracker.xlsx"
ACTIVE = ("IN_PROGRESS", "IMPLEMENTED", "TESTING")


def rows_of(rng) -> list[tuple]:
    value = rng.Value
    if not isinstance(value, tuple):
        return [(value,)]
    return [row if isinstance(row, tuple) else (row,) for row in value]


def expected_counts(tasks: list[dict]) -> dict:
    def count(*statuses, priority=None):
        return sum(1 for t in tasks if t["Status"] in statuses and (priority is None or t["Priority"] == priority))

    total = len(tasks)
    done = count("DONE")
    return {
        "Total tasks": total, "Completed (DONE)": done, "Verified (VERIFIED + DONE)": count("VERIFIED") + done,
        "In progress": count(*ACTIVE), "Blocked": count("BLOCKED"), "Failed": count("FAILED"),
        "Deferred": count("DEFERRED"), "Not started": count("NOT_STARTED"), "Remaining (not DONE)": total - done,
        "P0 remaining": sum(1 for t in tasks if t["Priority"] == "P0" and t["Status"] != "DONE"),
        "P1 remaining": sum(1 for t in tasks if t["Priority"] == "P1" and t["Status"] != "DONE"),
    }


def verify(wb) -> list[str]:
    problems: list[str] = []
    master = rows_of(wb.Worksheets("MASTER").UsedRange)
    headers = [str(h) for h in master[0]]
    tasks = [dict(zip(headers, row)) for row in master[1:] if row[0]]
    status_of = {t["ID"]: t["Status"] for t in tasks}

    dash = wb.Worksheets("DASHBOARD")
    kpis = {str(label): value for label, value in rows_of(dash.Range("A5:B20")) if label}
    for label, want in expected_counts(tasks).items():
        got = kpis.get(label)
        if got is None or float(got) != float(want):
            problems.append(f"DASHBOARD {label}: formula gives {got}, MASTER data gives {want}")

    # progress by phase: find the header row in column E
    col_e = rows_of(dash.Range("E1:E120"))
    header_row = next((i + 1 for i, (v,) in enumerate(col_e) if v == "Phase"), None)
    if header_row is None:
        problems.append("DASHBOARD: 'Progress by phase' table not found")
    else:
        for offset in range(1, 20):
            phase, _name, n, done = rows_of(dash.Range(f"E{header_row + offset}:H{header_row + offset}"))[0]
            want_n = sum(1 for t in tasks if float(t["Phase"]) == float(phase))
            want_done = sum(1 for t in tasks if float(t["Phase"]) == float(phase) and t["Status"] == "DONE")
            if float(n) != want_n or float(done) != want_done:
                problems.append(f"DASHBOARD phase {phase}: {n}/{done} vs data {want_n}/{want_done}")

    # every view row's Status equals MASTER
    checked = 0
    for ws in wb.Worksheets:
        if ws.Name in ("MASTER", "DASHBOARD", "CHANGE_LOG", "SESSION_STATE", "RELEASE_GATES"):
            continue
        used = rows_of(ws.UsedRange)
        in_view = False
        for row in used:
            first = row[0] if row else None
            if first == "ID" and len(row) > 5 and row[5] == "Status":
                in_view = True
                continue
            if in_view:
                if not first:
                    in_view = False
                    continue
                if first in status_of:
                    checked += 1
                    if row[5] != status_of[first]:
                        problems.append(f"{ws.Name} {first}: view status {row[5]!r} != MASTER {status_of[first]!r}")
    if checked == 0:
        problems.append("no view rows found to check")

    # findings
    fixes = rows_of(wb.Worksheets("CRITICAL_FIXES").UsedRange)
    header_idx = next((i for i, row in enumerate(fixes) if row and row[0] == "Finding ID"), None)
    if header_idx is None:
        problems.append("CRITICAL_FIXES: findings table not found")
    else:
        cols = {str(h): i for i, h in enumerate(fixes[header_idx]) if h}
        for row in fixes[header_idx + 1:]:
            if not row[0]:
                break
            ids = [x.strip() for x in str(row[cols["Fix Tasks"]] or "").split(",") if x.strip()]
            resolved = bool(ids) and all(status_of.get(x) == "DONE" for x in ids)
            if (row[cols["Status"]] == "RESOLVED") != resolved:
                problems.append(f"CRITICAL_FIXES {row[0]}: status {row[cols['Status']]} but resolved={resolved}")
    return problems


def strip_sensitivity_labels(path: Path) -> int:
    """Excel stamps MSIP_Label_* properties (with the organisation's tenant ID) into
    docProps/custom.xml on save; the repository is public, so remove them again."""
    with zipfile.ZipFile(path) as source:
        if "docProps/custom.xml" not in source.namelist():
            return 0
        xml = source.read("docProps/custom.xml").decode("utf-8")
        cleaned, removed = re.subn(r'<property[^>]*name="MSIP_Label_[^"]*"[^>]*>.*?</property>', "", xml, flags=re.S)
        if not removed:
            return 0
        tmp = path.with_name(f".{path.stem}.tmp-labels.xlsx")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as target:
            for item in source.infolist():
                data = cleaned.encode("utf-8") if item.filename == "docProps/custom.xml" else source.read(item.filename)
                target.writestr(item, data)
    os.replace(tmp, path)
    return removed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workbook", nargs="?", type=Path, default=DEFAULT)
    parser.add_argument("--check-only", action="store_true", help="verify without saving")
    args = parser.parse_args()
    path = args.workbook.resolve()
    for lock in (path.with_name("~$" + path.name), path.with_name("~$" + path.name[2:])):
        if lock.exists():
            print(json.dumps({"error": f"{path.name} is open in Excel; close it first"}))
            return 2
    pythoncom.CoInitialize()
    excel = win32com.client.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    wb = None
    try:
        wb = excel.Workbooks.Open(str(path), UpdateLinks=0, ReadOnly=args.check_only)
        excel.CalculateFull()
        total, errors = 0, []
        for ws in wb.Worksheets:
            try:
                total += ws.UsedRange.SpecialCells(XL_CELL_TYPE_FORMULAS).Count
            except pywintypes.com_error:
                continue
            try:
                for cell in ws.UsedRange.SpecialCells(XL_CELL_TYPE_FORMULAS, XL_ERRORS):
                    errors.append(f"{ws.Name}!{cell.Address.replace('$', '')}: {cell.Text}")
            except pywintypes.com_error:
                pass
        problems = verify(wb)
        if not args.check_only:
            wb.Save()
        result = {"status": "success" if not errors and not problems else "errors_found",
                  "sheets": wb.Worksheets.Count, "total_formulas": total, "total_errors": len(errors),
                  "errors": errors[:100], "value_mismatches": problems[:100], "saved": not args.check_only}
    finally:
        if wb is not None:
            wb.Close(SaveChanges=False)
        excel.Quit()
    if result["saved"]:
        result["sensitivity_label_properties_removed"] = strip_sensitivity_labels(path)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
