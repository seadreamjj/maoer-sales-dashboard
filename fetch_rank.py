#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
猫耳 FM 三榜自动抓取版
======================

每天抓取：

1. 销量月榜 Top 50
   type=9, sub_type=3
   保留原有深度分析：
   - 播放量
   - 订阅数
   - 宣发策略
   - 总集数
   - 付费集数
   - 全部集弹幕 UID
   - 付费集弹幕 UID
   - 弹幕留存率
   - 收订比

2. 人气月榜 Top 100
   type=2, sub_type=3
   不进行弹幕 UID 分析。
   保留：
   - 排名
   - 剧名
   - 播放量
   - 订阅数
   - 宣发策略
   - 最新更新
   - 剧集ID

3. 新品日榜 Top 30
   type=1, sub_type=1
   不进行弹幕 UID 分析。
   保留：
   - 排名
   - 剧名
   - 播放量
   - 订阅数
   - 宣发策略
   - 最新更新
   - 剧集ID

Cookie：
从 GitHub Actions Secret MAOER_COOKIE 读取。
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


# ============================================================
# 基础配置
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data" / "raw"
DATA_DIR.mkdir(parents=True, exist_ok=True)

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


# -------------------------
# 榜单配置
# -------------------------

SALES_TOP_N = 50
POPULARITY_TOP_N = 100
NEW_TOP_N = 30

SALES_RANK_URL = (
    "https://www.missevan.com/rank/details"
    "?page=1&page_size=50&type=9&sub_type=3"
)

POPULARITY_RANK_URL = (
    "https://www.missevan.com/rank/details"
    "?page=1&page_size=100&type=2&sub_type=3"
)

NEW_RANK_URL = (
    "https://www.missevan.com/rank/details"
    "?page=1&page_size=50&type=1&sub_type=1"
)


# -------------------------
# 请求配置
# -------------------------

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


# 北京时间
TZ_BEIJING = timezone(timedelta(hours=8))


# ============================================================
# Session / Retry
# ============================================================

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

    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=20,
        pool_maxsize=20,
    )

    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(HEADERS)

    return session


SESSION = build_session()


def request_get(url, *, json_response=False, timeout=REQUEST_TIMEOUT):
    """
    统一 GET 请求。

    429 / 500 / 502 / 503 / 504
    由 HTTPAdapter 自动有限重试。
    """

    resp = SESSION.get(url, timeout=timeout)

    if resp.status_code >= 400:
        raise requests.HTTPError(
            f"HTTP {resp.status_code} for {url}",
            response=resp,
        )

    if json_response:
        return resp.json()

    return resp.text


# ============================================================
# 弹幕 UID
# ============================================================

def get_danmaku_uids(sound_id):
    """获取单集弹幕中的所有 UID。"""

    url = (
        "https://www.missevan.com/sound/getdm"
        f"?soundid={sound_id}"
    )

    try:
        text = request_get(url)

        # p="时间,模式,字号,颜色,时间戳,池,UID,ID"
        dm_raw = re.findall(r'p="(.+?)"', text)

        uids = []

        for item in dm_raw:
            fields = item.split(",")

            if len(fields) >= 8 and fields[6]:
                uids.append(fields[6])

        return uids

    except Exception as exc:
        print(
            f"  ⚠️ sound_id={sound_id} "
            f"弹幕获取失败：{type(exc).__name__}"
        )
        return []


# ============================================================
# 单剧深度统计
# 仅用于销量月榜
# ============================================================

