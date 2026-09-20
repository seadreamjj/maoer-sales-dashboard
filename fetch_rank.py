#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
猫耳销量月榜：GitHub Actions 自动抓取版

数据口径沿用用户原始 Colab 代码：
- 月榜：type=9, sub_type=3, Top 50
- 播放量：月榜接口 view_count
- 订阅数：getdramabysound -> subscription_num
- 宣发策略：getdramabysound -> strategy_id
- 总集数：剧详情中的 sound_id 去重后数量
- 付费集数：need_pay != 0 的 sound_id 数量
- 全部集弹幕 UID：所有集弹幕 UID 去重
- 付费集弹幕 UID：付费集弹幕 UID 去重
- 弹幕留存率：付费集弹幕 UID / 全部集弹幕 UID
- 收订比：付费集弹幕 UID / 订阅数

GitHub Actions 中的 Cookie 从环境变量 MAOER_COOKIE 读取，绝不写入代码。
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


# =========================
# 配置
# =========================
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "raw"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

TOP_N = 50
RANK_URL = "https://www.missevan.com/rank/details?page=1&page_size=50&type=9&sub_type=3"

# 猫耳请求较多，保留原来的 0.5 秒剧间隔，并对 HTTP 错误做有限重试。
DRAMA_SLEEP = float(os.getenv("DRAMA_SLEEP", "0.5"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "4"))

# 不在日志中打印 Cookie。
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


# =========================
# Session / 重试
# =========================
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
    """统一 GET；429/5xx 由 HTTPAdapter 重试，最终失败时抛出异常。"""
    resp = SESSION.get(url, timeout=timeout)
    if resp.status_code >= 400:
        # 不输出完整 URL 以外的敏感信息；URL 本身不包含 Cookie。
        raise requests.HTTPError(
            f"HTTP {resp.status_code} for {url}", response=resp
        )
    if json_response:
        return resp.json()
    return resp.text


# =========================
# 弹幕 UID
# =========================
def get_danmaku_uids(sound_id):
    """获取单集弹幕的所有 UID。"""
    url = f"https://www.missevan.com/sound/getdm?soundid={sound_id}"
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
        # 单集失败不让整部剧失败；在日志中保留 sound_id 便于排查。
        print(f"  ⚠️ sound_id={sound_id} 弹幕获取失败：{type(exc).__name__}")
        return []


# =========================
# 单剧深度统计
# =========================
def get_drama_full_stats(drama_id):
    """深入统计单部剧：集数、订阅、弹幕 UID。"""
    stats = {
        "sub_count": 0,
        "strategy": 0,
        "total_ids": 0,
        "paid_ids": 0,
        "all_dm_uids": 0,
        "paid_dm_uids": 0,
    }

    drama_url = f"https://www.missevan.com/dramaapi/getdrama?drama_id={drama_id}"
    resp_text = request_get(drama_url)

    all_sids = re.findall(r'"sound_id":(\d+),', resp_text)
    pay_types = re.findall(r'"need_pay":(\d+),', resp_text)

    # 沿用原代码的对齐方式。
    pay_types = pay_types[1:]
    all_sids = all_sids[: len(pay_types)]

    # 保留原逻辑的“去重后总集数”。
    all_sids_set = list(set(all_sids))
    paid_sids = [sid for sid, pay in zip(all_sids, pay_types) if pay != "0"]

    stats["total_ids"] = len(all_sids_set)
    stats["paid_ids"] = len(paid_sids)

    # 订阅数 / 宣发策略
    if all_sids_set:
        info_url = (
            "https://www.missevan.com/dramaapi/getdramabysound"
            f"?sound_id={all_sids_set[0]}"
        )
        info_res = request_get(info_url, json_response=True)
        if info_res.get("success"):
            drama_info = info_res.get("info", {}).get("drama", {})
            stats["sub_count"] = drama_info.get("subscription_num", 0) or 0
            stats["strategy"] = drama_info.get("strategy_id", 0) or 0

    # 所有集 / 付费集 UID 去重
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


