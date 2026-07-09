#!/usr/bin/env python3
"""
Architecture (per the deployment guidance):
  - 2010-2024 is baked into data/history_2010_2024.json
  - Only the CURRENT year (2025) is fetched live through Hermai
  - If the live fetch fails, we fall back to data/fallback_2025.json so the deploy still works.
  - The two are combined with IDENTICAL id cleaning on both sides, then streaks/chronic/hero
    are computed and baked into template.html -> index.html.
"""
import os, sys, json, io, time
import urllib.request, urllib.error
import pandas as pd, numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from nbi_codes import agency, IOWA_COUNTY

SITE_URL = os.environ.get("SITE_URL", "https://placeholder.github.io/").strip()
if not SITE_URL.endswith("/"): SITE_URL += "/"
API_KEY = os.environ.get("HERMAI_API_KEY", "").strip()
API_URL = "https://api.hermai.ai/v1/fetch"
CURRENT = 2025
YEARS = list(range(2010, 2026))          # full 16-year window for the panel
POST = {"A":"Open","B":"Open","D":"Open","E":"Open","G":"Not yet open","K":"CLOSED",
        "P":"Open, weight-posted","R":"Open, restricted"}

def log(*a): print("[build]", *a, flush=True)

# ---------- id cleaning: SAME on both sides (fixes the NaN-match crash) ----------
def clean_sn(x):
    """'000000000000060 ' -> 60 ; '60.0' -> 60 ; junk -> None"""
    if x is None: return None
    s = str(x).strip().strip("'").strip()
    if s == "" or s.lower() == "nan": return None
    try: return int(float(s))
    except Exception: return None

def num(s):  # unconvertible -> NaN instead of crashing
    return pd.to_numeric(s, errors="coerce")

# ---------- Hermai fetch (current year only, with retries) ----------
def fetch_current(retries=3, wait=6):
    sf = f"IA{CURRENT % 100:02d}"
    body = json.dumps({"site":"fhwa.dot.gov","endpoint":"nbi_state_bridges",
                       "params":{"year":str(CURRENT),"state_file":sf}}).encode()
    last = None
    for attempt in range(1, retries+1):
        try:
            req = urllib.request.Request(API_URL, data=body, method="POST")
            req.add_header("Authorization", "Bearer " + API_KEY)   # if 401/403, try "x-api-key"
            req.add_header("Content-Type", "application/json")
            log(f"fetching {sf} via Hermai (attempt {attempt}/{retries}) ...")
            with urllib.request.urlopen(req, timeout=180) as r:
                payload = json.loads(r.read().decode())
            if not payload.get("success"):
                raise RuntimeError(f"success=false: {payload.get('error')}")
            return payload["data"]
        except Exception as e:
            last = e; log(f"  attempt {attempt} failed: {repr(e)[:200]}")
            if attempt < retries: time.sleep(wait)
    raise RuntimeError(f"all {retries} attempts failed: {last!r}")

