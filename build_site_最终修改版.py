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

def trend(rows):
    x=[float(v) for v in rows if pd.notna(v)]
    if len(x)<2 or x[0]==x[-1]:return "波动"
    d=[x[i]-x[i-1] for i in range(1,len(x))]
    if all(v<=0 for v in d) and any(v<0 for v in d):return "上升"
    if all(v>=0 for v in d) and any(v>0 for v in d):return "下降"
    if abs(x[-1]-x[0])<=2:return "波动"
    return "上升" if x[-1]<x[0] else "下降"

def status(group,start,end):
    ds=sorted(group["日期"].unique())
    if not ds:return "闪现"
    a=ds[0]==start;b=ds[-1]==end
    if a and b:return "稳定在榜"
    if not a and b:return "新晋榜单"
    if a and not b:return "掉榜"
    return "闪现"

def summary(df,start,end):
    out=[]
    groups=df.groupby("剧集ID",dropna=False) if df["剧集ID"].notna().any() else df.groupby("剧名")
    for key,g in groups:
        g=g.sort_values("日期"); ranks=pd.to_numeric(g["排名"],errors="coerce").dropna()
        if ranks.empty:continue
        did="" if pd.isna(key) else str(key)
        out.append({"剧集ID":did,"剧名":str(g.iloc[-1]["剧名"]),"首字母":initial(g.iloc[-1]["剧名"]),"在榜天数":int(g["日期"].nunique()),"最高排名":int(ranks.min()),"最低排名":int(ranks.max()),"当前排名":int(ranks.iloc[-1]),"首次上榜":str(g.iloc[0]["日期"]),"最后在榜":str(g.iloc[-1]["日期"]),"榜单状态":status(g,start,end),"趋势状态":trend(ranks.tolist())})
    return out


