#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""猫耳三个榜单每日抓取。

- 销量月榜：Top 50，保留原有深度弹幕 UID 分析
- 人气月榜：Top 100，只抓基础榜单数据，不抓弹幕 UID
- 新品日榜：接口取 Top 50，但只保存前 30，只抓基础榜单数据

Cookie 从 GitHub Actions Secret MAOER_COOKIE 读取。
"""

import os
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tqdm import tqdm

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "raw"
LOG_DIR = BASE_DIR / "logs"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

SALES_TOP_N = 50
POPULARITY_TOP_N = 100
NEW_TOP_N = 30

SALES_URL = "https://www.missevan.com/rank/details?page=1&page_size=50&type=9&sub_type=3"
POPULARITY_URL = "https://www.missevan.com/rank/details?page=1&page_size=100&type=2&sub_type=3"
NEW_URL = "https://www.missevan.com/rank/details?page=1&page_size=50&type=1&sub_type=1"

DRAMA_SLEEP = float(os.getenv("DRAMA_SLEEP", "0.5"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "4"))
COOKIE = os.getenv("MAOER_COOKIE", "").strip()

HEADERS = {
    "User-Agent": os.getenv(
        "MAOER_USER_AGENT",
        "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 "
        "Mobile Safari/537.36",
    ),
    "Accept": "*/*",
    "Connection": "keep-alive",
}
if COOKIE:
    HEADERS["Cookie"] = COOKIE


def build_session():
    session = requests.Session()
    retry = Retry(
        total=MAX_RETRIES,
        connect=MAX_RETRIES,
        read=MAX_RETRIES,
        status=MAX_RETRIES,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(HEADERS)
    return session


SESSION = build_session()


def request_get(url, *, json_response=False, timeout=REQUEST_TIMEOUT):
    resp = SESSION.get(url, timeout=timeout)
    if resp.status_code >= 400:
        raise requests.HTTPError(f"HTTP {resp.status_code} for {url}", response=resp)
    return resp.json() if json_response else resp.text


def get_danmaku_uids(sound_id):
    """仅用于销量月榜：获取单集弹幕 UID。"""
    url = f"https://www.missevan.com/sound/getdm?soundid={sound_id}"
    try:
        text = request_get(url)
        dm_raw = re.findall(r'p="(.+?)"', text)
        return [item.split(",")[6] for item in dm_raw if len(item.split(",")) >= 8 and item.split(",")[6]]
    except Exception as exc:
        print(f"  ⚠️ sound_id={sound_id} 弹幕获取失败：{type(exc).__name__}")
        return []


def get_drama_full_stats(drama_id):
    """销量月榜深度统计：集数、订阅、弹幕 UID。"""
    stats = {"sub_count": 0, "strategy": 0, "total_ids": 0, "paid_ids": 0,
             "all_dm_uids": 0, "paid_dm_uids": 0}
    drama_url = f"https://www.missevan.com/dramaapi/getdrama?drama_id={drama_id}"
    resp_text = request_get(drama_url)
    all_sids = re.findall(r'"sound_id":(\d+),', resp_text)
    pay_types = re.findall(r'"need_pay":(\d+),', resp_text)
    pay_types = pay_types[1:]
    all_sids = all_sids[: len(pay_types)]
    all_sids_set = list(set(all_sids))
    paid_sids = [sid for sid, pay in zip(all_sids, pay_types) if pay != "0"]
    stats["total_ids"] = len(all_sids_set)
    stats["paid_ids"] = len(set(paid_sids))

    if all_sids_set:
        info_url = f"https://www.missevan.com/dramaapi/getdramabysound?sound_id={all_sids_set[0]}"
        info_res = request_get(info_url, json_response=True)
        if info_res.get("success"):
            drama_info = info_res.get("info", {}).get("drama", {})
            stats["sub_count"] = drama_info.get("subscription_num", 0) or 0
            stats["strategy"] = drama_info.get("strategy_id", 0) or 0

    total_uids, paid_uids = set(), set()
    paid_sids_set = set(paid_sids)
    for sid in all_sids_set:
        uids = get_danmaku_uids(sid)
        total_uids.update(uids)
        if sid in paid_sids_set:
            paid_uids.update(uids)
    stats["all_dm_uids"] = len(total_uids)
    stats["paid_dm_uids"] = len(paid_uids)
    return stats


def get_drama_basic_stats(drama_id):
    """人气/月榜与新品日榜只获取基础信息，不抓弹幕。"""
    stats = {"sub_count": 0, "strategy": 0, "total_ids": 0, "paid_ids": 0}
    drama_url = f"https://www.missevan.com/dramaapi/getdrama?drama_id={drama_id}"
    text = request_get(drama_url)
    all_sids = list(dict.fromkeys(re.findall(r'"sound_id":(\d+),', text)))
    pay_types = re.findall(r'"need_pay":(\d+),', text)[1:]
    stats["total_ids"] = len(all_sids)
    stats["paid_ids"] = sum(1 for x in pay_types[:len(all_sids)] if x != "0")
    if all_sids:
        info_url = f"https://www.missevan.com/dramaapi/getdramabysound?sound_id={all_sids[0]}"
        info_res = request_get(info_url, json_response=True)
        if info_res.get("success"):
            drama_info = info_res.get("info", {}).get("drama", {})
            stats["sub_count"] = drama_info.get("subscription_num", 0) or 0
            stats["strategy"] = drama_info.get("strategy_id", 0) or 0
    return stats


def fetch_rank(url, limit, label):
    payload = request_get(url, json_response=True)
    try:
        data = payload["info"]["data"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"{label}接口返回结构异常，无法找到 info.data") from exc
    if not isinstance(data, list) or not data:
        raise RuntimeError(f"{label}接口没有返回有效数据")
    return data[:limit]


def now_beijing():
    return datetime.now(timezone(timedelta(hours=8)))


def save_basic_rank(rank_data, label, filename_prefix, limit):
    results, failed = [], []
    with tqdm(total=len(rank_data), desc=label, unit="部") as pbar:
        for index, item in enumerate(rank_data):
            drama_id = item.get("id")
            name = item.get("name", "")
            pbar.set_description(f"{label}: {str(name)[:12]}…")
            try:
                basic = get_drama_basic_stats(drama_id)
                results.append({
                    "排名": index + 1,
                    "剧名": name,
                    "播放量": item.get("view_count"),
                    "订阅数": basic["sub_count"],
                    "宣发策略": basic["strategy"],
                    "总集数": basic["total_ids"],
                    "付费集数": basic["paid_ids"],
                    "最新更新": item.get("newest"),
                    "剧集ID": drama_id,
                })
            except Exception as exc:
                failed.append({"排名": index + 1, "剧名": name, "剧集ID": drama_id,
                               "错误": f"{type(exc).__name__}: {exc}"})
                print(f"\n❌ ID {drama_id}《{name}》处理失败：{type(exc).__name__}")
            pbar.update(1)
            time.sleep(DRAMA_SLEEP)

    if not results:
        raise RuntimeError(f"{label}全部抓取失败，不生成空文件")

    date_str = now_beijing().strftime("%Y%m%d")
    path = DATA_DIR / f"{filename_prefix}{date_str}.csv"
    pd.DataFrame(results).to_csv(path, index=False, encoding="utf_8_sig")
    if failed:
        fail_path = LOG_DIR / f"{filename_prefix}{date_str}_失败记录.csv"
        pd.DataFrame(failed).to_csv(fail_path, index=False, encoding="utf_8_sig")
    print(f"✅ {label}: {len(results)}/{len(rank_data)} → {path.name}")
    return path


def save_sales_rank(rank_data):
    results, failed = [], []
    with tqdm(total=len(rank_data), desc="销量月榜", unit="部") as pbar:
        for index, item in enumerate(rank_data):
            drama_id = item.get("id")
            name = item.get("name", "")
            pbar.set_description(f"销量月榜: {str(name)[:12]}…")
            try:
                deep = get_drama_full_stats(drama_id)
                retention = deep["paid_dm_uids"] / deep["all_dm_uids"] if deep["all_dm_uids"] else 0
                ratio = deep["paid_dm_uids"] / deep["sub_count"] if deep["sub_count"] else 0
                results.append({
                    "排名": index + 1,
                    "剧名": name,
                    "播放量": item.get("view_count"),
                    "订阅数": deep["sub_count"],
                    "宣发策略": deep["strategy"],
                    "总集数": deep["total_ids"],
                    "付费集数": deep["paid_ids"],
                    "全部集弹幕UID数": deep["all_dm_uids"],
                    "付费集弹幕UID数": deep["paid_dm_uids"],
                    "弹幕留存率": f"{retention:.2%}",
                    "收订比": f"{ratio:.2%}",
                    "最新更新": item.get("newest"),
                    "剧集ID": drama_id,
                })
            except Exception as exc:
                failed.append({"排名": index + 1, "剧名": name, "剧集ID": drama_id,
                               "错误": f"{type(exc).__name__}: {exc}"})
                print(f"\n❌ ID {drama_id}《{name}》处理失败：{type(exc).__name__}")
            pbar.update(1)
            time.sleep(DRAMA_SLEEP)

    if not results:
        raise RuntimeError("销量月榜全部抓取失败，不生成空文件")
    date_str = now_beijing().strftime("%Y%m%d")
    path = DATA_DIR / f"猫耳销量月榜{date_str}.csv"
    pd.DataFrame(results).to_csv(path, index=False, encoding="utf_8_sig")
    if failed:
        pd.DataFrame(failed).to_csv(LOG_DIR / f"猫耳销量月榜{date_str}_失败记录.csv", index=False, encoding="utf_8_sig")
    print(f"✅ 销量月榜: {len(results)}/{len(rank_data)} → {path.name}")
    return path


def main():
    print("=" * 72)
    print("🎙️ 猫耳三榜单自动抓取")
    print("=" * 72)
    print(f"北京时间：{now_beijing().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Cookie：{'已配置' if COOKIE else '未配置'}")
    if not COOKIE:
        print("⚠️ MAOER_COOKIE 未设置；如果接口需要登录态，抓取可能失败。")

    # 销量月榜：唯一进行弹幕 UID 深度分析的榜单
    sales = fetch_rank(SALES_URL, SALES_TOP_N, "销量月榜")
    save_sales_rank(sales)

    # 人气月榜、新品日榜：不抓弹幕 UID
    popularity = fetch_rank(POPULARITY_URL, POPULARITY_TOP_N, "人气月榜")
    save_basic_rank(popularity, "人气月榜", "猫耳人气月榜", POPULARITY_TOP_N)

    new = fetch_rank(NEW_URL, 50, "新品日榜")
    save_basic_rank(new[:NEW_TOP_N], "新品日榜", "猫耳新品日榜", NEW_TOP_N)

    print("=" * 72)
    print("✅ 三个榜单抓取完成")
    print("=" * 72)


if __name__ == "__main__":
    main()
