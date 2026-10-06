# -*- coding: utf-8 -*-
"""猫耳三榜单 GitHub Pages Dashboard。
核心原则：以「榜单 + 剧集ID」识别剧目，不以剧名识别。
"""
from __future__ import annotations
import datetime as dt
import html, json, math, os, re, shutil
from pathlib import Path
import numpy as np
import pandas as pd
from pypinyin import lazy_pinyin, Style

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "raw"
OUTPUT_DIR = BASE_DIR / "site"
EXPORT_DIR = BASE_DIR / "exports"
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_DAYS = 30
BOARDS = {
    "sales": {"label":"销量月榜", "prefix":"猫耳销量月榜", "json":"sales.json", "detail":"sales", "sales":True},
    "popularity": {"label":"人气月榜", "prefix":"猫耳人气月榜", "json":"popularity.json", "detail":"popularity", "sales":False},
    "new": {"label":"新品日榜", "prefix":"猫耳新品日榜", "json":"new.json", "detail":"new", "sales":False},
}
ID_CANDIDATES = ["剧集ID","剧集 Id","剧集id","作品ID","作品id","drama_id","dramaId","Drama_ID","ID","id","音频ID"]
TIME_CANDIDATES = ["抓取时间","采集时间","抓取日期","采集日期","表格时间","榜单时间","榜单日期","统计时间","更新时间","生成时间","下载时间","时间","日期时间"]

def norm(x):
    return str(x).strip().replace(" ","").replace("\u3000","").replace("_","").lower()

def find_col(df, candidates):
    for c in candidates:
        if c in df.columns: return c
    m={norm(c):c for c in df.columns}
    for c in candidates:
        if norm(c) in m: return m[norm(c)]
    return None

def initial(x):
    s="" if x is None else str(x).strip()
    if not s:return "#"
    try:
        p=lazy_pinyin(s[0],style=Style.FIRST_LETTER)
        if p and p[0].isalpha(): return p[0].upper()
    except Exception: pass
    return s[0].upper() if s[0].isalpha() else "#"

def jval(v):
    if v is None:return None
    try:
        if pd.isna(v):return None
    except Exception:pass
    if isinstance(v,(np.integer,)):return int(v)
    if isinstance(v,(np.floating,)):
        return None if math.isnan(float(v)) else float(v)
    if isinstance(v,(pd.Timestamp,dt.datetime,dt.date)):return v.strftime("%Y-%m-%d")
    return v

def records(df):
    return [{str(c):jval(row[c]) for c in df.columns} for _,row in df.iterrows()]

def date_from_name(path):
    for s in reversed(re.findall(r"(20\d{6})",Path(path).name)):
        try:return dt.datetime.strptime(s,"%Y%m%d").strftime("%Y-%m-%d")
        except ValueError:pass
    return None

def datetime_from_name(path):
    n=Path(path).name
    for d,t in reversed(re.findall(r"(20\d{6})[_-](\d{4,6})",n)):
        try:return dt.datetime.strptime(d+t,"%Y%m%d%H%M" if len(t)==4 else "%Y%m%d%H%M%S")
        except ValueError:pass
    d=date_from_name(path)
    return dt.datetime.strptime(d,"%Y-%m-%d") if d else None

def table_datetime(df):
    for c in TIME_CANDIDATES:
        col=find_col(df,[c])
        if col:
            x=pd.to_datetime(df[col],errors="coerce").dropna()
            if not x.empty:return x.max().to_pydatetime()
    return None

def read_csv(path):
    try:
        try:return pd.read_csv(path,encoding="utf-8-sig")
        except UnicodeDecodeError:return pd.read_csv(path,encoding="gb18030")
    except Exception as e:
        print(f"⚠️ 读取失败 {path.name}: {e}"); return None

def standardize(df):
    df=df.copy(); df.columns=[str(c).strip() for c in df.columns]
    idc=find_col(df,ID_CANDIDATES)
    if idc and idc!="剧集ID":df.rename(columns={idc:"剧集ID"},inplace=True)
    if "剧集ID" not in df:df["剧集ID"]=None
    nc=find_col(df,["剧名","作品名","剧目","作品","名称","标题"])
    if nc and nc!="剧名":df.rename(columns={nc:"剧名"},inplace=True)
    rc=find_col(df,["排名","名次","rank","Rank"])
    if rc and rc!="排名":df.rename(columns={rc:"排名"},inplace=True)
    if "剧名" not in df:df["剧名"]=""
    if "排名" not in df:df["排名"]=np.nan
    df["剧名"]=df["剧名"].fillna("").astype(str).str.strip()
    df["排名"]=pd.to_numeric(df["排名"],errors="coerce")
    df["剧集ID"]=df["剧集ID"].map(lambda x:None if pd.isna(x) or str(x).strip() in ("","nan","None") else str(x).strip())
    return df

