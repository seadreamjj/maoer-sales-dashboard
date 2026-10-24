#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""猫耳四个榜单每日抓取。

- 销量月榜：Top 50，保留原有深度弹幕 UID 分析
- 销量周榜：Top 50，只抓基础榜单数据，不抓弹幕 UID
- 人气月榜：Top 100，只抓基础榜单数据，不抓弹幕 UID
- 新品日榜：接口取 Top 50，但只保存前 30，只抓基础榜单数据
- 剧集作者、会员、价格、标签、CV 信息写入按剧集 ID 去重的长期缓存

Cookie 从 GitHub Actions Secret MAOER_COOKIE 读取。
"""

import os
import re
import json
import time
import argparse
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
SALES_WEEKLY_TOP_N = 50
POPULARITY_TOP_N = 100
NEW_TOP_N = 30

SALES_URL = "https://www.missevan.com/rank/details?page=1&page_size=50&type=9&sub_type=3"
SALES_WEEKLY_URL = "https://www.missevan.com/rank/details?page=1&page_size=50&type=9&sub_type=2"
DRAMA_INFO_CACHE = DATA_DIR / "猫耳剧集信息.csv"
POPULARITY_URL = "https://www.missevan.com/rank/details?page=1&page_size=100&type=2&sub_type=3"
NEW_URL = "https://www.missevan.com/rank/details?page=1&page_size=50&type=1&sub_type=1"

DRAMA_SLEEP = float(os.getenv("DRAMA_SLEEP", "0.5"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "4"))
COOKIE = os.getenv("MAOER_COOKIE", "").strip()

HEADERS = {
    "User-Agent": os.getenv(
        "MAOER_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/100.0.4896.127 Safari/537.36",
    ),
    "Referer": "https://www.missevan.com/",
    "Accept": "application/json, text/plain, */*",
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


def _find_metadata_object(payload):
    """兼容 getdrama 返回对象外层结构不同的情况，找到包含剧集资料的字典。"""
    if isinstance(payload, dict):
        keys = {str(k).lower() for k in payload}
        if keys.intersection({"author", "vip", "price", "tags", "cvs"}):
            return payload
        for value in payload.values():
            found = _find_metadata_object(value)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_metadata_object(value)
            if found is not None:
                return found
    return None


def _names(value):
    """将标签/CV 字段转成可读名称；兼容字符串、字典和列表。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        name = value.get("name") or value.get("title") or value.get("nickname")
        if name:
            return [str(name).strip()]
        out = []
        for v in value.values():
            out.extend(_names(v))
        return out
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(_names(item))
        return out
    return []



def parse_drama_metadata(drama_id, payload):
    """解析猫耳剧集基础信息：作者、会员、价格、标签、CV1、CV2。"""
    try:
        # 兼容传入 JSON 字符串或已解析的字典
        if isinstance(payload, str):
            payload = json.loads(payload)

        if not isinstance(payload, dict):
            raise ValueError("API 返回内容不是字典")

        # 按 getdrama 的实际数据结构读取
        info = payload.get("info", {})
        if not isinstance(info, dict):
            info = {}

        drama = info.get("drama", {})
        if not isinstance(drama, dict):
            drama = {}

        # 作者
        author = drama.get("author", "")
        if isinstance(author, dict):
            author = author.get("name", "")
        author = str(author or "").strip()

        # 标签：例如玄幻、仙侠、情有独钟
        tags = drama.get("tags", [])
        tag_names = []
        if isinstance(tags, list):
            for tag in tags:
                if isinstance(tag, dict):
                    name = tag.get("name", "")
                else:
                    name = tag
                name = str(name or "").strip()
                if name and name not in tag_names:
                    tag_names.append(name)
        elif isinstance(tags, dict):
            name = tags.get("name", "")
            if name:
                tag_names.append(str(name).strip())

        # CV：提取配音演员姓名，不把角色名误当成 CV 姓名
        cv_list = info.get("cvs", [])
        cv_names = []

        if isinstance(cv_list, list):
            for cv in cv_list:
                if not isinstance(cv, dict):
                    continue

                cv_info = cv.get("cv_info", {})
                if isinstance(cv_info, dict):
                    name = cv_info.get("name", "")
                else:
                    name = ""

                name = str(name or "").strip()
                if name:
                    cv_names.append(name)

        elif isinstance(cv_list, dict):
            for key in ("cv1", "cv2"):
                cv = cv_list.get(key, {})
                if isinstance(cv, dict):
                    cv_info = cv.get("cv_info", {})
                    name = (
                        cv_info.get("name", "")
                        if isinstance(cv_info, dict) and cv_info.get("name")
                        else cv.get("name", "")
                    )
                else:
                    name = cv

                name = str(name or "").strip()
                if name:
                    cv_names.append(name)

        # 价格：沿用原有逻辑，将 API 返回的价格除以 10
        try:
            price = float(drama.get("price", 0) or 0) / 10
            price = round(price, 2)
        except (TypeError, ValueError):
            price = ""

        # 会员标记
        vip = drama.get("vip", 0)
        try:
            vip = int(vip or 0)
        except (TypeError, ValueError):
            vip = 0

        return {
            "剧集ID": str(drama.get("id") or drama_id),
            "作者": author,
            "是否会员剧": "是" if vip == 1 else "否",
            "价格（元）": price,
            "标签": "、".join(tag_names),
            "CV1": cv_names[0] if len(cv_names) > 0 else "",
            "CV2": cv_names[1] if len(cv_names) > 1 else "",
            "信息更新时间": now_beijing().strftime("%Y-%m-%d %H:%M:%S"),
        }

    except Exception as e:
        print(f"⚠️ 解析剧集 {drama_id} 的基础信息失败：{e}")
        return {
            "剧集ID": str(drama_id),
            "作者": "",
            "是否会员剧": "",
            "价格（元）": "",
            "标签": "",
            "CV1": "",
            "CV2": "",
            "信息更新时间": now_beijing().strftime("%Y-%m-%d %H:%M:%S"),
        }


    

   
    