# ---------- turn raw NBI text (or the fallback json) into a slim 2025 frame ----------
def process_2025_from_csv(raw_text):
    df = pd.read_csv(io.StringIO(raw_text), dtype=str, low_memory=False)
    def col(c): return df[c] if c in df.columns else pd.Series([np.nan]*len(df))
    d=num(col("DECK_COND_058")); s_=num(col("SUPERSTRUCTURE_COND_059"))
    u=num(col("SUBSTRUCTURE_COND_060")); c=num(col("CULVERT_COND_062"))
    minr = pd.concat([d,s_,u,c],axis=1).min(axis=1)
    poor = pd.Series(pd.NA, index=df.index, dtype="Int64")
    poor[minr.notna()] = (minr[minr.notna()]<=4).astype("Int64")
    if poor.isna().all() and "BRIDGE_CONDITION" in df.columns:
        poor = col("BRIDGE_CONDITION").astype(str).str.upper().str[0].map({"P":1,"F":0,"G":0}).astype("Int64")
    def dms(v):
        try:
            v=int(v)
            if v<=0: return np.nan
            dd=v//1000000; r=v%1000000; mm=r//10000; ss=(r%10000)/100.0
            return dd+mm/60+ss/3600
        except Exception: return np.nan
    out = pd.DataFrame({
        "sn": col("STRUCTURE_NUMBER_008").map(clean_sn), "poor": poor,
        "county_code": num(col("COUNTY_CODE_003")),
        "carries": col("FACILITY_CARRIED_007").astype(str).str.strip().str.strip("'").str.strip(),
        "crosses": col("FEATURES_DESC_006A").astype(str).str.strip().str.strip("'").str.strip(),
        "owner_code": num(col("OWNER_022")),
        "year_built": num(col("YEAR_BUILT_027")), "year_recon": num(col("YEAR_RECONSTRUCTED_106")),
        "adt": num(col("ADT_029")), "adt_year": num(col("YEAR_ADT_030")),
        "truck_pct": num(col("PERCENT_ADT_TRUCK_109")),
        "lat": col("LAT_016").map(dms),
        "lon": col("LONG_017").map(dms).map(lambda x: -x if pd.notna(x) else np.nan),
        "status_code": col("OPEN_CLOSED_POSTED_041").astype(str).str.strip(),
    })
    return out.dropna(subset=["sn"]).drop_duplicates(subset=["sn"], keep="first")

def load_fallback_2025():
    recs = json.load(open(os.path.join(ROOT,"data","fallback_2025.json")))
    df = pd.DataFrame(recs)
    df["sn"] = df["sn"].map(clean_sn)
    return df.dropna(subset=["sn"]).drop_duplicates(subset=["sn"], keep="first")

def get_2025():
    if API_KEY:
        try:
            return process_2025_from_csv(fetch_current()), "live Hermai"
        except Exception as e:
            log("WARNING: live 2025 fetch failed -> using saved fallback. Reason:", repr(e)[:200])
    else:
        log("No HERMAI_API_KEY -> using saved fallback for 2025.")
    return load_fallback_2025(), "saved fallback"