def get_drama_full_stats(drama_id):
    """
    深入统计单部剧：

    - 订阅数
    - 宣发策略
    - 总集数
    - 付费集数
    - 全部集弹幕 UID
    - 付费集弹幕 UID
    """

    stats = {
        "sub_count": 0,
        "strategy": 0,
        "total_ids": 0,
        "paid_ids": 0,
        "all_dm_uids": 0,
        "paid_dm_uids": 0,
    }

    # -------------------------
    # 获取剧集列表
    # -------------------------

    drama_url = (
        "https://www.missevan.com/dramaapi/getdrama"
        f"?drama_id={drama_id}"
    )

    resp_text = request_get(drama_url)

    all_sids = re.findall(
        r'"sound_id":(\d+),',
        resp_text
    )

    pay_types = re.findall(
        r'"need_pay":(\d+),',
        resp_text
    )

    # 沿用原代码的对齐方式
    pay_types = pay_types[1:]
    all_sids = all_sids[:len(pay_types)]

    # 去重
    all_sids_set = list(set(all_sids))

    # 付费集
    paid_sids = [
        sid
        for sid, pay in zip(all_sids, pay_types)
        if pay != "0"
    ]

    stats["total_ids"] = len(all_sids_set)
    stats["paid_ids"] = len(paid_sids)

    # -------------------------
    # 获取订阅数 / 宣发策略
    # -------------------------

    if all_sids_set:

        info_url = (
            "https://www.missevan.com/dramaapi/getdramabysound"
            f"?sound_id={all_sids_set[0]}"
        )

        info_res = request_get(
            info_url,
            json_response=True
        )

        if info_res.get("success"):

            drama_info = (
                info_res
                .get("info", {})
                .get("drama", {})
            )

            stats["sub_count"] = (
                drama_info.get(
                    "subscription_num",
                    0
                ) or 0
            )

            stats["strategy"] = (
                drama_info.get(
                    "strategy_id",
                    0
                ) or 0
            )

    # -------------------------
    # 弹幕 UID
    # -------------------------

    total_uids = set()
    paid_uids = set()
    paid_sids_set = set(paid_sids)

    for sid in all_sids_set:

        uids = get_danmaku_uids(sid)

        total_uids.update(uids)

        if sid in paid_sids_set:
            paid_uids.update(uids)

    stats["all_dm_uids"] = len(total_uids)
    stats["paid_dm_uids"] = len(paid_uids)

    return stats


# ============================================================
# 获取基础剧集信息
# 用于人气月榜 / 新品日榜
# ============================================================

def get_drama_basic_stats(drama_id):
    """
    不抓弹幕。

    仅获取：
    - 订阅数
    - 宣发策略

    这里仍然通过 getdrama + getdramabysound
    保持与销量月榜的订阅口径一致。
    """

    stats = {
        "sub_count": 0,
        "strategy": 0,
    }

    try:

        drama_url = (
            "https://www.missevan.com/dramaapi/getdrama"
            f"?drama_id={drama_id}"
        )

        resp_text = request_get(drama_url)

        all_sids = re.findall(
            r'"sound_id":(\d+),',
            resp_text
        )

        # 去重
        all_sids_set = list(set(all_sids))

        if not all_sids_set:
            return stats

        info_url = (
            "https://www.missevan.com/dramaapi/getdramabysound"
            f"?sound_id={all_sids_set[0]}"
        )

        info_res = request_get(
            info_url,
            json_response=True
        )

        if info_res.get("success"):

            drama_info = (
                info_res
                .get("info", {})
                .get("drama", {})
            )

            stats["sub_count"] = (
                drama_info.get(
                    "subscription_num",
                    0
                ) or 0
            )

            stats["strategy"] = (
                drama_info.get(
                    "strategy_id",
                    0
                ) or 0
            )

    except Exception as exc:

        print(
            f"  ⚠️ ID={drama_id} "
            f"基础信息获取失败：{type(exc).__name__}"
        )

    return stats


# ============================================================
# 通用榜单接口
# ============================================================

def fetch_rank_api(
    rank_url,
    top_n,
    rank_name
):
    """
    获取指定榜单。

    rank_name 仅用于日志。
    """

    print(
        f"[{datetime.now(TZ_BEIJING).strftime('%H:%M:%S')}] "
        f"开始采集{rank_name} Top {top_n}..."
    )

    payload = request_get(
        rank_url,
        json_response=True
    )

    try:
        rank_data = payload["info"]["data"]

    except (KeyError, TypeError) as exc:

        raise RuntimeError(
            f"{rank_name}接口返回结构异常，"
            "无法找到 info.data"
        ) from exc

    if not isinstance(rank_data, list):
        raise RuntimeError(
            f"{rank_name}接口没有返回列表"
        )

    if not rank_data:
        raise RuntimeError(
            f"{rank_name}接口返回空数据"
        )

    rank_data = rank_data[:top_n]

    print(
        f"✅ {rank_name}接口返回 "
        f"{len(rank_data)} 部剧"
    )

    return rank_data


# ============================================================
# 销量月榜
# ============================================================