def calculate_rank_score(df, start_date=None, end_date=None, rank_limit=50):
    """计算销量月榜表现指数；详情页不传日期时使用完整生命周期。"""
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
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 10% -10%,rgba(216,180,106,.1),transparent 30%),var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}.container{width:min(1500px,94%);margin:auto;padding:24px 0 60px}.topbar{position:sticky;top:0;z-index:30;background:rgba(13,15,18,.93);backdrop-filter:blur(12px);border-bottom:1px solid rgba(216,180,106,.15)}.nav{width:min(1500px,94%);min-height:64px;margin:auto;display:flex;align-items:center;gap:22px}.brand{font-weight:850;white-space:nowrap}.brand small{display:block;color:var(--muted);font-size:9px;letter-spacing:2px}.navlinks{display:flex;gap:3px;overflow:auto}.navlinks a{color:#aaa69e;text-decoration:none;padding:9px 14px;border-radius:9px;font-size:13px;font-weight:750;white-space:nowrap}.navlinks a:hover,.navlinks a.active{color:var(--gold2);background:rgba(216,180,106,.1)}.hero{padding:34px 36px;border:1px solid rgba(216,180,106,.2);border-radius:20px;background:linear-gradient(135deg,rgba(255,255,255,.04),rgba(255,255,255,.012)),#111419;box-shadow:0 18px 50px rgba(0,0,0,.2);margin:22px 0}.eyebrow{font-size:10px;font-weight:850;letter-spacing:2.5px;color:var(--gold)}h1{margin:8px 0;font-size:clamp(28px,4vw,42px)}.hero p{margin:0;color:var(--muted);font-size:13px}.panel{background:linear-gradient(145deg,rgba(255,255,255,.035),rgba(255,255,255,.012));border:1px solid var(--line);border-radius:15px;padding:19px;margin-bottom:17px}.filters{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}.filter label{display:block;color:var(--muted);font-size:11px;font-weight:750;margin-bottom:6px}input,select{width:100%;height:41px;border:1px solid #353a42;border-radius:9px;background:#101318;color:var(--text);padding:0 10px;outline:none}input:focus,select:focus{border-color:var(--gold)}button{border:1px solid rgba(216,180,106,.35);background:linear-gradient(135deg,#a67b35,#d8b46a);color:#17130b;height:40px;border-radius:9px;padding:0 14px;font-weight:850;cursor:pointer}.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:11px;margin-bottom:17px}.stat{background:#15181d;border:1px solid var(--line);border-radius:13px;padding:16px}.stat .label{font-size:10px;color:var(--muted)}.stat .value{font-size:25px;font-weight:850;margin-top:5px}.gold{color:var(--gold2)}.section-head{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:12px}.section-head h2{margin:0;font-size:17px}.muted{font-size:11px;color:var(--muted)}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:11px}table{width:100%;border-collapse:collapse}th{background:#111419;color:#aaa69f;font-size:10px;padding:11px;text-align:left;white-space:nowrap;border-bottom:1px solid var(--line)}td{font-size:12px;padding:11px;border-bottom:1px solid rgba(43,48,55,.7);white-space:nowrap}tbody tr:hover td{background:rgba(216,180,106,.035)}.drama-link{border:0;background:none;color:var(--text);padding:0;height:auto;font-weight:750}.drama-link:hover{color:var(--gold2)}.id-text{color:#98948d;font:11px ui-monospace,SFMono-Regular,Menlo,monospace}.badge{display:inline-flex;padding:4px 8px;border-radius:99px;font-size:10px;font-weight:800}.badge.gold{color:var(--gold2);background:rgba(216,180,106,.1)}.badge.green{color:var(--green);background:rgba(107,194,140,.09)}.badge.red{color:var(--red);background:rgba(228,125,118,.09)}.badge.blue{color:var(--blue);background:rgba(120,166,216,.09)}.badge.gray{color:#aaa69f;background:rgba(170,166,159,.08)}.detail-title{font-size:30px;font-weight:900}.score-value{color:var(--gold2);font-weight:900}.detail-id{margin-top:6px;color:var(--gold);font:12px ui-monospace,monospace}.lifecycle-score{display:grid;grid-template-columns:250px 1fr;gap:20px;align-items:stretch;margin-bottom:17px}.score-main{background:linear-gradient(145deg,#fffdf7,#fff);border:1px solid #e2d2a9;border-radius:14px;padding:20px 22px;display:flex;flex-direction:column;justify-content:center}.score-main .score-label{font-size:12px;color:#7b8490;font-weight:800}.score-main .score-number{font-size:42px;line-height:1.05;font-weight:900;color:#a67b35;margin-top:8px}.score-main .score-sub{font-size:11px;color:#7b8490;margin-top:7px}.score-metrics{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}.score-metric{background:#fff;border:1px solid #dfe3e8;border-radius:11px;padding:12px 14px}.score-metric .label{font-size:10px;color:#7b8490}.score-metric .value{font-size:16px;font-weight:850;color:#20252b;margin-top:5px}.score-metric .value.gold{color:#a67b35}.info-grid>.lifecycle-score{grid-column:1/-1}.period-score-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}.period-score-card{background:#fff;border:1px solid #dfe3e8;border-radius:11px;padding:13px}.period-score-card .label{font-size:10px;color:#7b8490}.period-score-card .value{font-size:18px;font-weight:850;color:#20252b;margin-top:5px}.period-score-card .value.gold{color:#a67b35}@media(max-width:780px){.period-score-grid{grid-template-columns:repeat(2,1fr)}}
.detail-controls{display:grid;grid-template-columns:180px 180px 230px;gap:11px;align-items:end}.segment{display:flex;border:1px solid var(--line);border-radius:9px;overflow:hidden}.segment button{flex:1;border:0;border-radius:0;background:#101318;color:#aaa69f}.segment button.active{background:rgba(216,180,106,.16);color:var(--gold2)}.info-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:9px}.info-card{background:#14171b;border:1px solid var(--line);border-radius:11px;padding:13px}.info-label{font-size:10px;color:var(--muted)}.info-value{font-size:15px;font-weight:850;margin-top:5px;word-break:break-all}.chart-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.chart-card{background:#14171b;border:1px solid var(--line);border-radius:13px;padding:14px}.chart-title{font-size:15px;font-weight:850}.chart-sub{font-size:10px;color:var(--muted);margin-top:4px}.chart{height:370px}.back{display:inline-block;color:var(--gold2);text-decoration:none;font-size:12px;font-weight:800;margin-bottom:12px}.empty{text-align:center;color:var(--muted);padding:35px}.footer{text-align:center;color:#6d6962;font-size:10px;padding:24px}.board-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:15px}.board-card{display:block;text-decoration:none;background:#15181d;border:1px solid var(--line);border-radius:16px;padding:24px}.board-card:hover{border-color:rgba(216,180,106,.4);transform:translateY(-2px)}.board-card h2{margin:8px 0}.board-card p{color:var(--muted);font-size:12px}.board-card span{color:var(--gold2);font-weight:800;font-size:12px}.home-table.theme-day tbody tr td{background:#ffffff;color:#20252b;border-bottom-color:#e5e7eb}.home-table.theme-day tbody tr:hover td{background:#f3f4f6}.home-table.theme-night tbody tr td{background:#171a1f;color:#f3efe5}.home-table.theme-night tbody tr:hover td{background:#20242a}.home-table.theme-day .drama-link{color:#20252b}.home-table.theme-night .drama-link{color:#f3efe5}.home-table .threshold-row td{background:#fff1cf!important}.home-table.theme-night .threshold-row td{background:#3a3020!important}.home-table.theme-day th{background:#f0f2f4;color:#59616b}.home-table.theme-night th{background:#111419;color:#aaa69f}@media(max-width:1050px){.filters{grid-template-columns:repeat(3,1fr)}.stats{grid-template-columns:repeat(3,1fr)}.info-grid{grid-template-columns:repeat(3,1fr)}}@media(max-width:780px){.lifecycle-score{grid-template-columns:1fr}.score-metrics{grid-template-columns:1fr 1fr}.chart-grid{grid-template-columns:1fr}.detail-controls{grid-template-columns:1fr}.board-grid{grid-template-columns:1fr}}@media(max-width:600px){.score-metrics{grid-template-columns:1fr}.filters,.stats,.info-grid{grid-template-columns:1fr 1fr}.hero{padding:26px 22px}.detail-title{font-size:25px}}
</style>'''
PLOTLY='<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>'

def nav(active):
    links=[]
    for k,c in BOARDS.items():links.append(f'<a class="{"active" if k==active else ""}" href="{k}.html">{c["label"]}</a>')
    return f'<div class="topbar"><div class="nav"><div class="brand">猫耳数据中心<small>MAOER · AUDIO DRAMA</small></div><div class="navlinks">{"".join(links)}</div></div></div>'

def detail_name(board,did):return f'{BOARDS[board]["detail"]}_{re.sub(r"[^0-9A-Za-z_-]","_",str(did))}.html'

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
    # 付费 ID 比值使用该剧当前（最新日期）数据，保留两位小数并显示为百分比。
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
    template="""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__</title>__PLOTLY____CSS__<style>/* 单剧页：版头保留黑金，其余区域使用浅色分析界面 */.detail-page{background:#f4f6f8;color:#20252b}.detail-page .container{padding-top:18px}.detail-page .hero{background:linear-gradient(135deg,#121417,#24272c);border-color:#3a3d42;box-shadow:0 10px 30px rgba(0,0,0,.12)}.detail-page .detail-title{
    color:#C5A059;
    font-weight:800;
}.detail-page .panel,.detail-page .chart-card,.detail-page .info-card{background:#fff;border:1px solid #dfe3e8;box-shadow:0 4px 16px rgba(31,41,55,.05)}.detail-page .panel{color:#20252b}.detail-page .section-head h2,.detail-page .chart-title{color:#20252b}.detail-page .muted,.detail-page .chart-sub,.detail-page .info-label{color:#7b8490}.detail-page .info-value{color:#20252b}.detail-page input,.detail-page select{background:#fff;color:#20252b;border-color:#cfd5dc}.detail-page input:focus,.detail-page select:focus{border-color:#7aa7d9}.detail-page .segment{border-color:#cfd5dc}.detail-page .segment button{background:#f5f7f9;color:#68727d}.detail-page .segment button.active{background:#e7eef7;color:#315f91}.detail-page .table-wrap{border-color:#dfe3e8}.detail-page th{background:#f0f3f6;color:#5d6670;border-color:#dfe3e8}.detail-page td{color:#30363d;border-color:#edf0f3}.detail-page tbody tr:hover td{background:#f7f9fb}.detail-page .back{color:#496f9e}.detail-page .footer{color:#8a929c}</style></head><body class="detail-page">__NAV__<div class="container"><a class="back" href="__BOARD__.html">← 返回__LABEL__</a><section class="hero"><div class="eyebrow">__LABEL__ · DRAMA DETAIL</div><div class="detail-title">__NAME__</div><div class="detail-id">ID · __ID__</div><p>历史数据：__FIRST__ → __LAST__ · 综合评分按整个生命周期计算</p></section><div class="panel"><div class="section-head"><h2>时间与增量</h2><span class="muted">短缺口只在图表中插值</span></div><div class="detail-controls"><div class="filter"><label>开始日期</label><input id="start" type="date" min="__FIRST__" max="__LAST__" value="__FIRST__"></div><div class="filter"><label>结束日期</label><input id="end" type="date" min="__FIRST__" max="__LAST__" value="__LAST__"></div><div><label style="display:block;color:var(--muted);font-size:11px;font-weight:750;margin-bottom:6px">增量方式</label><div class="segment"><button id="b7" class="active" onclick="setMode(7)">7日增量</button><button id="b1" onclick="setMode(1)">单日增量</button></div></div></div></div>__PERIOD_SCORE__<div class="panel"><div class="info-grid">__CARDS__</div></div><div class="chart-grid">__CHARTS__</div><div class="panel"><div class="section-head"><h2>每日详细数据</h2><span id="range" class="muted">__FIRST__ → __LAST__</span></div><div class="table-wrap"><table><thead><tr>__HEADERS__</tr></thead><tbody id="table">__ROWS__</tbody></table></div></div><div class="footer">猫耳数据中心 · __LABEL__</div></div><script>
const DATA=__DATA__;const MAP=__MAP__;const COLS=__COLS__;let MODE=7;
function num(v){const n=Number(v);return Number.isFinite(n)?n:null}
function setMode(x){MODE=x;b7.classList.toggle('active',x===7);b1.classList.toggle('active',x===1);render()}
function series(rows,key,gap){if(!key)return[];const mp=new Map();rows.forEach(r=>mp.set(r.日期,num(r[key])));const ds=[...mp.keys()].sort();if(!ds.length)return[];let a=[],d=new Date(ds[0]+'T00:00:00'),e=new Date(ds[ds.length-1]+'T00:00:00');for(;d<=e;d.setDate(d.getDate()+1)){const x=d.toISOString().slice(0,10);a.push({date:x,v:mp.has(x)?mp.get(x):null,est:false})}for(let i=0;i<a.length;i++)if(a[i].v===null){let l=i-1,r=i+1;while(l>=0&&a[l].v===null)l--;while(r<a.length&&a[r].v===null)r++;if(l>=0&&r<a.length&&r-l-1<=gap){a[i].v=a[l].v+(a[r].v-a[l].v)*(i-l)/(r-l);a[i].est=true}}return a}
function metric(id,title,rows,key){if(!key)return;const a=series(rows,key,3),x=a.map(z=>z.date),y=a.map(z=>z.v),delta=y.map((v,i)=>i>=MODE&&v!=null&&y[i-MODE]!=null?v-y[i-MODE]:null),real=a.filter(z=>z.v!=null&&!z.est),est=a.filter(z=>z.v!=null&&z.est),dn=MODE===7?'7日增量':'单日增量';Plotly.react(id,[{x,y:delta,type:'bar',name:dn,yaxis:'y2',opacity:.42},{x,y,type:'scatter',mode:'lines',name:'累计值',line:{width:2.8}},{x:real.map(z=>z.date),y:real.map(z=>z.v),type:'scatter',mode:'markers',name:'原始',marker:{size:5}},{x:est.map(z=>z.date),y:est.map(z=>z.v),type:'scatter',mode:'markers',name:'插值',marker:{size:7,symbol:'diamond'}}],{margin:{l:55,r:60,t:12,b:45},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',hovermode:'x unified',legend:{orientation:'h'},xaxis:{type:'date'},yaxis:{title:title,gridcolor:'rgba(216,180,106,.1)'},yaxis2:{title:dn,overlaying:'y',side:'right'}},{responsive:true,displaylogo:false})}
function rank(rows){const a=series(rows,MAP.rank,1),x=a.map(z=>z.date),y=a.map(z=>z.v),r=a.filter(z=>z.v!=null&&!z.est),e=a.filter(z=>z.v!=null&&z.est);Plotly.react('chart_rank',[{x,y,type:'scatter',mode:'lines',name:'排名',line:{width:2.8}},{x:r.map(z=>z.date),y:r.map(z=>z.v),type:'scatter',mode:'markers',name:'原始'},{x:e.map(z=>z.date),y:e.map(z=>z.v),type:'scatter',mode:'markers',name:'插值',marker:{symbol:'diamond'}}],{margin:{l:55,r:25,t:12,b:45},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',hovermode:'x unified',legend:{orientation:'h'},xaxis:{type:'date'},yaxis:{title:'排名',autorange:'reversed',dtick:5,gridcolor:'rgba(216,180,106,.1)'}},{responsive:true,displaylogo:false})}
function updatePeriodScore(rows,s,e){if(!document.getElementById('periodScore'))return;const total=(new Date(e+'T00:00:00')-new Date(s+'T00:00:00'))/86400000+1;const vals=rows.map(r=>Number(r[MAP.rank])).filter(v=>Number.isFinite(v)&&v>=1&&v<=50);const unique=new Map();rows.forEach(r=>{const v=Number(r[MAP.rank]);if(r.日期&&Number.isFinite(v)&&v>=1&&v<=50&&(!unique.has(r.日期)||v<unique.get(r.日期)))unique.set(r.日期,v)});const ranks=[...unique.values()];const days=ranks.length;const points=ranks.reduce((a,v)=>a+(51-v),0);const avg=ranks.length?ranks.reduce((a,v)=>a+v,0)/ranks.length:null;const best=ranks.length?Math.min(...ranks):null;const worst=ranks.length?Math.max(...ranks):null;const t3=ranks.filter(v=>v<=3).length,t10=ranks.filter(v=>v<=10).length,t20=ranks.filter(v=>v<=20).length;const quality=days?ranks.reduce((a,v)=>a+(51-v)/50,0)/days:0;const score=days&&total>0?100*(.30*(days/total)+.50*quality+.08*(t3/total)+.08*(t10/total)+.04*(t20/total)):null;periodRange.textContent=s+' → '+e;periodScore.textContent=score==null?'—':score.toFixed(2);periodDays.textContent=days+' / '+total;periodAvgRank.textContent=avg==null?'—':avg.toFixed(2);periodBestRank.textContent=best==null?'—':'#'+best;periodWorstRank.textContent=worst==null?'—':'#'+worst;periodTop3.textContent=t3;periodTop10.textContent=t10;periodTop20.textContent=t20;periodPoints.textContent=points.toLocaleString();periodAvgPoints.textContent=days?(points/days).toFixed(1):'—'}function render(){const s=start.value,e=end.value;if(s>e){alert('开始日期不能晚于结束日期');return}const rows=DATA.filter(r=>r.日期>=s&&r.日期<=e);updatePeriodScore(rows,s,e);range.textContent=s+' → '+e;table.innerHTML=rows.length?rows.map(r=>'<tr>'+COLS.map(c=>'<td>'+((r[c]??'')===''?'--':r[c])+'</td>').join('')+'</tr>').join(''):'<tr><td class="empty" colspan="20">该时间段没有数据</td></tr>';rank(rows);metric('chart_play','播放量',rows,MAP.play);metric('chart_subscribe','订阅数',rows,MAP.subscribe);metric('chart_total_id','全部弹幕 UID',rows,MAP.total_id);metric('chart_paid_id','付费弹幕 UID',rows,MAP.paid_id)}
start.onchange=render;end.onchange=render;document.addEventListener('DOMContentLoaded',render);
</script></body></html>"""
    repl={"__TITLE__":html.escape(name)+" · "+cfg["label"],"__PLOTLY__":PLOTLY,"__CSS__":CSS,"__NAV__":nav(board),"__BOARD__":board,"__LABEL__":cfg["label"],"__NAME__":html.escape(name),"__ID__":html.escape(str(did)),"__FIRST__":first,"__LAST__":last,"__CARDS__":''.join(cards),"__PERIOD_SCORE__":period_score_markup,"__CHARTS__":charts,"__HEADERS__":''.join('<th>'+html.escape(c)+'</th>' for c in cols),"__ROWS__":rows,"__DATA__":data,"__MAP__":mapping,"__COLS__":cols_json}
    for k,v in repl.items():template=template.replace(k,str(v))
    (OUTPUT_DIR/detail_name(board,did)).write_text(template,encoding='utf-8')

def board_page(board,df):
    cfg=BOARDS[board]; dates=sorted(df["日期"].unique()); latest=dates[-1]; default=max(pd.to_datetime(dates[0]),pd.to_datetime(latest)-pd.Timedelta(days=DEFAULT_DAYS-1)).strftime("%Y-%m-%d")
    for did in sorted(set(df["剧集ID"].dropna().astype(str))):detail_page(board,did,df)
    datafile=cfg["json"]
    page=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{cfg["label"]} · 猫耳数据中心</title>{CSS}</head><body>{nav(board)}<div class="container"><section class="hero"><div class="eyebrow">MAOER DATA CENTER</div><h1>{cfg["label"]}</h1><p>以剧集 ID 为唯一识别 · 历史跨期分析 · 每剧独立详情页</p></section><div class="panel"><div class="filters"><div class="filter"><label>开始日期</label><input id="start" type="date" min="{dates[0]}" max="{latest}" value="{default}"></div><div class="filter"><label>结束日期</label><input id="end" type="date" min="{dates[0]}" max="{latest}" value="{latest}"></div><div class="filter"><label>排序规则 1</label><select id="sort1"></option><option value="best">最高排名 ↑<option value="days">在榜天数 ↓</option><option value="score">综合评分 ↓</option><option value="current" selected>当前排名 ↑</option><option value="initial">首字母 ↑</option><option value="name">剧名 ↑</option></select></div><div class="filter"><label>排序规则 2</label><select id="sort2"><option value="none" selected>不使用第二排序</option><option value="days">在榜天数 ↓</option><option value="score">综合评分 ↓</option><option value="best">最高排名 ↑</option><option value="current">当前排名 ↑</option><option value="initial">首字母 ↑</option><option value="name">剧名 ↑</option></select></div><div class="filter"><label>搜索剧名</label><input id="q" placeholder="输入剧名…"></div><div class="filter"><label>搜索 ID</label><input id="qi" placeholder="输入剧集 ID…"></div></div></div><div class="stats"><div class="stat"><div class="label">剧目数量</div><div id="n" class="value gold">—</div></div><div class="stat"><div class="label">稳定在榜</div><div id="stable" class="value">—</div></div><div class="stat"><div class="label">新晋</div><div id="newCount" class="value">—</div></div><div class="stat"><div class="label">掉榜 / 闪现</div><div id="drop" class="value">—</div></div><div class="stat"><div class="label">统计范围</div><div id="range" class="value" style="font-size:14px">—</div></div></div><div class="panel"><div class="section-head"><h2>剧目榜单</h2><span id="count" class="muted"></span></div><div class="table-wrap"><table><thead><tr><th>#</th><th>剧名</th><th>在榜天数</th><th>综合评分</th><th>最高排名</th><th>最低排名</th><th>当前排名</th><th>累计排名积分</th><th>首次</th><th>最后</th><th>状态</th><th>趋势</th></tr></thead><tbody id="table"></tbody></table></div></div><div class="footer">猫耳数据中心 · {cfg["label"]} · {dates[0]} → {dates[-1]}</div></div><script>
let APP=null;const DETAIL='{cfg["detail"]}';const BOARD_SCORE_ENABLED='{board}';function id(r){{return r['剧集ID']==null?'':String(r['剧集ID'])}}function status(g,s,e){{const d=[...new Set(g.map(r=>r.日期))].sort();if(!d.length)return'闪现';if(d[0]===s&&d.at(-1)===e)return'稳定在榜';if(d[0]!==s&&d.at(-1)===e)return'新晋榜单';if(d[0]===s&&d.at(-1)!==e)return'掉榜';return'闪现'}}function trend(g){{const a=g.map(r=>Number(r.排名)).filter(Number.isFinite);if(a.length<2||a[0]===a.at(-1))return'波动';if(a.every((v,i)=>i===0||v<=a[i-1]))return'上升';if(a.every((v,i)=>i===0||v>=a[i-1]))return'下降';return Math.abs(a.at(-1)-a[0])<=2?'波动':a.at(-1)<a[0]?'上升':'下降'}}function badge(x){{const c=x==='稳定在榜'?'gold':x==='新晋榜单'?'blue':(x==='掉榜'||x==='下降')?'red':x==='上升'?'green':'gray';return'<span class="badge '+c+'">'+x+'</span>'}}function calculateScore(g,s,e){{if(BOARD_SCORE_ENABLED!=='sales')return null;const mp=new Map();g.forEach(r=>{{const d=r.日期,n=Number(r.排名);if(!d||!Number.isFinite(n)||n<1||n>50)return;if(!mp.has(d)||n<mp.get(d))mp.set(d,n)}});const vals=[...mp.values()];if(!vals.length)return null;const total=(new Date(e+'T00:00:00')-new Date(s+'T00:00:00'))/86400000+1;if(total<=0)return null;const days=vals.length,daysRate=days/total,rankQuality=vals.reduce((a,r)=>a+(51-r)/50,0)/days,top3=vals.filter(r=>r<=3).length/total,top10=vals.filter(r=>r<=10).length/total,top20=vals.filter(r=>r<=20).length/total;return Number((100*(.30*daysRate+.50*rankQuality+.08*top3+.08*top10+.04*top20)).toFixed(2))}}function render(){{const s=start.value,e=end.value;if(s>e){{alert('开始日期不能晚于结束日期');return}}let rows=APP.records.filter(r=>r.日期>=s&&r.日期<=e),qq=q.value.trim().toLowerCase(),ii=qi.value.trim();if(qq)rows=rows.filter(r=>String(r.剧名).toLowerCase().includes(qq));if(ii)rows=rows.filter(r=>id(r).includes(ii));const m=new Map();rows.forEach(r=>{{const k=id(r)?'id:'+id(r):'name:'+r.剧名;if(!m.has(k))m.set(k,[]);m.get(k).push(r)}});let a=[];m.forEach(g=>{{g.sort((x,y)=>x.日期.localeCompare(y.日期));const rs=g.map(r=>Number(r.排名)).filter(Number.isFinite);if(rs.length)a.push({{id:id(g[0]),name:g.at(-1).剧名,initial:g[0].首字母||'#',days:new Set(g.map(r=>r.日期)).size,score:calculateScore(g,s,e),best:Math.min(...rs),worst:Math.max(...rs),rankPoints:BOARD_SCORE_ENABLED==='sales'?rs.reduce((sum,r)=>sum+(51-r),0):null,current:rs.at(-1),first:g[0].日期,last:g.at(-1).日期,status:status(g,s,e),trend:trend(g)}})}});const s1=sort1.value,s2=sort2.value;function compareBy(x,y,k){{if(k==='none')return 0;if(k==='days')return y.days-x.days;if(k==='score')return (y.score??-1)-(x.score??-1);if(k==='best')return x.best-y.best;if(k==='current')return x.current-y.current;if(k==='initial')return x.initial.localeCompare(y.initial,'zh-CN');if(k==='name')return x.name.localeCompare(y.name,'zh-CN');return 0}}a.sort((x,y)=>compareBy(x,y,s1)||compareBy(x,y,s2)||x.name.localeCompare(y.name,'zh-CN')||String(x.id).localeCompare(String(y.id)));n.textContent=a.length;stable.textContent=a.filter(x=>x.status==='稳定在榜').length;newCount.textContent=a.filter(x=>x.status==='新晋榜单').length;drop.textContent=a.filter(x=>x.status==='掉榜'||x.status==='闪现').length;range.textContent=s+' → '+e;count.textContent=a.length+' 部';table.innerHTML=a.length?a.map((x,i)=>'<tr><td>'+ (i+1)+'</td><td>'+ (x.id?'<a class="drama-link" href="'+DETAIL+'_'+encodeURIComponent(x.id)+'.html">'+x.name+'</a>':x.name)+'</td><td>'+x.days+'</td><td class="score-value">'+(x.score==null?'—':x.score.toFixed(2))+'</td><td>#'+x.best+'</td><td>#'+x.worst+'</td><td>#'+x.current+'</td><td>'+(x.rankPoints==null?'—':x.rankPoints.toLocaleString())+'</td><td>'+x.first+'</td><td>'+x.last+'</td><td>'+badge(x.status)+'</td><td>'+badge(x.trend)+'</td></tr>').join(''):'<tr><td colspan="12" class="empty">没有符合条件的数据</td></tr>'}}fetch('data/{datafile}').then(r=>r.json()).then(x=>{{APP=x;render()}});start.onchange=end.onchange=sort1.onchange=sort2.onchange=render;q.oninput=qi.oninput=render;
</script></body></html>'''
    (OUTPUT_DIR/f"{board}.html").write_text(page,encoding='utf-8')

def write_json(board,df):
    p=OUTPUT_DIR/"data";p.mkdir(parents=True,exist_ok=True)
    payload={"meta":{"board":board,"label":BOARDS[board]["label"],"data_start":str(df.日期.min()),"data_end":str(df.日期.max()),"record_count":len(df),"id_count":df.剧集ID.nunique(dropna=True)},"records":records(df)}
    (p/BOARDS[board]["json"]).write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":")),encoding='utf-8')