# ---------- combine + compute ----------
def build_D():
    hist = json.load(open(os.path.join(ROOT,"data","history_2010_2024.json")))  # {sn(str):[15]}
    hist = {clean_sn(k): v for k,v in hist.items()}                              # clean ids too
    df25, src = get_2025()
    log(f"2025 rows: {len(df25)} (source: {src})")

    poor25 = {int(r.sn): (int(r.poor) if pd.notna(r.poor) else None) for r in df25.itertuples()}
    meta = df25.set_index("sn")

    all_sns = set(hist) | set(poor25)
    rows = []
    for sn in all_sns:
        flags = list(hist.get(sn, [None]*15)) + [poor25.get(sn)]     # 16 flags
        # streak of consecutive Poor years ending 2025 (None or 0 breaks it)
        streak = 0
        for v in reversed(flags):
            if v == 1: streak += 1
            else: break
        rows.append((sn, streak))
    st = pd.DataFrame(rows, columns=["sn","streak"]).set_index("sn")

    def gi(sn, c):                         # guarded int from 2025 meta
        if sn not in meta.index: return None
        v = meta.at[sn, c]
        return int(v) if pd.notna(v) else None
    def gf(sn, c):
        if sn not in meta.index: return None
        v = meta.at[sn, c]
        return round(float(v),5) if pd.notna(v) else None
    def gs(sn, c):
        if sn not in meta.index: return ""
        v = meta.at[sn, c]
        return "" if pd.isna(v) else str(v)

    def rec(sn, tl=False):
        streak = int(st.at[sn,"streak"]) if sn in st.index else 0
        r = {"sn": int(sn), "carries": gs(sn,"carries"), "crosses": gs(sn,"crosses"),
             "county": IOWA_COUNTY.get(gi(sn,"county_code"),""),
             "owner_code": gi(sn,"owner_code"),
             "owner": agency(gi(sn,"owner_code"), 19, gi(sn,"county_code")),
             "year_built": gi(sn,"year_built"), "year_recon": (gi(sn,"year_recon") or None),
             "adt": gi(sn,"adt") or 0, "adt_year": gi(sn,"adt_year"),
             "truck_pct": gi(sn,"truck_pct"),
             "streak": streak, "poor_since": 2026-streak,
             "status": POST.get(gs(sn,"status_code").strip(), gs(sn,"status_code").strip()),
             "lat": gf(sn,"lat"), "lon": gf(sn,"lon"),
             "img": None, "img_credit": None, "news": None, "nickname": None}
        if r["year_recon"] is not None and r["year_recon"] <= 0: r["year_recon"] = None
        if tl:
            flags = list(hist.get(sn,[None]*15)) + [poor25.get(sn)]
            r["timeline"] = ["P" if f==1 else ("FG" if f==0 else "-") for f in flags]
        return r

    poor_sns = [sn for sn,p in poor25.items() if p==1]
    poor_meta = meta.loc[[s for s in poor_sns if s in meta.index]].copy()
    poor_meta["adt"] = num(poor_meta["adt"]).fillna(0).astype(int)
    poor_meta = poor_meta.sort_values("adt", ascending=False)

    hero = rec(int(poor_meta.index[0]), tl=True)          # busiest Poor bridge in 2025
    chronic_sns = [sn for sn in poor_sns if st.at[sn,"streak"]==16]
    chr_sorted = poor_meta.loc[[s for s in chronic_sns if s in poor_meta.index]].index.tolist()
    bridges = [rec(int(sn)) for sn in chr_sorted[:100]]

    total_daily = int(poor_meta["adt"].sum())
    poor10 = int((st["streak"]>=10).sum())
    cc = pd.Series([gi(sn,"owner_code") for sn in chronic_sns])
    stats = {"chronic": len(chronic_sns), "poor25": len(poor_sns),
             "total_daily": total_daily, "poor10": poor10,
             "county_share": int(round((cc.eq(2).mean()*100))) if len(cc) else 0}
    mp = [[gf(sn,"lat"), gf(sn,"lon"), int(poor_meta.at[sn,"adt"])]
          for sn in chronic_sns if sn in poor_meta.index and gf(sn,"lat") is not None]
    owner_chronic = {"County": int(cc.eq(2).sum()), "City / Municipal": int(cc.eq(4).sum()),
                     "Iowa DOT (State)": int(cc.eq(1).sum())}
    log(f"chronic (Poor all 16 yrs)={stats['chronic']}  poor2025={stats['poor25']}  hero=sn {hero['sn']} ({hero['carries']})")
    return {"hero": hero, "stats": stats, "bridges": bridges, "map": mp, "owner_chronic": owner_chronic}

def merge_news(D):
    path = os.path.join(ROOT,"data","news.json")
    if not os.path.exists(path): return
    news = json.load(open(path))
    def attach(b):
        n = news.get(str(b.get("sn")))
        if not n: return
        b["news"] = {k:n[k] for k in ("status","source","domain","url","date") if k in n}
        for k in ("nickname","img","img_credit"):
            if n.get(k): b[k] = n[k]
    attach(D["hero"])
    for b in D["bridges"]: attach(b)

def main():
    D = build_D()
    merge_news(D)
    tpl = open(os.path.join(ROOT,"template.html")).read()
    html = tpl.replace("__DATA__", json.dumps(D, separators=(",",":"))).replace("__SITE_URL__", SITE_URL)
    open(os.path.join(ROOT,"index.html"),"w").write(html)
    log(f"wrote index.html (SITE_URL={SITE_URL}, bridges={len(D['bridges'])}, map={len(D['map'])})")

if __name__ == "__main__":
    main()
