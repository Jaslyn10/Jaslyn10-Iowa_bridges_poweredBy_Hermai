#!/usr/bin/env python3
"""
Build step for the Iowa Poor-Bridges site.

WHAT IT DOES (this runs in GitHub Actions, never in the visitor's browser):
  1. Pulls the 16 yearly NBI files (IA10..IA25) THROUGH Hermai, using the API key
     that lives only in a GitHub Secret.
  2. Computes everything (Poor flag, streaks, the 1,294 chronic set, the hero bridge,
     stats) exactly like the notebook did.
  3. Merges the hand-curated news from data/news.json.
  4. Bakes the finished data + your real domain into template.html -> index.html.

SAFETY: if the API key is missing or any fetch/compute step fails, it falls back to
the committed data/site_data.json so the deploy still succeeds. That means your FIRST
deploy works even before the Hermai call is proven, and a bad API day never takes the
site down.
"""
import os, sys, json, io, time
import urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from nbi_codes import agency, IOWA_COUNTY   # local codebook module

SITE_URL = os.environ.get("SITE_URL", "https://placeholder.github.io/").strip()
if not SITE_URL.endswith("/"):
    SITE_URL += "/"
API_KEY = os.environ.get("HERMAI_API_KEY", "").strip()
API_URL = "https://api.hermai.ai/v1/fetch"
YEARS = list(range(2010, 2026))

def log(*a): print("[build]", *a, flush=True)

# ---------- Hermai fetch ----------
def fetch_year(state_file):
    body = json.dumps({"site": "fhwa.dot.gov", "endpoint": "nbi_state_bridges",
                       "params": {"year": "20" + state_file[2:], "state_file": state_file}}).encode()
    req = urllib.request.Request(API_URL, data=body, method="POST")
    req.add_header("x-api-key", API_KEY)
    req.add_header("Authorization", "Bearer " + API_KEY)
    with urllib.request.urlopen(req, timeout=120) as r:
        payload = json.loads(r.read().decode())
    if not payload.get("success"):
        raise RuntimeError(f"Hermai returned success=false for {state_file}")
    return payload["data"]