def load_board(board):
    cfg=BOARDS[board]
    files=[p for p in DATA_DIR.glob("*.csv") if cfg["prefix"] in p.name]
    versions={}
    for p in files:
        date=date_from_name(p)
        if not date:continue
        df=read_csv(p)
        if df is None or df.empty:continue
        df=standardize(df)
        priority=table_datetime(df) or datetime_from_name(p) or dt.datetime.fromtimestamp(p.stat().st_mtime)
        versions.setdefault(date,[]).append((priority,p,df))
    chosen=[]
    for date,items in sorted(versions.items()):
        items.sort(key=lambda x:x[0]); priority,p,df=items[-1]
        if len(items)>1:print(f"🔁 {cfg['label']} {date}: 使用 {p.name} ({priority:%Y-%m-%d %H:%M:%S})")
        df=df.copy(); df["日期"]=date; df["来源文件"]=p.name; df["版本时间"]=priority.strftime("%Y-%m-%d %H:%M:%S")
        chosen.append(df)
    if not chosen:return None
    df=pd.concat(chosen,ignore_index=True)
    df=df.dropna(subset=["排名"])
    df=df[(df["剧名"]!="")&(df["剧名"].str.lower()!="nan")].copy()
    has=df["剧集ID"].notna()
    a=df[has].drop_duplicates(["日期","剧集ID"],keep="last")
    b=df[~has].drop_duplicates(["日期","剧名","排名"],keep="last")
    df=pd.concat([a,b],ignore_index=True)
    df["首字母"]=df["剧名"].map(initial); df["榜单"]=board
    df.sort_values(["日期","排名","剧集ID","剧名"],na_position="last",inplace=True)
    df.reset_index(drop=True,inplace=True)
    print(f"✅ {cfg['label']}: {df['日期'].min()} → {df['日期'].max()} | {len(df):,} 条 | ID {df['剧集ID'].nunique(dropna=True):,}")
    return df

def metrics(df):
    return {
        "play":find_col(df,["播放量","播放","播放数","播放次数","VV"]),
        "subscribe":find_col(df,["订阅数","订阅","收藏数","收藏"]),
        "total_id":find_col(df,["全部集弹幕UID数","全部ID数","全部ID","全部UID","全部集UID数","弹幕UID数","UID数"]),
        "paid_id":find_col(df,["付费集弹幕UID数","付费ID数","付费ID","付费UID","付费集UID数"]),
        "total_episodes":find_col(df,["总集数","集数","总集"]),
        "paid_episodes":find_col(df,["付费集数","付费集"]),
        "latest_update":find_col(df,["最新更新","更新","最新更新内容"]),
    }

def calculate_rank_score(df, start_date=None, end_date=None, rank_limit=50):
    empty={"score":None,"days":0,"total_days":0,"days_rate":0,"avg_rank":None,"best_rank":None,"top3_days":0,"top10_days":0,"top20_days":0,"top3_rate":0,"top10_rate":0,"top20_rate":0,"rank_quality":0,"rank_points":0,"avg_daily_points":0}
    if df is None or df.empty:return empty
    x=df.copy();x["日期"]=pd.to_datetime(x["日期"],errors="coerce");x["排名"]=pd.to_numeric(x["排名"],errors="coerce")
    x=x.dropna(subset=["日期","排名"]);x=x[(x["排名"]>=1)&(x["排名"]<=rank_limit)]
    if x.empty:return empty
    if start_date is not None:start_date=pd.to_datetime(start_date)
    if end_date is not None:end_date=pd.to_datetime(end_date)
    if start_date is None:start_date=x["日期"].min()
    if end_date is None:end_date=x["日期"].max()
    if start_date>end_date:return empty
    x=x[(x["日期"]>=start_date)&(x["日期"]<=end_date)]
    if x.empty:
        empty["total_days"]=int((end_date-start_date).days+1);return empty
    x=x.sort_values(["日期","排名"]).drop_duplicates(["日期"],keep="first")
    total_days=int((end_date-start_date).days+1);days=int(len(x));days_rate=days/total_days if total_days else 0
    x["rank_quality"]=(rank_limit+1-x["排名"])/rank_limit;rank_quality=float(x["rank_quality"].mean())
    top3_days=int((x["排名"]<=3).sum());top10_days=int((x["排名"]<=10).sum());top20_days=int((x["排名"]<=20).sum())
    top3_rate=top3_days/total_days if total_days else 0;top10_rate=top10_days/total_days if total_days else 0;top20_rate=top20_days/total_days if total_days else 0
    rank_points=int((rank_limit+1-x["排名"]).sum());avg_daily_points=rank_points/days if days else 0
    score = 100 * ( 0.30 * days_rate + 0.50 * rank_quality + 0.08 * top3_rate + 0.08 * top10_rate + 0.04 * top20_rate )
    return {"score":round(score,2),"days":days,"total_days":total_days,"days_rate":round(days_rate,4),"avg_rank":round(float(x["排名"].mean()),2),"best_rank":int(x["排名"].min()),"top3_days":top3_days,"top10_days":top10_days,"top20_days":top20_days,"top3_rate":round(top3_rate,4),"top10_rate":round(top10_rate,4),"top20_rate":round(top20_rate,4),"rank_quality":round(rank_quality,4),"rank_points":rank_points,"avg_daily_points":round(avg_daily_points,1)}

