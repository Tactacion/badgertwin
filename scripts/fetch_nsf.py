"""Pull UW–Madison NSF awards (start date 2023+) from the public NSF Award Search API."""
import csv, json, sys, time, urllib.parse, urllib.request

OUT = sys.argv[1]
FIELDS = "id,title,fundsObligatedAmt,estimatedTotalAmt,piFirstName,piLastName,startDate,expDate,fundProgramName,directorate,divi,awardeeName"
rows, offset = [], 1
while True:
    q = urllib.parse.urlencode({"awardeeName": '"University of Wisconsin-Madison"', "startDateStart": "01/01/2023",
                                "printFields": FIELDS, "rpp": 25, "offset": offset})
    d = json.load(urllib.request.urlopen("https://api.nsf.gov/services/v1/awards.json?" + q, timeout=60))
    batch = d["response"].get("award", [])
    for a in batch:
        rows.append({k: a.get(k) for k in FIELDS.split(",")})
    if len(batch) < 25 or offset > 3000:
        break
    offset += 25
    time.sleep(0.3)
with open(OUT, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=FIELDS.split(",")); w.writeheader(); w.writerows(rows)
print(len(rows), "rows")