def upsert_drama_info_cache(metadata_rows):
    """按剧集 ID 更新长期资料缓存；缺失值不覆盖旧的有效资料。"""
    if not metadata_rows:
        return
    columns = ["剧集ID", "作者", "是否会员剧", "价格（元）", "标签", "CV1", "CV2", "信息更新时间"]
    if DRAMA_INFO_CACHE.exists():
        try:
            old = pd.read_csv(DRAMA_INFO_CACHE, dtype={"剧集ID": str}, encoding="utf-8-sig").fillna("")
        except Exception:
            old = pd.DataFrame(columns=columns)
    else:
        old = pd.DataFrame(columns=columns)
    for c in columns:
        if c not in old.columns:
            old[c] = ""
    cache = {str(row.get("剧集ID", "")): row for row in old.to_dict("records") if str(row.get("剧集ID", "")).strip()}
    for item in metadata_rows:
        did = str(item.get("剧集ID", "")).strip()
        if not did:
            continue
        prior = cache.get(did, {})
        merged = dict(prior)
        # 已有缓存的有效资料不重复覆盖；仅补齐空字段，避免每次抓榜都刷新静态资料。
        changed = False
        for c in columns:
            value = item.get(c, "")
            existing = merged.get(c, "")
            if c == "信息更新时间":
                continue
            if (existing is None or str(existing).strip() == "" or str(existing).lower() == "nan") and value is not None and str(value).strip() != "":
                merged[c] = value
                changed = True
            elif c not in merged:
                merged[c] = ""
        if not prior or changed:
            merged["信息更新时间"] = item.get("信息更新时间", "")
        merged["剧集ID"] = did
        cache[did] = merged
    out = pd.DataFrame(list(cache.values()), columns=columns)
    out.sort_values("剧集ID", key=lambda col: col.astype(str), inplace=True)
    out.to_csv(DRAMA_INFO_CACHE, index=False, encoding="utf_8_sig")


def fetch_drama_metadata(drama_id, response_text=None):
    """从已有 getdrama 响应解析资料；未传响应时才请求 API。"""
    try:
        payload = json.loads(response_text) if response_text is not None else request_get(
            f"https://www.missevan.com/dramaapi/getdrama?drama_id={drama_id}", json_response=True
        )
        return parse_drama_metadata(drama_id, payload)
    except Exception as exc:
        print(f"  ⚠️ ID={drama_id} 剧集资料获取失败：{type(exc).__name__}")
        return None