CSS=r'''<style>
:root{--bg:#0d0f12;--panel:#171a1f;--panel2:#111419;--line:#2b3037;--text:#f3efe5;--muted:#a6a198;--gold:#d8b46a;--gold2:#f0d28b;--green:#6bc28c;--red:#e47d76;--blue:#78a6d8}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 10% -10%,rgba(216,180,106,.1),transparent 30%),var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}.container{width:min(1500px,94%);margin:auto;padding:24px 0 60px}.topbar{position:sticky;top:0;z-index:30;background:rgba(13,15,18,.93);backdrop-filter:blur(12px);border-bottom:1px solid rgba(216,180,106,.15)}.nav{width:min(1500px,94%);min-height:64px;margin:auto;display:flex;align-items:center;gap:22px}.brand{font-weight:850;white-space:nowrap}.brand small{display:block;color:var(--muted);font-size:9px;letter-spacing:2px}.navlinks{display:flex;gap:3px;overflow:auto}.navlinks a{color:#aaa69e;text-decoration:none;padding:9px 14px;border-radius:99px;font-size:13px;font-weight:750;white-space:nowrap}.navlinks a:hover,.navlinks a.active{color:var(--gold2);background:rgba(216,180,106,.1)}.hero{padding:34px 36px;border:1px solid rgba(216,180,106,.2);border-radius:20px;background:linear-gradient(135deg,rgba(255,255,255,.04),rgba(255,255,255,.012)),#111419;box-shadow:0 18px 50px rgba(0,0,0,.2);margin:22px 0}.eyebrow{font-size:10px;font-weight:850;letter-spacing:2.5px;color:var(--gold)}h1{margin:8px 0;font-size:clamp(28px,4vw,42px)}.hero p{margin:0;color:var(--muted);font-size:13px}.panel{background:linear-gradient(145deg,rgba(255,255,255,.035),rgba(255,255,255,.012));border:1px solid var(--line);border-radius:15px;padding:19px;margin-bottom:17px}
.filters{display:flex;flex-wrap:wrap;gap:12px;}
.filter{flex:1 1 180px;min-width:160px;}
.filter label{display:block;color:var(--muted);font-size:11px;font-weight:750;margin-bottom:6px}input,select{width:100%;height:41px;border:1px solid #353a42;border-radius:9px;background:#101318;color:var(--text);padding:0 10px;outline:none}input:focus,select:focus{border-color:var(--gold)}button{border:1px solid rgba(216,180,106,.35);background:linear-gradient(135deg,#a67b35,#d8b46a);color:#17130b;height:40px;border-radius:9px;padding:0 14px;font-weight:850;cursor:pointer}.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:11px;margin-bottom:17px}.stat{background:#15181d;border:1px solid var(--line);border-radius:13px;padding:16px}.stat .label{font-size:10px;color:var(--muted)}.stat .value{font-size:25px;font-weight:850;margin-top:5px}.gold{color:var(--gold2)}.section-head{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:12px}.section-head h2{margin:0;font-size:17px}.muted{font-size:11px;color:var(--muted)}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:11px}table{width:100%;border-collapse:collapse}th{background:#111419;color:#aaa69f;font-size:10px;padding:11px;text-align:left;white-space:nowrap;border-bottom:1px solid var(--line)}td{font-size:12px;padding:11px;border-bottom:1px solid rgba(43,48,55,.7);white-space:nowrap}tbody tr:hover td{background:rgba(216,180,106,.035)}.drama-link{border:0;background:none;color:var(--text);padding:0;height:auto;font-weight:750;cursor:pointer;text-decoration:none}.drama-link:hover{color:var(--gold2)}.id-text{color:#98948d;font:11px ui-monospace,SFMono-Regular,Menlo,monospace}.badge{display:inline-flex;padding:4px 8px;border-radius:99px;font-size:10px;font-weight:800}.badge.gold{color:var(--gold2);background:rgba(216,180,106,.1)}.badge.green{color:var(--green);background:rgba(107,194,140,.09)}.badge.red{color:var(--red);background:rgba(228,125,118,.09)}.badge.blue{color:var(--blue);background:rgba(120,166,216,.09)}.badge.gray{color:#aaa69f;background:rgba(170,166,159,.08)}.detail-title{font-size:30px;font-weight:900}.score-value{color:var(--gold2);font-weight:900}.detail-id{margin-top:6px;color:var(--gold);font:12px ui-monospace,monospace}.lifecycle-score{display:grid;grid-template-columns:250px 1fr;gap:20px;align-items:stretch;margin-bottom:17px}.score-main{background:linear-gradient(145deg,#fffdf7,#fff);border:1px solid #e2d2a9;border-radius:14px;padding:20px 22px;display:flex;flex-direction:column;justify-content:center}.score-main .score-label{font-size:12px;color:#7b8490;font-weight:800}.score-main .score-number{font-size:42px;line-height:1.05;font-weight:900;color:#a67b35;margin-top:8px}.score-main .score-sub{font-size:11px;color:#7b8490;margin-top:7px}.score-metrics{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}.score-metric{background:#fff;border:1px solid #dfe3e8;border-radius:11px;padding:12px 14px}.score-metric .label{font-size:10px;color:#7b8490}.score-metric .value{font-size:16px;font-weight:850;color:#20252b;margin-top:5px}.score-metric .value.gold{color:#a67b35}.info-grid>.lifecycle-score{grid-column:1/-1}.period-score-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}.period-score-card{background:#fff;border:1px solid #dfe3e8;border-radius:11px;padding:13px}.period-score-card .label{font-size:10px;color:#7b8490}.period-score-card .value{font-size:18px;font-weight:850;color:#20252b;margin-top:5px}.period-score-card .value.gold{color:#a67b35}@media(max-width:780px){.period-score-grid{grid-template-columns:repeat(2,1fr)}}
.detail-controls{display:grid;grid-template-columns:180px 180px 230px;gap:11px;align-items:end}.segment{display:flex;border:1px solid var(--line);border-radius:9px;overflow:hidden}.segment button{flex:1;border:0;border-radius:0;background:#101318;color:#aaa69f}.segment button.active{background:rgba(216,180,106,.16);color:var(--gold2)}.info-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:9px}.info-card{background:#14171b;border:1px solid var(--line);border-radius:11px;padding:13px}.info-label{font-size:10px;color:var(--muted)}.info-value{font-size:15px;font-weight:850;margin-top:5px;word-break:break-all}.chart-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.chart-card{background:#14171b;border:1px solid var(--line);border-radius:13px;padding:14px}.chart-title{font-size:15px;font-weight:850}.chart-sub{font-size:10px;color:var(--muted);margin-top:4px}.chart{height:370px}.back{display:inline-block;color:var(--gold2);text-decoration:none;font-size:12px;font-weight:800;margin-bottom:12px}.empty{text-align:center;color:var(--muted);padding:35px}.footer{text-align:center;color:#6d6962;font-size:10px;padding:24px}

.theme-buttons{display:flex;gap:6px;}
.theme-btn{height:41px!important;background:#101318!important;color:#aaa69f!important;border:1px solid #353a42!important;cursor:pointer;}
.theme-btn.active{background:rgba(216,180,106,.2)!important;color:var(--gold2)!important;border-color:rgba(216,180,106,.6)!important;}

#homeTableWrap.theme-day table,
#homeTableWrap.theme-day table tr,
#homeTableWrap.theme-day table td { background-color: #ffffff !important; color: #20252b !important; border-bottom-color: #e5e7eb; }
#homeTableWrap.theme-day table th { background-color: #f0f2f4 !important; color: #59616b !important; }
#homeTableWrap.theme-day .drama-link { color: #20252b !important; }

#homeTableWrap.theme-night table,
#homeTableWrap.theme-night table tr,
#homeTableWrap.theme-night table td { background-color: #171a1f !important; color: #f3efe5 !important; border-bottom-color: #2b3037; }
#homeTableWrap.theme-night table th { background-color: #111419 !important; color: #aaa69f !important; }
#homeTableWrap.theme-night .drama-link { color: #f3efe5 !important; }

@media(max-width:1050px){.stats{grid-template-columns:repeat(3,1fr)}.info-grid{grid-template-columns:repeat(3,1fr)}}@media(max-width:780px){.lifecycle-score{grid-template-columns:1fr}.score-metrics{grid-template-columns:1fr 1fr}.chart-grid{grid-template-columns:1fr}.detail-controls{grid-template-columns:1fr}}@media(max-width:600px){.score-metrics{grid-template-columns:1fr}.stats,.info-grid{grid-template-columns:1fr 1fr}.hero{padding:26px 22px}.detail-title{font-size:25px}}
</style>'''