def clean_output():
    if OUTPUT_DIR.exists():
        for x in OUTPUT_DIR.iterdir():shutil.rmtree(x) if x.is_dir() else x.unlink()
    OUTPUT_DIR.mkdir(parents=True,exist_ok=True)

def main():
    print("="*70);print("🎙️ 猫耳数据中心 · 三榜单构建");print("="*70)
    boards={k:v for k in BOARDS for v in [load_board(k)] if v is not None and not v.empty}
    if not boards:raise RuntimeError("没有找到有效榜单 CSV")
    clean_output()
    for k,df in boards.items():write_json(k,df);board_page(k,df)
    # 首页默认展示“销量月榜”最近 30 天的剧目，而不是只放三个入口卡片。
    # 用户可以在首页直接切换三个榜单；日期默认取当前榜单最新日期往前 30 天。
    available={k:v for k,v in boards.items()}
    if not available:
        raise RuntimeError("没有可用于首页展示的榜单")
    default_board="sales" if "sales" in available else next(iter(available))
    board_meta={k:{"label":BOARDS[k]["label"],"start":str(v.日期.min()),"end":str(v.日期.max())} for k,v in available.items()}
    home_html=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>猫耳数据中心</title>{CSS}
<style>.home-tabs{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}}.home-tab{{background:#15181d;color:#aaa69f;border:1px solid var(--line);height:40px;padding:0 18px;border-radius:9px;font-weight:800}}.home-tab.active{{background:rgba(216,180,106,.14);color:var(--gold2);border-color:rgba(216,180,106,.4)}}.home-board-note{{font-size:11px;color:var(--muted)}}.home-filters{{grid-template-columns:repeat(6,minmax(0,1fr))}}@media(max-width:1050px){{.home-filters{{grid-template-columns:repeat(3,minmax(0,1fr))}}}}@media(max-width:600px){{.home-filters{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
</style></head><body>{nav('home')}<div class="container"><section class="hero"><div class="eyebrow">MAOER · DATA CENTER</div><h1>猫耳数据中心</h1><p>默认显示最新 30 天剧目，可直接切换销量月榜 / 人气月榜 / 新品日榜，并进入单剧详情。</p></section>
<div class="panel"><div class="section-head"><div><h2>榜单切换</h2><span id="boardNote" class="home-board-note"></span></div><a id="moreLink" class="back" href="#">进入完整榜单 →</a></div><div id="tabs" class="home-tabs"></div>
<div class="filters home-filters"><div class="filter"><label>开始日期</label><input id="start" type="date"></div><div class="filter"><label>结束日期</label><input id="end" type="date"></div><div class="filter"><label>排序规则 1</label><select id="sort1"><option value="days">在榜天数 ↓</option><option value="score">综合评分 ↓</option><option value="best">最高排名 ↑</option><option value="current" selected>当前排名 ↑</option><option value="initial">首字母 ↑</option><option value="name">剧名 ↑</option></select></div><div class="filter"><label>排序规则 2</label><select id="sort2"><option value="none">不使用第二排序</option><option value="days">在榜天数 ↓</option><option value="score">综合评分 ↓</option><option value="best">最高排名 ↑</option><option value="current">当前排名 ↑</option><option value="initial" selected>首字母 ↑</option><option value="name">剧名 ↑</option></select></div><div class="filter"><label>搜索剧名</label><input id="q" placeholder="输入剧名…"></div><div class="filter"><label>搜索 ID</label><input id="qi" placeholder="输入剧集 ID…"></div><div class="filter"><label>剧集底色</label><select id="tableTheme"><option value="day">白天</option><option value="night">黑夜</option></select></div><div class="filter"><label>ID 换色阈值</label><input id="idThreshold" type="number" min="0" step="1" placeholder="例如 10000"></div></div></div>
<div class="stats"><div class="stat"><div class="label">剧目数量</div><div id="n" class="value gold">—</div></div><div class="stat"><div class="label">稳定在榜</div><div id="stable" class="value">—</div></div><div class="stat"><div class="label">新晋</div><div id="newCount" class="value">—</div></div><div class="stat"><div class="label">掉榜 / 闪现</div><div id="drop" class="value">—</div></div><div class="stat"><div class="label">统计范围</div><div id="range" class="value" style="font-size:14px">—</div></div></div>
<div class="panel"><div class="section-head"><h2 id="tableTitle">最近 30 天剧目</h2><span id="count" class="muted"></span></div><div id="homeTableWrap" class="table-wrap home-table theme-day"><table><thead><tr><th>#</th><th>剧名</th><th>在榜天数</th><th>综合评分</th><th>最高排名</th><th>最低排名</th><th>当前排名</th><th>累计排名积分</th><th>首次</th><th>最后</th><th>状态</th><th>趋势</th></tr></thead><tbody id="table"></tbody></table></div></div>
<div class="footer">数据由 GitHub Actions 自动更新 · 首页默认最新 30 天</div></div><script>
const META={json.dumps(board_meta,ensure_ascii=False,separators=(',',':'))};const DEFAULT_BOARD='{default_board}';let BOARD=DEFAULT_BOARD,APP=null;
const files={json.dumps({k:BOARDS[k]["json"] for k in available},ensure_ascii=False,separators=(',',':'))};
function id(r){{return r['剧集ID']==null?'':String(r['剧集ID'])}}
function status(g,s,e){{const d=[...new Set(g.map(r=>r.日期))].sort();if(!d.length)return'闪现';if(d[0]===s&&d.at(-1)===e)return'稳定在榜';if(d[0]!==s&&d.at(-1)===e)return'新晋榜单';if(d[0]===s&&d.at(-1)!==e)return'掉榜';return'闪现'}}
function trend(g){{const a=g.map(r=>Number(r.排名)).filter(Number.isFinite);if(a.length<2||a[0]===a.at(-1))return'波动';if(a.every((v,i)=>i===0||v<=a[i-1]))return'上升';if(a.every((v,i)=>i===0||v>=a[i-1]))return'下降';return Math.abs(a.at(-1)-a[0])<=2?'波动':a.at(-1)<a[0]?'上升':'下降'}}
function badge(x){{const c=x==='稳定在榜'?'gold':x==='新晋榜单'?'blue':(x==='掉榜'||x==='下降')?'red':x==='上升'?'green':'gray';return'<span class="badge '+c+'">'+x+'</span>'}}function calculateScore(g,s,e){{if(BOARD!=='sales')return null;const mp=new Map();g.forEach(r=>{{const d=r.日期,n=Number(r.排名);if(!d||!Number.isFinite(n)||n<1||n>50)return;if(!mp.has(d)||n<mp.get(d))mp.set(d,n)}});const vals=[...mp.values()];if(!vals.length)return null;const total=(new Date(e+'T00:00:00')-new Date(s+'T00:00:00'))/86400000+1;if(total<=0)return null;const days=vals.length,daysRate=days/total,rankQuality=vals.reduce((a,r)=>a+(51-r)/50,0)/days,top3=vals.filter(r=>r<=3).length/total,top10=vals.filter(r=>r<=10).length/total,top20=vals.filter(r=>r<=20).length/total;return Number((100*(.30*daysRate+.50*rankQuality+.08*top3+.08*top10+.04*top20)).toFixed(2))}}
function setBoard(b){{BOARD=b;APP=null;document.querySelectorAll('.home-tab').forEach(x=>x.classList.toggle('active',x.dataset.board===b));const m=META[b];const latest=m.end;const d=new Date(latest+'T00:00:00');d.setDate(d.getDate()-29);const first=m.start;start.value=d.toISOString().slice(0,10)>first?d.toISOString().slice(0,10):first;end.value=latest;moreLink.href=b+'.html';boardNote.textContent=m.start+' → '+m.end+' · 默认最新 30 天';tableTitle.textContent=m.label+' · 最近 30 天';fetch('data/'+files[b]).then(r=>r.json()).then(x=>{{APP=x;render()}})}}
function render(){{if(!APP)return;const s=start.value,e=end.value;if(s>e)return;let rows=APP.records.filter(r=>r.日期>=s&&r.日期<=e),qq=q.value.trim().toLowerCase(),ii=qi.value.trim();if(qq)rows=rows.filter(r=>String(r.剧名).toLowerCase().includes(qq));if(ii)rows=rows.filter(r=>id(r).includes(ii));const m=new Map();rows.forEach(r=>{{const k=id(r)?'id:'+id(r):'name:'+r.剧名;if(!m.has(k))m.set(k,[]);m.get(k).push(r)}});let a=[];m.forEach(g=>{{g.sort((x,y)=>x.日期.localeCompare(y.日期));const rs=g.map(r=>Number(r.排名)).filter(Number.isFinite);if(rs.length)a.push({{id:id(g[0]),name:g.at(-1).剧名,initial:g[0].首字母||'#',days:new Set(g.map(r=>r.日期)).size,score:calculateScore(g,s,e),best:Math.min(...rs),worst:Math.max(...rs),rankPoints:BOARD==='sales'?rs.reduce((sum,r)=>sum+(51-r),0):null,current:rs.at(-1),first:g[0].日期,last:g.at(-1).日期,status:status(g,s,e),trend:trend(g)}})}});const s1=sort1.value,s2=sort2.value;function compareBy(x,y,k){{if(k==='none')return 0;if(k==='days')return y.days-x.days;if(k==='score')return (y.score??-1)-(x.score??-1);if(k==='best')return x.best-y.best;if(k==='current')return x.current-y.current;if(k==='initial')return x.initial.localeCompare(y.initial,'zh-CN');if(k==='name')return x.name.localeCompare(y.name,'zh-CN');return 0}}a.sort((x,y)=>compareBy(x,y,s1)||compareBy(x,y,s2)||x.name.localeCompare(y.name,'zh-CN')||String(x.id).localeCompare(String(y.id)));n.textContent=a.length;stable.textContent=a.filter(x=>x.status==='稳定在榜').length;newCount.textContent=a.filter(x=>x.status==='新晋榜单').length;drop.textContent=a.filter(x=>x.status==='掉榜'||x.status==='闪现').length;range.textContent=s+' → '+e;count.textContent=a.length+' 部';table.innerHTML=a.length?a.map((x,i)=>'<tr class=\"'+rowClass(x)+'\"><td>'+(i+1)+'</td><td>'+(x.id?'<a class="drama-link" href="'+files[BOARD].replace('.json','').replace('sales','sales')+'#'+encodeURIComponent(x.id)+'" onclick="return goDetail(event,\''+BOARD+'\',\''+x.id.replace(/\\/g,'')+'\')">'+x.name+'</a>':x.name)+'</td><td>'+x.days+'</td><td class="score-value">'+(x.score==null?'—':x.score.toFixed(2))+'</td><td>#'+x.best+'</td><td>#'+x.worst+'</td><td>#'+x.current+'</td><td>'+(x.rankPoints==null?'—':x.rankPoints.toLocaleString())+'</td><td>'+x.first+'</td><td>'+x.last+'</td><td>'+badge(x.status)+'</td><td>'+badge(x.trend)+'</td></tr>').join(''):'<tr><td colspan="12" class="empty">没有符合条件的数据</td></tr>'}}
function goDetail(ev,b,d){{ev.preventDefault();location.href={json.dumps({k:BOARDS[k]["detail"] for k in available},ensure_ascii=False,separators=(',',':'))}[b]+'_'+encodeURIComponent(d)+'.html';return false}}
function rowClass(x){{const t=idThreshold.value.trim();if(t!==''&&x.id!==''&&Number(x.id)>Number(t))return'threshold-row';return''}}function applyTableTheme(){{homeTableWrap.classList.toggle('theme-day',tableTheme.value==='day');homeTableWrap.classList.toggle('theme-night',tableTheme.value==='night')}}
const tabBox=document.getElementById('tabs');tabBox.innerHTML=Object.keys(META).map(k=>'<button class="home-tab" data-board="'+k+'" onclick="setBoard(\''+k+'\')">'+META[k].label+'</button>').join('');start.onchange=end.onchange=sort1.onchange=sort2.onchange=render;q.oninput=qi.oninput=render;tableTheme.onchange=()=>{{applyTableTheme();render()}};idThreshold.oninput=render;setBoard(DEFAULT_BOARD);applyTableTheme();
</script></body></html>'''
    (OUTPUT_DIR/"index.html").write_text(home_html,encoding='utf-8')
    (OUTPUT_DIR/"build-info.json").write_text(json.dumps({"generated_at":dt.datetime.now().isoformat(timespec='seconds'),"id_key":"剧集ID","boards":{k:{"start":str(v.日期.min()),"end":str(v.日期.max()),"records":len(v)} for k,v in boards.items()}},ensure_ascii=False,indent=2),encoding='utf-8')
    print("🎉 构建完成")

if __name__=='__main__':main()