def fetch_sales_monthly(date_str):
    """
    销量月榜 Top 50。

    保留完整弹幕 UID 分析。
    """

    print("\n" + "=" * 72)
    print("💰 销量月榜 Top 50")
    print("=" * 72)

    rank_data = fetch_rank_api(
        SALES_RANK_URL,
        SALES_TOP_N,
        "销量月榜"
    )

    final_results = []
    failed_dramas = []

    with tqdm(
        total=len(rank_data),
        desc="销量月榜",
        unit="部"
    ) as pbar:

        for index, item in enumerate(rank_data):

            d_id = item.get("id")
            d_name = item.get("name", "")

            pbar.set_description(
                f"销量: {str(d_name)[:12]}…"
            )

            try:

                deep = get_drama_full_stats(d_id)

                retention = 0.0

                if deep["all_dm_uids"] > 0:
                    retention = (
                        deep["paid_dm_uids"]
                        / deep["all_dm_uids"]
                    )

                subscription_ratio = 0.0

                if deep["sub_count"] > 0:
                    subscription_ratio = (
                        deep["paid_dm_uids"]
                        / deep["sub_count"]
                    )

                final_results.append({

                    "排名": index + 1,

                    "剧名": d_name,

                    "播放量": item.get(
                        "view_count"
                    ),

                    "订阅数": deep["sub_count"],

                    "宣发策略": deep["strategy"],

                    "总集数": deep["total_ids"],

                    "付费集数": deep["paid_ids"],

                    "全部集弹幕UID数":
                        deep["all_dm_uids"],

                    "付费集弹幕UID数":
                        deep["paid_dm_uids"],

                    "弹幕留存率":
                        f"{retention:.2%}",

                    "收订比":
                        f"{subscription_ratio:.2%}",

                    "最新更新":
                        item.get("newest"),

                    "剧集ID":
                        d_id,
                })

            except Exception as exc:

                failed_dramas.append({

                    "排名":
                        index + 1,

                    "剧名":
                        d_name,

                    "剧集ID":
                        d_id,

                    "错误":
                        f"{type(exc).__name__}: {exc}",
                })

                print(
                    f"\n❌ ID {d_id}"
                    f"《{d_name}》"
                    f"处理失败："
                    f"{type(exc).__name__}"
                )

            pbar.update(1)

            time.sleep(DRAMA_SLEEP)

    if not final_results:

        raise RuntimeError(
            "销量月榜 Top 50 全部抓取失败，"
            "未生成新的 CSV。"
        )

    output_path = (
        DATA_DIR
        / f"猫耳销量月榜{date_str}.csv"
    )

    pd.DataFrame(
        final_results
    ).to_csv(
        output_path,
        index=False,
        encoding="utf_8_sig"
    )

    if failed_dramas:

        fail_path = (
            LOG_DIR
            / f"猫耳销量月榜{date_str}_失败记录.csv"
        )

        pd.DataFrame(
            failed_dramas
        ).to_csv(
            fail_path,
            index=False,
            encoding="utf_8_sig"
        )

    print(
        f"✅ 销量月榜保存："
        f"{output_path.name}"
    )

    print(
        f"成功 {len(final_results)} / "
        f"{len(rank_data)}"
    )

    return output_path


# ============================================================
# 人气月榜
# ============================================================

def fetch_popularity_monthly(date_str):
    """
    人气月榜 Top 100。

    不进行任何弹幕 UID 分析。
    """

    print("\n" + "=" * 72)
    print("🔥 人气月榜 Top 100")
    print("=" * 72)

    rank_data = fetch_rank_api(
        POPULARITY_RANK_URL,
        POPULARITY_TOP_N,
        "人气月榜"
    )

    final_results = []
    failed_dramas = []

    with tqdm(
        total=len(rank_data),
        desc="人气月榜",
        unit="部"
    ) as pbar:

        for index, item in enumerate(rank_data):

            d_id = item.get("id")
            d_name = item.get("name", "")

            pbar.set_description(
                f"人气: {str(d_name)[:12]}…"
            )

            try:

                basic = get_drama_basic_stats(
                    d_id
                )

                final_results.append({

                    "排名":
                        index + 1,

                    "剧名":
                        d_name,

                    "播放量":
                        item.get(
                            "view_count"
                        ),

                    "订阅数":
                        basic["sub_count"],

                    "宣发策略":
                        basic["strategy"],

                    "最新更新":
                        item.get("newest"),

                    "剧集ID":
                        d_id,
                })

            except Exception as exc:

                failed_dramas.append({

                    "排名":
                        index + 1,

                    "剧名":
                        d_name,

                    "剧集ID":
                        d_id,

                    "错误":
                        f"{type(exc).__name__}: {exc}",
                })

                print(
                    f"\n❌ ID {d_id}"
                    f"《{d_name}》"
                    f"处理失败："
                    f"{type(exc).__name__}"
                )

            pbar.update(1)

            time.sleep(DRAMA_SLEEP)

    if not final_results:

        raise RuntimeError(
            "人气月榜 Top 100 全部抓取失败，"
            "未生成新的 CSV。"
        )

    output_path = (
        DATA_DIR
        / f"猫耳人气月榜{date_str}.csv"
    )

    pd.DataFrame(
        final_results
    ).to_csv(
        output_path,
        index=False,
        encoding="utf_8_sig"
    )

    if failed_dramas:

        fail_path = (
            LOG_DIR
            / f"猫耳人气月榜{date_str}_失败记录.csv"
        )

        pd.DataFrame(
            failed_dramas
        ).to_csv(
            fail_path,
            index=False,
            encoding="utf_8_sig"
        )

    print(
        f"✅ 人气月榜保存："
        f"{output_path.name}"
    )

    print(
        f"成功 {len(final_results)} / "
        f"{len(rank_data)}"
    )

    return output_path