# =========================
# 获取 Top 50
# =========================
def fetch_rank_data():
    payload = request_get(RANK_URL, json_response=True)
    try:
        rank_data = payload["info"]["data"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError("月榜接口返回结构异常，无法找到 info.data") from exc

    if not isinstance(rank_data, list) or not rank_data:
        raise RuntimeError("月榜接口没有返回有效的 Top 50 数据")

    return rank_data[:TOP_N]


# =========================
# 主程序
# =========================
def main():
    print("=" * 72)
    print("🎙️ 猫耳销量月榜 GitHub Actions 自动抓取")
    print("=" * 72)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 获取月榜 Top {TOP_N}…")
    print(f"Cookie：{'已配置' if COOKIE else '未配置'}")

    if not COOKIE:
        print("⚠️ MAOER_COOKIE 未设置；如果接口需要登录态，抓取可能失败。")

    rank_data = fetch_rank_data()
    print(f"✅ 月榜接口返回 {len(rank_data)} 部剧")

    final_results = []
    failed_dramas = []

    with tqdm(total=len(rank_data), desc="总进度", unit="部") as pbar:
        for index, item in enumerate(rank_data):
            d_id = item.get("id")
            d_name = item.get("name", "")
            pbar.set_description(f"正在分析: {str(d_name)[:12]}…")

            try:
                deep = get_drama_full_stats(d_id)

                retention = 0.0
                if deep["all_dm_uids"] > 0:
                    retention = deep["paid_dm_uids"] / deep["all_dm_uids"]

                subscription_ratio = 0.0
                if deep["sub_count"] > 0:
                    subscription_ratio = deep["paid_dm_uids"] / deep["sub_count"]

                final_results.append({
                    "排名": index + 1,
                    "剧名": d_name,
                    "播放量": item.get("view_count"),
                    "订阅数": deep["sub_count"],
                    "宣发策略": deep["strategy"],
                    "总集数": deep["total_ids"],
                    "付费集数": deep["paid_ids"],
                    "全部集弹幕UID数": deep["all_dm_uids"],
                    "付费集弹幕UID数": deep["paid_dm_uids"],
                    "弹幕留存率": f"{retention:.2%}",
                    "收订比": f"{subscription_ratio:.2%}",
                    "最新更新": item.get("newest"),
                    "剧集ID": d_id,
                })

            except Exception as exc:
                # 单剧失败：记录失败但继续抓后面的剧。
                failed_dramas.append({
                    "排名": index + 1,
                    "剧名": d_name,
                    "剧集ID": d_id,
                    "错误": f"{type(exc).__name__}: {exc}",
                })
                print(f"\n❌ ID {d_id}《{d_name}》处理失败：{type(exc).__name__}")

            pbar.update(1)
            time.sleep(DRAMA_SLEEP)

    # 如果整榜全部失败，不生成“空的成功文件”，避免覆盖历史数据。
    if not final_results:
        raise RuntimeError("Top 50 全部抓取失败，未生成新的 CSV；历史数据不会被覆盖。")

    # 北京时间文件名：一天一份，避免同一天重复运行产生多个快照。
    tz_beijing = timezone(timedelta(hours=8))
    now_beijing = datetime.now(tz_beijing)
    date_str = now_beijing.strftime("%Y%m%d")
    file_name = f"猫耳销量月榜{date_str}.csv"
    output_path = DATA_DIR / file_name

    df = pd.DataFrame(final_results)
    df.to_csv(output_path, index=False, encoding="utf_8_sig")

    # 单独保存失败日志，不影响 Dashboard 数据。
    if failed_dramas:
        fail_path = LOG_DIR / f"猫耳销量月榜{date_str}_失败记录.csv"
        pd.DataFrame(failed_dramas).to_csv(fail_path, index=False, encoding="utf_8_sig")
        print(f"⚠️ 有 {len(failed_dramas)} 部剧失败，失败记录：{fail_path.name}")

    print("\n" + "=" * 72)
    print("✅ 月榜抓取完成")
    print(f"📄 数据：{output_path}")
    print(f"📊 成功：{len(final_results)} / {len(rank_data)}")
    print(f"❌ 失败：{len(failed_dramas)} / {len(rank_data)}")
    print("=" * 72)

    return output_path


if __name__ == "__main__":
    main()