# ---------- compute (mirrors the notebook) ----------
def compute():
    import pandas as pd, numpy as np
    def dms(v):
        try:
            v = int(v)
            if v <= 0: return np.nan
            d = v//1000000; r = v % 1000000; m = r//10000; s = (r % 10000)/100.0
            return d + m/60 + s/3600
        except Exception: return np.nan
    def norm_sn(x):
        try: return int(float(str(x).strip().strip("'")))
        except Exception: return None
    def numc(df, c): return pd.to_numeric(df[c], errors="coerce") if c in df.columns else pd.Series(np.nan, index=df.index)
    def col(df, c): return df[c] if c in df.columns else pd.Series(np.nan, index=df.index)

    per_year = {}
    for y in YEARS:
        sf = f"IA{y % 100:02d}"
        log(f"fetching {sf} via Hermai ...")
        raw = fetch_year(sf)
        df = pd.read_csv(io.StringIO(raw), dtype=str, low_memory=False)
        d = numc(df,"DECK_COND_058"); s_ = numc(df,"SUPERSTRUCTURE_COND_059")
        u = numc(df,"SUBSTRUCTURE_COND_060"); c = numc(df,"CULVERT_COND_062")
        comp = pd.concat([d,s_,u,c], axis=1)
        minr = comp.min(axis=1)
        poor = pd.Series(pd.NA, index=df.index, dtype="Int64")
        poor[minr.notna()] = (minr[minr.notna()] <= 4).astype("Int64")
        if poor.isna().all() and "BRIDGE_CONDITION" in df.columns:      # safety net for odd years
            bc = col(df,"BRIDGE_CONDITION").astype(str).str.upper().str[0]
            poor = bc.map({"P":1,"F":0,"G":0}).astype("Int64")
        out = pd.DataFrame({
            "year": y, "sn": col(df,"STRUCTURE_NUMBER_008").map(norm_sn),
            "county_code": numc(df,"COUNTY_CODE_003"),
            "carries": col(df,"FACILITY_CARRIED_007").astype(str).str.strip().str.strip("'").str.strip(),
            "crosses": col(df,"FEATURES_DESC_006A").astype(str).str.strip().str.strip("'").str.strip(),
            "owner_code": numc(df,"OWNER_022"),
            "year_built": numc(df,"YEAR_BUILT_027"), "year_recon": numc(df,"YEAR_RECONSTRUCTED_106"),
            "adt": numc(df,"ADT_029"), "adt_year": numc(df,"YEAR_ADT_030"),
            "truck_pct": numc(df,"PERCENT_ADT_TRUCK_109"),
            "poor": poor, "lat": col(df,"LAT_016").map(dms),
            "lon": col(df,"LONG_017").map(dms).map(lambda x: -x if pd.notna(x) else np.nan),
            "status_code": col(df,"OPEN_CLOSED_POSTED_041").astype(str).str.strip(),
        }).dropna(subset=["sn"]).drop_duplicates(subset=["sn"], keep="first")
        per_year[y] = out

    allp = pd.concat(per_year.values(), ignore_index=True)
    pw = allp.pivot_table(index="sn", columns="year", values="poor", aggfunc="first").reindex(columns=YEARS)
    pw0 = pw.fillna(0).astype(int); arr = pw0[YEARS].to_numpy(); sns = pw.index.to_numpy()
    streak = np.zeros(len(sns), int)
    for i in range(len(sns)):
        cnt = 0
        for j in range(len(YEARS)-1, -1, -1):
            if arr[i, j] == 1: cnt += 1
            else: break
        streak[i] = cnt
    st = pd.DataFrame({"sn": sns, "streak": streak})
    POST = {"A":"Open","B":"Open","D":"Open","E":"Open","G":"Not yet open","K":"CLOSED","P":"Open, weight-posted","R":"Open, restricted"}
    m = per_year[2025].merge(st, on="sn", how="left"); m["adt"] = m["adt"].fillna(0).astype(int)
    def cc(c): return IOWA_COUNTY.get(int(c), "") if pd.notna(c) else ""
    def rec(row, tl=False):
        sn = row["sn"]
        r = {"sn": int(sn), "carries": str(row["carries"]), "crosses": str(row["crosses"]),
             "county": cc(row["county_code"]),
             "owner_code": int(row["owner_code"]) if pd.notna(row["owner_code"]) else None,
             "owner": agency(row["owner_code"], 19, row["county_code"]),
             "year_built": int(row["year_built"]) if pd.notna(row["year_built"]) else None,
             "year_recon": int(row["year_recon"]) if pd.notna(row["year_recon"]) and row["year_recon"]>0 else None,
             "adt": int(row["adt"]), "adt_year": int(row["adt_year"]) if pd.notna(row["adt_year"]) else None,
             "truck_pct": int(row["truck_pct"]) if pd.notna(row["truck_pct"]) else None,
             "streak": int(row["streak"]), "poor_since": int(2026-row["streak"]),
             "status": POST.get(str(row["status_code"]).strip(), str(row["status_code"]).strip()),
             "lat": round(float(row["lat"]),5) if pd.notna(row["lat"]) else None,
             "lon": round(float(row["lon"]),5) if pd.notna(row["lon"]) else None,
             "img": None, "img_credit": None, "news": None, "nickname": None}
        if tl:
            r["timeline"] = [("P" if pw.loc[sn,y]==1 else ("FG" if pw.loc[sn,y]==0 else "-")) for y in YEARS]
        return r
    poor25 = m[m["poor"] == 1].copy()
    hero = rec(poor25.sort_values("adt", ascending=False).iloc[0], tl=True)
    chronic = poor25[poor25["streak"] == 16].sort_values("adt", ascending=False)
    bridges = [rec(r) for _, r in chronic.head(100).iterrows()]
    stats = {"chronic": int(len(chronic)), "poor25": int(len(poor25)),
             "total_daily": int(poor25["adt"].sum()), "poor10": int((st["streak"]>=10).sum()),
             "county_share": round(chronic["owner_code"].eq(2).mean()*100)}
    mp = [[round(float(r["lat"]),5), round(float(r["lon"]),5), int(r["adt"])]
          for _, r in chronic.iterrows() if pd.notna(r["lat"])]
    owner_chronic = {"County": int(chronic["owner_code"].eq(2).sum()),
                     "City / Municipal": int(chronic["owner_code"].eq(4).sum()),
                     "Iowa DOT (State)": int(chronic["owner_code"].eq(1).sum())}
    return {"hero": hero, "stats": stats, "bridges": bridges, "map": mp, "owner_chronic": owner_chronic}

# ---------- news merge ----------
def merge_news(D):
    path = os.path.join(ROOT, "data", "news.json")
    if not os.path.exists(path): return
    news = json.load(open(path))
    def attach(b):
        n = news.get(str(b.get("sn")))
        if n:
            b["news"] = {k: n[k] for k in ("status","source","domain","url","date") if k in n}
            if n.get("nickname"): b["nickname"] = n["nickname"]
            if n.get("img"): b["img"] = n["img"]
            if n.get("img_credit"): b["img_credit"] = n["img_credit"]
    attach(D["hero"])
    for b in D.get("bridges", []): attach(b)

# ---------- main ----------
def main():
    D = None
    if API_KEY:
        try:
            D = compute()
            log("computed fresh data from Hermai OK.")
        except Exception as e:
            log("WARNING: Hermai fetch/compute failed -> using committed fallback. Reason:", repr(e))
    else:
        log("No HERMAI_API_KEY set -> using committed fallback data/site_data.json.")
    if D is None:
        D = json.load(open(os.path.join(ROOT, "data", "site_data.json")))
    merge_news(D)

    tpl = open(os.path.join(ROOT, "template.html")).read()
    html = tpl.replace("__DATA__", json.dumps(D, separators=(",", ":"))).replace("__SITE_URL__", SITE_URL)
    out = os.path.join(ROOT, "index.html")
    open(out, "w").write(html)
    log(f"wrote {out}  (SITE_URL={SITE_URL}, bridges={len(D.get('bridges',[]))}, map={len(D.get('map',[]))})")

if __name__ == "__main__":
    main()