# ============================================================
# 新品日榜
# ============================================================

def fetch_new_daily(date_str):
    """
    新品日榜。

    API 请求 page_size=50，
    但按照用户要求，只保存前 30 名。

    不进行弹幕 UID 分析。
    """

    print("\n" + "=" * 72)
    print("🆕 新品日榜 Top 30")
    print("=" * 72)

    rank_data = fetch_rank_api(
        NEW_RANK_URL,
        NEW_TOP_N,
        "新品日榜"
    )

    final_results = []
    failed_dramas = []

    with tqdm(
        total=len(rank_data),
        desc="新品日榜",
        unit="部"
    ) as pbar:

        for index, item in enumerate(rank_data):

            d_id = item.get("id")
            d_name = item.get("name", "")

            pbar.set_description(
                f"新品: {str(d_name)[:12]}…"
            )

            try:

                basic = get_drama_basic_stats(
                    d_id
                )

                final_results.append({

                    "排名":
                        index + 1,

                    "剧名":
                        d_name,

                    "播放量":
                        item.get(
                            "view_count"
                        ),

                    "订阅数":
                        basic["sub_count"],

                    "宣发策略":
                        basic["strategy"],

                    "最新更新":
                        item.get("newest"),

                    "剧集ID":
                        d_id,
                })

            except Exception as exc:

                failed_dramas.append({

                    "排名":
                        index + 1,

                    "剧名":
                        d_name,

                    "剧集ID":
                        d_id,

                    "错误":
                        f"{type(exc).__name__}: {exc}",
                })

                print(
                    f"\n❌ ID {d_id}"
                    f"《{d_name}》"
                    f"处理失败："
                    f"{type(exc).__name__}"
                )

            pbar.update(1)

            time.sleep(DRAMA_SLEEP)

    if not final_results:

        raise RuntimeError(
            "新品日榜 Top 30 全部抓取失败，"
            "未生成新的 CSV。"
        )

    output_path = (
        DATA_DIR
        / f"猫耳新品日榜{date_str}.csv"
    )

    pd.DataFrame(
        final_results
    ).to_csv(
        output_path,
        index=False,
        encoding="utf_8_sig"
    )

    if failed_dramas:

        fail_path = (
            LOG_DIR
            / f"猫耳新品日榜{date_str}_失败记录.csv"
        )

        pd.DataFrame(
            failed_dramas
        ).to_csv(
            fail_path,
            index=False,
            encoding="utf_8_sig"
        )

    print(
        f"✅ 新品日榜保存："
        f"{output_path.name}"
    )

    print(
        f"成功 {len(final_results)} / "
        f"{len(rank_data)}"
    )

    return output_path


# ============================================================
# 主程序
# ============================================================

def main():

    print("\n" + "=" * 72)
    print("🎙️ 猫耳 FM 三榜自动采集")
    print("=" * 72)

    now_beijing = datetime.now(
        TZ_BEIJING
    )

    date_str = now_beijing.strftime(
        "%Y%m%d"
    )

    print(
        f"北京时间："
        f"{now_beijing.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    print(
        f"Cookie："
        f"{'已配置' if COOKIE else '未配置'}"
    )

    if not COOKIE:

        print(
            "⚠️ MAOER_COOKIE 未设置。"
            "如果接口需要登录态，抓取可能失败。"
        )

    results = []

    # ========================================================
    # 1. 销量月榜
    # ========================================================

    results.append(
        fetch_sales_monthly(
            date_str
        )
    )

    # ========================================================
    # 2. 人气月榜
    # ========================================================

    results.append(
        fetch_popularity_monthly(
            date_str
        )
    )

    # ========================================================
    # 3. 新品日榜
    # ========================================================

    results.append(
        fetch_new_daily(
            date_str
        )
    )

    # ========================================================
    # 完成
    # ========================================================

    print("\n" + "=" * 72)
    print("🎉 三榜全部抓取完成")
    print("=" * 72)

    for path in results:
        print(f"📄 {path}")

    print("=" * 72)

    return results


if __name__ == "__main__":
    main()