PLOTLY='<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>'

def nav(active):
    links=[]
    for k,c in BOARDS.items():
        # 默认首页就是销量月榜 (sales)
        target_href = "index.html" if k == "sales" else f"{k}.html"
        links.append(f'<a class="{"active" if k==active else ""}" href="{target_href}">{c["label"]}</a>')
    return f'<div class="topbar"><div class="nav"><div class="brand">猫耳数据中心<small>MAOER · AUDIO DRAMA</small></div><div class="navlinks">{"".join(links)}</div></div></div>'

def detail_name(board,did):
    return f'{BOARDS[board]["detail"]}_{re.sub(r"[^0-9A-Za-z_-]","_",str(did))}.html'

def detail_page(board,did,df):
    g=df[df["剧集ID"].astype(str)==str(did)].sort_values("日期").copy()
    if g.empty:return
    m=metrics(g); cfg=BOARDS[board]
    name=str(g.iloc[-1]["剧名"]); first=str(g["日期"].min()); last=str(g["日期"].max())
    lifecycle_score=calculate_rank_score(g) if board=="sales" else None
    score=lifecycle_score or {}
    cards=[]
    if board=="sales" and lifecycle_score:
        cards.append('<div class="lifecycle-score"><div class="score-main"><div class="score-label">月榜表现指数</div><div class="score-number">%s</div><div class="score-sub">完整生命周期 · %s → %s</div></div><div class="score-metrics"><div class="score-metric"><div class="label">上榜天数</div><div class="value">%s / %s</div></div><div class="score-metric"><div class="label">上榜率</div><div class="value">%.1f%%</div></div><div class="score-metric"><div class="label">平均排名</div><div class="value">%s</div></div><div class="score-metric"><div class="label">最高排名</div><div class="value gold">#%s</div></div><div class="score-metric"><div class="label">Top 3 天数</div><div class="value">%s</div></div><div class="score-metric"><div class="label">Top 10 天数</div><div class="value">%s</div></div><div class="score-metric"><div class="label">Top 20 天数</div><div class="value">%s</div></div><div class="score-metric"><div class="label">累计排名积分</div><div class="value">%s</div></div><div class="score-metric"><div class="label">平均每日积分</div><div class="value">%.1f</div></div></div></div>'%(score.get("score","--"),first,last,score.get("days",0),score.get("total_days",0),score.get("days_rate",0)*100,score.get("avg_rank","--"),score.get("best_rank","--"),score.get("top3_days",0),score.get("top10_days",0),score.get("top20_days",0),score.get("rank_points",0),score.get("avg_daily_points",0)))
    specs=[("剧集ID","剧集ID"),("当前排名","排名"),("播放量",m["play"]),("订阅数",m["subscribe"]),("总集数",m["total_episodes"]),("付费集数",m["paid_episodes"]),("全部弹幕UID",m["total_id"]),("付费弹幕UID",m["paid_id"]),("在榜天数",None)]
    if board=="sales" and m["paid_id"] and m["total_id"]:
        latest_row=g.iloc[-1]
        total_id=jval(latest_row.get(m["total_id"]))
        paid_id=jval(latest_row.get(m["paid_id"]))
        subscribe=jval(latest_row.get(m["subscribe"])) if m["subscribe"] else None
        def ratio_text(a,b):
            try:
                a=float(a); b=float(b)
                return f"{a/b*100:.2f}%" if b>0 else "--"
            except Exception:
                return "--"
        ratio_cards=[
            ("付费ID / 总ID",ratio_text(paid_id,total_id)),
            ("付费ID / 追剧",ratio_text(paid_id,subscribe)),
        ]
    else:
        ratio_cards=[]
    for label,col in specs:
        v=g["日期"].nunique() if label=="在榜天数" else (g.iloc[-1].get(col,"--") if col else "--")
        v=jval(v)
        cards.append('<div class="info-card"><div class="info-label">%s</div><div class="info-value">%s</div></div>'%(html.escape(label),html.escape(str(v if v is not None else "--"))))
    for label,v in ratio_cards:
        cards.append('<div class="info-card"><div class="info-label">%s</div><div class="info-value">%s</div></div>'%(html.escape(label),html.escape(str(v))))
    specs_chart=[("排名","排名","rank"),("播放量",m["play"],"play"),("订阅数",m["subscribe"],"subscribe")]
    if board=="sales":specs_chart += [("全部弹幕 UID",m["total_id"],"total_id"),("付费弹幕 UID",m["paid_id"],"paid_id")]
    charts=''.join('<div class="chart-card"><div class="chart-title">%s</div><div class="chart-sub">累计值 + 增量，可切换 7 日 / 单日</div><div id="chart_%s" class="chart"></div></div>'%(html.escape(t),key) for t,col,key in specs_chart if col or key=="rank")
    cols=["日期","排名"]
    for c in [m["play"],m["subscribe"],m["total_episodes"],m["paid_episodes"],m["total_id"],m["paid_id"]]:
        if c and c not in cols:cols.append(c)
    rows=''.join('<tr>'+''.join('<td>%s</td>'%html.escape(str(jval(r.get(c)) if jval(r.get(c)) is not None else "--")) for c in cols)+'</tr>' for _,r in g.iterrows())
    data=json.dumps(records(g),ensure_ascii=False,separators=(",",":"));mapping=json.dumps({"rank":"排名","play":m["play"],"subscribe":m["subscribe"],"total_id":m["total_id"],"paid_id":m["paid_id"]},ensure_ascii=False);cols_json=json.dumps(cols,ensure_ascii=False)
    period_score_markup = ""
    if board == "sales":
        period_score_markup = """<div class="panel"><div class="section-head"><h2>选定时间段的月榜表现</h2><span id="periodRange" class="muted">随上方日期范围更新</span></div><div class="period-score-grid"><div class="period-score-card"><div class="label">时间段表现指数</div><div id="periodScore" class="value gold">—</div></div><div class="period-score-card"><div class="label">上榜天数 / 区间天数</div><div id="periodDays" class="value">—</div></div><div class="period-score-card"><div class="label">平均排名</div><div id="periodAvgRank" class="value">—</div></div><div class="period-score-card"><div class="label">最高排名</div><div id="periodBestRank" class="value">—</div></div><div class="period-score-card"><div class="label">最低排名</div><div id="periodWorstRank" class="value">—</div></div><div class="period-score-card"><div class="label">Top 3 天数</div><div id="periodTop3" class="value">—</div></div><div class="period-score-card"><div class="label">Top 10 天数</div><div id="periodTop10" class="value">—</div></div><div class="period-score-card"><div class="label">Top 20 天数</div><div id="periodTop20" class="value">—</div></div><div class="period-score-card"><div class="label">累计排名积分</div><div id="periodPoints" class="value">—</div></div><div class="period-score-card"><div class="label">平均每日积分</div><div id="periodAvgPoints" class="value">—</div></div></div></div>"""
    
    back_target = "index.html" if board == "sales" else f"{board}.html"

    template="""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__</title>__PLOTLY____CSS__<style>.detail-page{background:#f4f6f8;color:#20252b}.detail-page .container{padding-top:18px}.detail-page .hero{background:linear-gradient(135deg,#121417,#24272c);border-color:#3a3d42;box-shadow:0 10px 30px rgba(0,0,0,.12)}.detail-page .detail-title{color:#C5A059;font-weight:800;}.detail-page .panel,.detail-page .chart-card,.detail-page .info-card{background:#fff;border:1px solid #dfe3e8;box-shadow:0 4px 16px rgba(31,41,55,.05)}.detail-page .panel{color:#20252b}.detail-page .section-head h2,.detail-page .chart-title{color:#20252b}.detail-page .muted,.detail-page .chart-sub,.detail-page .info-label{color:#7b8490}.detail-page .info-value{color:#20252b}.detail-page input,.detail-page select{background:#fff;color:#20252b;border-color:#cfd5dc}.detail-page input:focus,.detail-page select:focus{border-color:#7aa7d9}.detail-page .segment{border-color:#cfd5dc}.detail-page .segment button{background:#f5f7f9;color:#68727d}.detail-page .segment button.active{background:#e7eef7;color:#315f91}.detail-page .table-wrap{border-color:#dfe3e8}.detail-page th{background:#f0f3f6;color:#5d6670;border-color:#dfe3e8}.detail-page td{color:#30363d;border-color:#edf0f3}.detail-page tbody tr:hover td{background:#f7f9fb}.detail-page .back{color:#496f9e}.detail-page .footer{color:#8a929c}</style></head><body class="detail-page">__NAV__<div class="container"><a class="back" href="__BACK_TARGET__">← 返回__LABEL__</a><section class="hero"><div class="eyebrow">__LABEL__ · DRAMA DETAIL</div><div class="detail-title">__NAME__</div><div class="detail-id">ID · __ID__</div><p>历史数据：__FIRST__ → __LAST__ · 综合评分按整个生命周期计算</p></section><div class="panel"><div class="section-head"><h2>时间与增量</h2><span class="muted">短缺口只在图表中插值</span></div><div class="detail-controls"><div class="filter"><label>开始日期</label><input id="start" type="date" min="__FIRST__" max="__LAST__" value="__FIRST__"></div><div class="filter"><label>结束日期</label><input id="end" type="date" min="__FIRST__" max="__LAST__" value="__LAST__"></div><div><label style="display:block;color:var(--muted);font-size:11px;font-weight:750;margin-bottom:6px">增量方式</label><div class="segment"><button id="b7" class="active" onclick="setMode(7)">7日增量</button><button id="b1" onclick="setMode(1)">单日增量</button></div></div></div></div>__PERIOD_SCORE__<div class="panel"><div class="info-grid">__CARDS__</div></div><div class="chart-grid">__CHARTS__</div><div class="panel"><div class="section-head"><h2>每日详细数据</h2><span id="range" class="muted">__FIRST__ → __LAST__</span></div><div class="table-wrap"><table><thead><tr>__HEADERS__</tr></thead><tbody id="table">__ROWS__</tbody></table></div></div><div class="footer">猫耳数据中心 · __LABEL__</div></div><script>
const DATA=__DATA__;const MAP=__MAP__;const COLS=__COLS__;let MODE=7;
function num(v){const n=Number(v);return Number.isFinite(n)?n:null}
function setMode(x){MODE=x;b7.classList.toggle('active',x===7);b1.classList.toggle('active',x===1);render()}
function series(rows,key,gap){if(!key)return[];const mp=new Map();rows.forEach(r=>mp.set(r.日期,num(r[key])));const ds=[...mp.keys()].sort();if(!ds.length)return[];let a=[],d=new Date(ds[0]+'T00:00:00'),e=new Date(ds[ds.length-1]+'T00:00:00');for(;d<=e;d.setDate(d.getDate()+1)){const x=d.toISOString().slice(0,10);a.push({date:x,v:mp.has(x)?mp.get(x):null,est:false})}for(let i=0;i<a.length;i++)if(a[i].v===null){let l=i-1,r=i+1;while(l>=0&&a[l].v===null)l--;while(r<a.length&&a[r].v===null)r++;if(l>=0&&r<a.length&&r-l-1<=gap){a[i].v=a[l].v+(a[r].v-a[l].v)*(i-l)/(r-l);a[i].est=true}}return a}
function metric(id,title,rows,key){if(!key)return;const a=series(rows,key,3),x=a.map(z=>z.date),y=a.map(z=>z.v),delta=y.map((v,i)=>i>=MODE&&v!=null&&y[i-MODE]!=null?v-y[i-MODE]:null),real=a.filter(z=>z.v!=null&&!z.est),est=a.filter(z=>z.v!=null&&z.est),dn=MODE===7?'7日增量':'单日增量';Plotly.react(id,[{x,y:delta,type:'bar',name:dn,yaxis:'y2',opacity:.42},{x,y,type:'scatter',mode:'lines',name:'累计值',line:{width:2.8}},{x:real.map(z=>z.date),y:real.map(z=>z.v),type:'scatter',mode:'markers',name:'原始',marker:{size:5}},{x:est.map(z=>z.date),y:est.map(z=>z.v),type:'scatter',mode:'markers',name:'插值',marker:{size:7,symbol:'diamond'}}],{margin:{l:55,r:60,t:12,b:45},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',hovermode:'x unified',legend:{orientation:'h'},xaxis:{type:'date'},yaxis:{title:title,gridcolor:'rgba(216,180,106,.1)'},yaxis2:{title:dn,overlaying:'y',side:'right'}},{responsive:true,displaylogo:false})}
function rank(rows){const a=series(rows,MAP.rank,1),x=a.map(z=>z.date),y=a.map(z=>z.v),r=a.filter(z=>z.v!=null&&!z.est),e=a.filter(z=>z.v!=null&&z.est);Plotly.react('chart_rank',[{x,y,type:'scatter',mode:'lines',name:'排名',line:{width:2.8}},{x:r.map(z=>z.date),y:r.map(z=>z.v),type:'scatter',mode:'markers',name:'原始'},{x:e.map(z=>z.date),y:e.map(z=>z.v),type:'scatter',mode:'markers',name:'插值',marker:{symbol:'diamond'}}],{margin:{l:55,r:25,t:12,b:45},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',hovermode:'x unified',legend:{orientation:'h'},xaxis:{type:'date'},yaxis:{title:'排名',autorange:'reversed',dtick:5,gridcolor:'rgba(216,180,106,.1)'}},{responsive:true,displaylogo:false})}
function updatePeriodScore(rows,s,e){if(!document.getElementById('periodScore'))return;const total=(new Date(e+'T00:00:00')-new Date(s+'T00:00:00'))/86400000+1;const vals=rows.map(r=>Number(r[MAP.rank])).filter(v=>Number.isFinite(v)&&v>=1&&v<=50);const unique=new Map();rows.forEach(r=>{const v=Number(r[MAP.rank]);if(r.日期&&Number.isFinite(v)&&v>=1&&v<=50&&(!unique.has(r.日期)||v<unique.get(r.日期)))unique.set(r.日期,v)});const ranks=[...unique.values()];const days=ranks.length;const points=ranks.reduce((a,v)=>a+(51-v),0);const avg=ranks.length?ranks.reduce((a,v)=>a+v,0)/ranks.length:null;const best=ranks.length?Math.min(...ranks):null;const worst=ranks.length?Math.max(...ranks):null;const t3=ranks.filter(v=>v<=3).length,t10=ranks.filter(v=>v<=10).length,t20=ranks.filter(v=>v<=20).length;const quality=days?ranks.reduce((a,v)=>a+(51-v)/50,0)/days:0;const score=days&&total>0?100*(.30*(days/total)+.50*quality+.08*(t3/total)+.08*(t10/total)+.04*(t20/total)):null;periodRange.textContent=s+' → '+e;periodScore.textContent=score==null?'—':score.toFixed(2);periodDays.textContent=days+' / '+total;periodAvgRank.textContent=avg==null?'—':avg.toFixed(2);periodBestRank.textContent=best==null?'—':'#'+best;periodWorstRank.textContent=worst==null?'—':'#'+worst;periodTop3.textContent=t3;periodTop10.textContent=t10;periodTop20.textContent=t20;periodPoints.textContent=points.toLocaleString();periodAvgPoints.textContent=days?(points/days).toFixed(1):'—'}function render(){const s=start.value,e=end.value;if(s>e){alert('开始日期不能晚于结束日期');return}const rows=DATA.filter(r=>r.日期>=s&&r.日期<=e);updatePeriodScore(rows,s,e);range.textContent=s+' → '+e;table.innerHTML=rows.length?rows.map(r=>'<tr>'+COLS.map(c=>'<td>'+((r[c]??'')===''?'--':r[c])+'</td>').join('')+'</tr>').join(''):'<tr><td class="empty" colspan="20">该时间段没有数据</td></tr>';rank(rows);metric('chart_play','播放量',rows,MAP.play);metric('chart_subscribe','订阅数',rows,MAP.subscribe);metric('chart_total_id','全部弹幕 UID',rows,MAP.total_id);metric('chart_paid_id','付费弹幕 UID',rows,MAP.paid_id)}
start.onchange=render;end.onchange=render;document.addEventListener('DOMContentLoaded',render);
</script></body></html>"""
    repl={"__TITLE__":html.escape(name)+" · "+cfg["label"],"__PLOTLY__":PLOTLY,"__CSS__":CSS,"__NAV__":nav(board),"__BACK_TARGET__":back_target,"__LABEL__":cfg["label"],"__NAME__":html.escape(name),"__ID__":html.escape(str(did)),"__FIRST__":first,"__LAST__":last,"__CARDS__":''.join(cards),"__PERIOD_SCORE__":period_score_markup,"__CHARTS__":charts,"__HEADERS__":''.join('<th>'+html.escape(c)+'</th>' for c in cols),"__ROWS__":rows,"__DATA__":data,"__MAP__":mapping,"__COLS__":cols_json}
    for k,v in repl.items():template=template.replace(k,str(v))
    (OUTPUT_DIR/detail_name(board,did)).write_text(template,encoding='utf-8')

