"""Pull UW–Madison NIH awards (FY2025-2026) from the public NIH RePORTER API."""
import csv, json, sys, time, urllib.request

OUT = sys.argv[1]
URL = "https://api.reporter.nih.gov/v2/projects/search"
FIELDS = ["ApplId", "ProjectNum", "ProjectTitle", "AwardAmount", "ContactPiName",
          "Organization", "AgencyIcAdmin", "ProjectStartDate", "ProjectEndDate",
          "ActivityCode", "FiscalYear"]

rows = []
for fy in (2025, 2026):
    offset = 0
    while True:
        body = {"criteria": {"org_names": ["UNIVERSITY OF WISCONSIN-MADISON"], "fiscal_years": [fy]},
                "include_fields": FIELDS, "offset": offset, "limit": 500}
        req = urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
        d = json.load(urllib.request.urlopen(req, timeout=60))
        for r in d["results"]:
            org = r.get("organization") or {}
            rows.append({
                "fiscal_year": r.get("fiscal_year"), "project_num": r.get("project_num"),
                "title": r.get("project_title"), "award_amount_usd": r.get("award_amount"),
                "pi": (r.get("contact_pi_name") or "").strip(),
                "dept": org.get("org_dept"), "dept_type": org.get("dept_type"),
                "institute": (r.get("agency_ic_admin") or {}).get("abbreviation"),
                "activity_code": r.get("activity_code"),
                "start": r.get("project_start_date"), "end": r.get("project_end_date")})
        offset += 500
        if offset >= d["meta"]["total"] or offset >= 14500:
            break
        time.sleep(1)

with open(OUT, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader(); w.writerows(rows)
print(len(rows), "rows")