def get_drama_full_stats(drama_id):
    """销量月榜深度统计：集数、订阅、弹幕 UID。"""
    stats = {"sub_count": 0, "strategy": 0, "total_ids": 0, "paid_ids": 0,
             "all_dm_uids": 0, "paid_dm_uids": 0}
    drama_url = f"https://www.missevan.com/dramaapi/getdrama?drama_id={drama_id}"
    resp_text = request_get(drama_url)
    stats["metadata"] = fetch_drama_metadata(drama_id, resp_text)
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
    stats["metadata"] = fetch_drama_metadata(drama_id, text)
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
    results, failed, metadata_rows = [], [], []
    with tqdm(total=len(rank_data), desc=label, unit="部") as pbar:
        for index, item in enumerate(rank_data):
            drama_id = item.get("id")
            name = item.get("name", "")
            pbar.set_description(f"{label}: {str(name)[:12]}…")
            try:
                basic = get_drama_basic_stats(drama_id)
                if basic.get("metadata"):
                    metadata_rows.append(basic["metadata"])
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
    upsert_drama_info_cache(metadata_rows)
    print(f"✅ {label}: {len(results)}/{len(rank_data)} → {path.name}")
    return path


def save_sales_rank(rank_data):
    results, failed, metadata_rows = [], [], []
    with tqdm(total=len(rank_data), desc="销量月榜", unit="部") as pbar:
        for index, item in enumerate(rank_data):
            drama_id = item.get("id")
            name = item.get("name", "")
            pbar.set_description(f"销量月榜: {str(name)[:12]}…")
            try:
                deep = get_drama_full_stats(drama_id)
                if deep.get("metadata"):
                    metadata_rows.append(deep["metadata"])
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
    upsert_drama_info_cache(metadata_rows)
    print(f"✅ 销量月榜: {len(results)}/{len(rank_data)} → {path.name}")
    return path


BOARD_CONFIG = {
    "sales": ("猫耳销量月榜", SALES_URL, SALES_TOP_N, "销量月榜", "deep"),
    "weekly": ("猫耳销量周榜", SALES_WEEKLY_URL, SALES_WEEKLY_TOP_N, "销量周榜", "basic"),
    "popularity": ("猫耳人气月榜", POPULARITY_URL, POPULARITY_TOP_N, "人气月榜", "basic"),
    "new": ("猫耳新品日榜", NEW_URL, NEW_TOP_N, "新品日榜", "basic"),
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="抓取猫耳四个榜单。默认跳过当天已有的榜单文件。"
    )
    parser.add_argument(
        "--boards",
        default=os.getenv("MAOER_BOARDS", "all"),
        help="要抓取的榜单，逗号分隔：sales,weekly,popularity,new；默认 all",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=os.getenv("MAOER_FORCE", "").strip().lower() in {"1", "true", "yes", "y"},
        help="强制重抓并覆盖当天已有文件",
    )
    return parser.parse_args()


def board_file_path(prefix, date_str=None):
    date_str = date_str or now_beijing().strftime("%Y%m%d")
    return DATA_DIR / f"{prefix}{date_str}.csv"


def main():
    args = parse_args()
    requested = [x.strip().lower() for x in args.boards.split(",") if x.strip()]
    if requested == ["all"]:
        selected = list(BOARD_CONFIG)
    else:
        unknown = sorted(set(requested) - set(BOARD_CONFIG))
        if unknown or not requested:
            raise SystemExit(
                f"无效的 --boards 值：{', '.join(unknown) if unknown else args.boards}。"
                f"可选：all, {', '.join(BOARD_CONFIG)}"
            )
        # 保持标准顺序并去重
        selected = [key for key in BOARD_CONFIG if key in requested]

    print("=" * 72)
    print("🎙️ 猫耳四榜单自动抓取")
    print("=" * 72)
    print(f"北京时间：{now_beijing().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"抓取范围：{', '.join(selected)}")
    print(f"已有数据处理：{'强制覆盖' if args.force else '跳过当天已有文件'}")
    print(f"Cookie：{'已配置' if COOKIE else '未配置'}")
    if not COOKIE:
        print("⚠️ MAOER_COOKIE 未设置；如果接口需要登录态，抓取可能失败。")

    date_str = now_beijing().strftime("%Y%m%d")
    for key in selected:
        prefix, url, limit, label, mode = BOARD_CONFIG[key]
        output_path = board_file_path(prefix, date_str)
        if output_path.exists() and not args.force:
            print(f"⏭️ 跳过{label}：当天文件已存在（{output_path.name}）")
            continue

        if key == "new":
            # 接口取 Top 50，但只保存前 30
            rank_data = fetch_rank(url, 50, label)[:limit]
        else:
            rank_data = fetch_rank(url, limit, label)

        if mode == "deep":
            save_sales_rank(rank_data)
        else:
            save_basic_rank(rank_data, label, prefix, limit)

    print("=" * 72)
    print("✅ 本次所选榜单处理完成")
    print("=" * 72)


if __name__ == "__main__":
    main()