def board_page(board,df):
    cfg=BOARDS[board]; dates=sorted(df["日期"].unique()); latest=dates[-1]; default=max(pd.to_datetime(dates[0]),pd.to_datetime(latest)-pd.Timedelta(days=DEFAULT_DAYS-1)).strftime("%Y-%m-%d")
    for did in sorted(set(df["剧集ID"].dropna().astype(str))):
        detail_page(board,did,df)
    
    # 导出一个 json 供外部调用
    df.to_json(OUTPUT_DIR / cfg["json"], orient="records", date_format="iso", force_ascii=False)
    
    # 直接将数据转为 JSON 字符串内嵌到 JavaScript 变量中，避免异步 fetch 加载失败
    data_json = json.dumps(records(df), ensure_ascii=False, separators=(',', ':'))

    page=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{cfg["label"]} · 猫耳数据中心</title>{CSS}</head><body>{nav(board)}<div class="container"><section class="hero"><div class="eyebrow">MAOER DATA CENTER</div><h1>{cfg["label"]}</h1><p>以剧集 ID 为唯一识别 · 历史跨期分析 · 每剧独立详情页</p></section><div class="panel"><div class="filters"><div class="filter"><label>开始日期</label><input id="start" type="date" min="{dates[0]}" max="{latest}" value="{default}"></div><div class="filter"><label>结束日期</label><input id="end" type="date" min="{dates[0]}" max="{latest}" value="{latest}"></div><div class="filter"><label>榜单状态</label><select id="status"><option value="all">全部状态</option><option value="稳定在榜">稳定在榜</option><option value="新晋榜单">新晋榜单</option><option value="掉榜">掉榜</option><option value="闪现">闪现</option></select></div><div class="filter"><label>搜索剧名 / ID</label><input id="kw" type="text" placeholder="模糊搜索..."></div><div class="filter"><label>剧集显示设置</label><div class="theme-buttons"><button id="btnDay" class="theme-btn active" onclick="setTheme('day')">☀ 白天</button><button id="btnNight" class="theme-btn" onclick="setTheme('night')">☾ 黑夜</button></div><input type="hidden" id="idThreshold" value="50"></div></div></div><div class="stats"><div class="stat"><div class="label">统计区间上榜剧集</div><div id="statTotal" class="value gold">0</div></div><div class="stat"><div class="label">稳定在榜</div><div id="statStable" class="value">0</div></div><div class="stat"><div class="label">新晋榜单</div><div id="statNew" class="value">0</div></div><div class="stat"><div class="label">掉榜</div><div id="statDrop" class="value">0</div></div><div class="stat"><div class="label">闪现</div><div id="statFlash" class="value">0</div></div></div><div class="panel"><div class="section-head"><h2>剧集列表</h2><span id="count" class="muted">加载中...</span></div><div id="homeTableWrap" class="table-wrap theme-day"><table><thead><tr><th>剧集ID</th><th>剧名</th><th>首字母</th><th>在榜天数</th><th>最高排名</th><th>最低排名</th><th>当前排名</th><th>首次上榜</th><th>最后在榜</th><th>榜单状态</th><th>趋势</th><th>详情</th></tr></thead><tbody id="table"></tbody></table></div></div><div class="footer">猫耳数据中心 · {cfg["label"]}</div></div><script>
const RAW = {data_json};
const BOARD = '{board}', DETAIL_PREFIX = '{cfg["detail"]}';

function badge(status){{const m={{'稳定在榜':'green','新晋榜单':'gold','掉榜':'red','闪现':'gray'}};return `<span class="badge ${{m[status]||'gray'}}">${{status}}</span>`}}
function trendBadge(t){{const m={{'上升':'green','下降':'red','波动':'blue'}};return `<span class="badge ${{m[t]||'gray'}}">${{t}}</span>`}}
function setTheme(mode){{
  const wrap=document.getElementById('homeTableWrap');
  if(mode==='day'){{
    wrap.classList.remove('theme-night'); wrap.classList.add('theme-day');
    btnDay.classList.add('active'); btnNight.classList.remove('active');
  }}else{{
    wrap.classList.remove('theme-day'); wrap.classList.add('theme-night');
    btnNight.classList.add('active'); btnDay.classList.remove('active');
  }}
}}
function render(){{
  const s=start.value, e=end.value, st=status.value, kw=kw.value.trim().toLowerCase();
  if(s>e){{alert('开始日期不能晚于结束日期');return}}
  const sub=RAW.filter(r=>r.日期>=s&&r.日期<=e);
  const map=new Map();
  sub.forEach(r=>{{
    const key=r.剧集ID||r.剧名;
    if(!map.has(key)) map.set(key, []);
    map.get(key).push(r);
  }});
  const list=[];
  map.forEach((rows, key)=>{{
    rows.sort((a,b)=>a.日期.localeCompare(b.日期));
    const ranks=rows.map(r=>Number(r.排名)).filter(v=>!isNaN(v));
    if(!ranks.length)return;
    const last=rows[rows.length-1];
    const ds=[...new Set(rows.map(r=>r.日期))];
    const statusVal=(ds[0]===s && ds[ds.length-1]===e)?'稳定在榜':(ds[0]!==s && ds[ds.length-1]===e)?'新晋榜单':(ds[0]===s && ds[ds.length-1]!==e)?'掉榜':'闪现';
    list.push({{
      did: last.剧集ID||'',
      name: last.剧名,
      initial: last.首字母||'#',
      days: ds.length,
      best: Math.min(...ranks),
      worst: Math.max(...ranks),
      cur: ranks[ranks.length-1],
      first: rows[0].日期,
      last: last.日期,
      status: statusVal,
      trend: ranks.length<2||ranks[0]===ranks[ranks.length-1]?'波动':(ranks[ranks.length-1]<ranks[0]?'上升':'下降')
    }});
  }});
  let filtered=list.filter(r=>{{
    if(st!=='all' && r.status!==st) return false;
    if(kw && !r.name.toLowerCase().includes(kw) && !r.did.toLowerCase().includes(kw)) return false;
    return true;
  }});
  filtered.sort((a,b)=>a.cur-b.cur);
  statTotal.textContent=filtered.length;
  statStable.textContent=filtered.filter(r=>r.status==='稳定在榜').length;
  statNew.textContent=filtered.filter(r=>r.status==='新晋榜单').length;
  statDrop.textContent=filtered.filter(r=>r.status==='掉榜').length;
  statFlash.textContent=filtered.filter(r=>r.status==='闪现').length;
  count.textContent=`共 ${{filtered.length}} 剧目`;
  table.innerHTML=filtered.length?filtered.map(r=>`<tr>
    <td class="id-text">${{r.did||'--'}}</td>
    <td><a class="drama-link" href="${{DETAIL_PREFIX}}_${{(r.did||'').replace(/[^0-9A-Za-z_-]/g,'_')}}.html">${{r.name}}</a></td>
    <td>${{r.initial}}</td>
    <td>${{r.days}}</td>
    <td>#${{r.best}}</td>
    <td>#${{r.worst}}</td>
    <td><strong>#${{r.cur}}</strong></td>
    <td>${{r.first}}</td>
    <td>${{r.last}}</td>
    <td>${{badge(r.status)}}</td>
    <td>${{trendBadge(r.trend)}}</td>
    <td><a class="drama-link" href="${{DETAIL_PREFIX}}_${{(r.did||'').replace(/[^0-9A-Za-z_-]/g,'_')}}.html">查看详情</a></td>
  </tr>`).join(''):'<tr><td class="empty" colspan="12">暂无符合条件的剧目数据</td></tr>';
}}

document.addEventListener('DOMContentLoaded', render);
start.onchange=render; end.onchange=render; status.onchange=render; kw.oninput=render;
</script></body></html>'''

    output_filename = f"{board}.html"
    (OUTPUT_DIR / output_filename).write_text(page, encoding='utf-8')
    
    # 如果是销量月榜，直接将其作为默认首页 index.html 输出
    if board == "sales":
        (OUTPUT_DIR / "index.html").write_text(page, encoding='utf-8')

def main():
    print("🚀 开始数据构建...")
    for b in BOARDS:
        df = load_board(b)
        if df is not None and not df.empty:
            board_page(b, df)
    print("✨ 所有页面构建完成！销量月榜已默认设置为 index.html。")

if __name__ == "__main__":
    main()
