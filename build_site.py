
# -*- coding: utf-8 -*-

"""
============================================================
猫耳三榜静态网页生成器
============================================================

目录结构：

data/
└── raw/
    ├── 猫耳销量月榜YYYYMMDD.csv
    ├── 猫耳人气月榜YYYYMMDD.csv
    └── 猫耳新品日榜YYYYMMDD.csv

运行：

python build-site.py

输出：

site/
└── index.html

说明：
1. 本脚本只负责读取 data/raw/
2. 不负责抓取数据
3. fetch-data.py / fetch-data.yml 负责产生 CSV
4. build-site.yml 负责调用本脚本
5. 网页为纯静态 HTML，可直接部署 GitHub Pages

============================================================
"""

import os
import re
import json
import math
import html
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import numpy as np


# ============================================================
# 1. 路径
# ============================================================

ROOT = Path(__file__).resolve().parent

RAW_DIR = ROOT / "data" / "raw"
SITE_DIR = ROOT / "site"

RAW_DIR.mkdir(parents=True, exist_ok=True)
SITE_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# 2. 榜单配置
# ============================================================

RANK_CONFIG = {
    "sales": {
        "name": "猫耳销量月榜",
        "short_name": "销量月榜",
        "prefix": "猫耳销量月榜",
        "top_n": 50,
        "description": "Top 50 · 播放 / 订阅 / 弹幕 UID 深度分析",
        "has_danmu": True,
    },

    "popularity": {
        "name": "猫耳人气月榜",
        "short_name": "人气月榜",
        "prefix": "猫耳人气月榜",
        "top_n": 100,
        "description": "Top 100 · 播放量 / 订阅数 / 排名趋势",
        "has_danmu": False,
    },

    "new": {
        "name": "猫耳新品日榜",
        "short_name": "新品日榜",
        "prefix": "猫耳新品日榜",
        "top_n": 30,
        "description": "Top 30 · 播放量 / 订阅数 / 新品表现",
        "has_danmu": False,
    },
}


# ============================================================
# 3. 基础工具
# ============================================================

def safe_int(value):
    """
    安全转换整数。
    """
    if pd.isna(value):
        return None

    try:
        return int(float(value))
    except Exception:
        return None


def safe_float(value):
    """
    安全转换数字。
    """
    if pd.isna(value):
        return None

    try:
        return float(value)
    except Exception:
        return None


def clean_number(value):
    """
    输出给 JS 的数字。
    """
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    try:
        value = float(value)

        if not math.isfinite(value):
            return None

        if value.is_integer():
            return int(value)

        return round(value, 4)

    except Exception:
        return None


def clean_text(value):
    """
    清理文本。
    """
    if pd.isna(value):
        return ""

    return str(value).strip()


# ============================================================
# 4. 从文件名提取日期
# ============================================================

def extract_date_from_filename(filename):
    """
    支持：

    猫耳销量月榜20260821.csv
    猫耳销量月榜_20260821.csv
    猫耳销量月榜20260821_030001.csv
    猫耳销量月榜_2026-08-21.csv
    猫耳销量月榜2026-08-21 030000.csv
    """

    name = Path(filename).stem

    patterns = [
        r"(20\d{2})(\d{2})(\d{2})",
        r"(20\d{2})[-_](\d{2})[-_](\d{2})",
    ]

    for pattern in patterns:

        match = re.search(pattern, name)

        if not match:
            continue

        try:

            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3))

            return datetime(
                year,
                month,
                day
            ).date()

        except Exception:
            pass

    return None


# ============================================================
# 5. 文件版本时间
# ============================================================

def extract_file_datetime(path):
    """
    同一天存在多个版本时：

    优先识别文件名里的时间；
    如果没有，则使用文件修改时间。
    """

    name = path.stem

    # YYYYMMDD_HHMMSS
    patterns = [
        r"20\d{6}[_-](\d{2})(\d{2})(\d{2})",
        r"20\d{2}[-_]\d{2}[-_]\d{2}[_-](\d{2})(\d{2})(\d{2})",
    ]

    for pattern in patterns:

        match = re.search(pattern, name)

        if match:

            try:

                # 第二种 pattern 可能只有时间部分
                if len(match.groups()) == 3:

                    hh = int(match.group(1))
                    mm = int(match.group(2))
                    ss = int(match.group(3))

                    return (
                        path.stat().st_mtime,
                        hh * 3600 + mm * 60 + ss
                    )

            except Exception:
                pass

    return (
        path.stat().st_mtime,
        0
    )


# ============================================================
# 6. 找到每天最终版本
# ============================================================

def discover_files():

    result = {
        "sales": {},
        "popularity": {},
        "new": {},
    }

    all_files = sorted(
        RAW_DIR.glob("*.csv")
    )

    print()
    print("=" * 70)
    print("扫描 data/raw/")
    print("=" * 70)

    print(
        f"发现 CSV：{len(all_files)} 个"
    )

    for path in all_files:

        filename = path.name

        file_date = extract_date_from_filename(
            filename
        )

        if file_date is None:
            continue

        rank_type = None

        for key, config in RANK_CONFIG.items():

            if filename.startswith(
                config["prefix"]
            ):

                rank_type = key
                break

        if rank_type is None:
            continue

        version_time = extract_file_datetime(
            path
        )

        current = result[rank_type].get(
            file_date
        )

        if (
            current is None
            or version_time > current[1]
        ):

            result[rank_type][file_date] = (
                path,
                version_time
            )

    for rank_type in result:

        print(
            f"{RANK_CONFIG[rank_type]['name']}："
            f"{len(result[rank_type])} 天"
        )

    return result


# ============================================================
# 7. 自动识别字段
# ============================================================

def find_column(df, candidates):

    normalized = {
        str(c).strip().lower(): c
        for c in df.columns
    }

    for candidate in candidates:

        key = candidate.strip().lower()

        if key in normalized:
            return normalized[key]

    # 模糊匹配
    for col in df.columns:

        col_str = str(col).strip().lower()

        for candidate in candidates:

            if candidate.lower() in col_str:
                return col

    return None


# ============================================================
# 8. 标准化 CSV
# ============================================================

def normalize_dataframe(
    df,
    rank_type,
    file_date
):

    df = df.copy()

    # 去掉 Unnamed 列
    df = df.loc[
        :,
        [
            c
            for c in df.columns
            if not str(c).startswith("Unnamed")
        ]
    ]

    # --------------------------------------------------------
    # 字段识别
    # --------------------------------------------------------

    rank_col = find_column(
        df,
        [
            "排名",
            "名次",
            "rank",
        ]
    )

    drama_col = find_column(
        df,
        [
            "剧名",
            "作品名",
            "名称",
            "title",
        ]
    )

    views_col = find_column(
        df,
        [
            "播放量",
            "播放数",
            "views",
        ]
    )

    subs_col = find_column(
        df,
        [
            "订阅数",
            "订阅人数",
            "追剧人数",
            "subscriptions",
        ]
    )

    total_uid_col = find_column(
        df,
        [
            "全部集弹幕UID数",
            "全部集弹幕UID",
            "全部ID",
            "总弹幕UID数",
            "弹幕UID数",
        ]
    )

    paid_uid_col = find_column(
        df,
        [
            "付费集弹幕UID数",
            "付费集弹幕UID",
            "付费ID",
            "付费弹幕UID数",
        ]
    )

    total_eps_col = find_column(
        df,
        [
            "总集数",
            "总集",
        ]
    )

    paid_eps_col = find_column(
        df,
        [
            "付费集数",
            "付费集",
        ]
    )

    drama_id_col = find_column(
        df,
        [
            "剧ID",
            "drama_id",
            "id",
        ]
    )

    # --------------------------------------------------------
    # 必要字段
    # --------------------------------------------------------

    if drama_col is None:

        raise ValueError(
            f"{file_date} {rank_type}："
            f"无法识别剧名字段。"
            f"实际字段={list(df.columns)}"
        )

    if rank_col is None:

        raise ValueError(
            f"{file_date} {rank_type}："
            f"无法识别排名字段。"
        )

    # --------------------------------------------------------
    # 构造标准表
    # --------------------------------------------------------

    out = pd.DataFrame()

    out["日期"] = pd.to_datetime(
        file_date
    ).strftime("%Y-%m-%d")

    out["排名"] = pd.to_numeric(
        df[rank_col],
        errors="coerce"
    )

    out["剧名"] = (
        df[drama_col]
        .astype(str)
        .str.strip()
    )

    # 数值字段
    if views_col:

        out["播放量"] = pd.to_numeric(
            df[views_col],
            errors="coerce"
        )

    else:

        out["播放量"] = np.nan

    if subs_col:

        out["订阅数"] = pd.to_numeric(
            df[subs_col],
            errors="coerce"
        )

    else:

        out["订阅数"] = np.nan

    if total_uid_col:

        out["全部集弹幕UID数"] = pd.to_numeric(
            df[total_uid_col],
            errors="coerce"
        )

    else:

        out["全部集弹幕UID数"] = np.nan

    if paid_uid_col:

        out["付费集弹幕UID数"] = pd.to_numeric(
            df[paid_uid_col],
            errors="coerce"
        )

    else:

        out["付费集弹幕UID数"] = np.nan

    if total_eps_col:

        out["总集数"] = pd.to_numeric(
            df[total_eps_col],
            errors="coerce"
        )

    else:

        out["总集数"] = np.nan

    if paid_eps_col:

        out["付费集数"] = pd.to_numeric(
            df[paid_eps_col],
            errors="coerce"
        )

    else:

        out["付费集数"] = np.nan

    if drama_id_col:

        out["剧ID"] = (
            df[drama_id_col]
            .astype(str)
            .str.strip()
        )

    else:

        out["剧ID"] = ""

    # --------------------------------------------------------
    # 删除空剧名
    # --------------------------------------------------------

    out = out[
        (out["剧名"] != "")
        &
        (out["剧名"].str.lower() != "nan")
    ]

    # --------------------------------------------------------
    # Top N
    # --------------------------------------------------------

    top_n = RANK_CONFIG[
        rank_type
    ]["top_n"]

    out = out[
        out["排名"].notna()
    ]

    out = out[
        out["排名"] <= top_n
    ]

    # --------------------------------------------------------
    # 排序
    # --------------------------------------------------------

    out = out.sort_values(
        ["排名", "剧名"]
    )

    return out.reset_index(
        drop=True
    )


# ============================================================
# 9. 读取一个榜单
# ============================================================

def load_rank_data(
    rank_type,
    files_by_date
):

    frames = []

    for file_date in sorted(
        files_by_date.keys()
    ):

        path, _ = files_by_date[
            file_date
        ]

        try:

            df = pd.read_csv(
                path,
                encoding="utf-8-sig"
            )

        except UnicodeDecodeError:

            df = pd.read_csv(
                path,
                encoding="utf-8"
            )

        except Exception as e:

            print(
                f"⚠️ 读取失败：{path.name}"
            )

            print(e)

            continue

        try:

            normalized = normalize_dataframe(
                df,
                rank_type,
                file_date
            )

            frames.append(
                normalized
            )

        except Exception as e:

            print(
                f"⚠️ 处理失败：{path.name}"
            )

            print(e)

    if not frames:

        return pd.DataFrame()

    result = pd.concat(
        frames,
        ignore_index=True
    )

    # 同一天同一剧理论上只保留一条
    result = result.sort_values(
        [
            "日期",
            "排名"
        ]
    )

    result = result.drop_duplicates(
        subset=[
            "日期",
            "剧名"
        ],
        keep="first"
    )

    return result.reset_index(
        drop=True
    )


# ============================================================
# 10. 拼音首字母
# ============================================================

def get_initial(text):

    if not text:
        return "#"

    first = str(text).strip()[0]

    # 英文字母
    if re.match(
        r"[A-Za-z]",
        first
    ):

        return first.upper()

    # 数字
    if first.isdigit():
        return "#"

    # 常见中文拼音首字母
    pinyin_map = {
        "阿": "A",
        "八": "B",
        "擦": "C",
        "搭": "D",
        "蛾": "E",
        "发": "F",
        "噶": "G",
        "哈": "H",
        "击": "J",
        "喀": "K",
        "垃": "L",
        "妈": "M",
        "拿": "N",
        "哦": "O",
        "趴": "P",
        "期": "Q",
        "然": "R",
        "撒": "S",
        "塌": "T",
        "挖": "W",
        "昔": "X",
        "压": "Y",
        "匝": "Z",
    }

    for key, letter in pinyin_map.items():

        if first >= key:
            result = letter

        else:
            break

    try:

        # 如果安装了 pypinyin，使用真正拼音
        from pypinyin import lazy_pinyin

        p = lazy_pinyin(first)

        if p:

            return p[0][0].upper()

    except Exception:
        pass

    return "#"


# ============================================================
# 11. 榜单状态
# ============================================================

def calculate_rank_status(
    group,
    start_date,
    end_date
):

    dates = sorted(
        group["日期"].unique()
    )

    if not dates:
        return "闪现"

    first = dates[0]
    last = dates[-1]

    if (
        first == start_date
        and last == end_date
    ):

        return "稳定在榜"

    if (
        first != start_date
        and last == end_date
    ):

        return "新晋榜单"

    if (
        first == start_date
        and last != end_date
    ):

        return "掉榜"

    return "闪现"


# ============================================================
# 12. 趋势状态
# ============================================================

def calculate_trend(
    group
):

    ranks = (
        group
        .sort_values("日期")["排名"]
        .dropna()
        .tolist()
    )

    if len(ranks) <= 1:
        return "波动"

    changes = []

    for i in range(1, len(ranks)):

        changes.append(
            ranks[i] - ranks[i - 1]
        )

    positive = sum(
        x > 0
        for x in changes
    )

    negative = sum(
        x < 0
        for x in changes
    )

    if negative > 0 and positive == 0:
        return "上升"

    if positive > 0 and negative == 0:
        return "下降"

    first = ranks[0]
    last = ranks[-1]

    if abs(last - first) <= 2:
        return "波动"

    if last < first:
        return "上升"

    if last > first:
        return "下降"

    return "波动"


# ============================================================
# 13. 构造首页 summary
# ============================================================

def build_summary(
    df,
    start_date,
    end_date
):

    rows = []

    if df.empty:
        return rows

    for drama, group in df.groupby(
        "剧名"
    ):

        group = group.sort_values(
            "日期"
        )

        rows.append({

            "剧名": drama,

            "首字母": get_initial(
                drama
            ),

            "在榜天数": int(
                len(group)
            ),

            "最高排名": safe_int(
                group["排名"].min()
            ),

            "最低排名": safe_int(
                group["排名"].max()
            ),

            "首次上榜": str(
                group["日期"].iloc[0]
            ),

            "最后在榜": str(
                group["日期"].iloc[-1]
            ),

            "榜单状态": calculate_rank_status(
                group,
                start_date,
                end_date
            ),

            "趋势状态": calculate_trend(
                group
            ),

        })

    return rows


# ============================================================
# 14. 单剧数据
# ============================================================

def build_drama_data(
    df,
    drama
):

    group = (
        df[
            df["剧名"] == drama
        ]
        .sort_values("日期")
        .copy()
    )

    rows = []

    for _, row in group.iterrows():

        item = {
            "日期": str(row["日期"]),
            "排名": safe_int(row["排名"]),
            "播放量": clean_number(row["播放量"]),
            "订阅数": clean_number(row["订阅数"]),
            "全部集弹幕UID数": clean_number(
                row["全部集弹幕UID数"]
            ),
            "付费集弹幕UID数": clean_number(
                row["付费集弹幕UID数"]
            ),
            "总集数": clean_number(
                row["总集数"]
            ),
            "付费集数": clean_number(
                row["付费集数"]
            ),
            "剧ID": clean_text(
                row["剧ID"]
            ),
        }

        rows.append(item)

    return rows


# ============================================================
# 15. 所有数据转 JSON
# ============================================================

def dataframe_records(df):

    records = []

    if df.empty:
        return records

    for _, row in df.iterrows():

        records.append({

            "日期": str(row["日期"]),

            "剧名": clean_text(
                row["剧名"]
            ),

            "排名": safe_int(
                row["排名"]
            ),

            "播放量": clean_number(
                row["播放量"]
            ),

            "订阅数": clean_number(
                row["订阅数"]
            ),

            "全部集弹幕UID数": clean_number(
                row["全部集弹幕UID数"]
            ),

            "付费集弹幕UID数": clean_number(
                row["付费集弹幕UID数"]
            ),

            "总集数": clean_number(
                row["总集数"]
            ),

            "付费集数": clean_number(
                row["付费集数"]
            ),

            "剧ID": clean_text(
                row["剧ID"]
            ),

        })

    return records


# ============================================================
# 16. HTML CSS
# ============================================================

HTML_CSS = r"""
<style>

:root {
    --bg: #f6f7fb;
    --card: #ffffff;
    --text: #1f2937;
    --muted: #6b7280;
    --border: #e5e7eb;
    --primary: #6366f1;
    --primary-dark: #4f46e5;
    --green: #10b981;
    --red: #ef4444;
    --orange: #f59e0b;
    --blue: #3b82f6;
    --shadow: 0 8px 30px rgba(0,0,0,.06);
}

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        "PingFang SC",
        "Hiragino Sans GB",
        "Microsoft YaHei",
        sans-serif;
}

.container {
    max-width: 1500px;
    margin: 0 auto;
    padding: 24px;
}

.header {
    background:
        linear-gradient(
            135deg,
            #667eea,
            #764ba2
        );
    color: white;
    border-radius: 20px;
    padding: 32px;
    margin-bottom: 20px;
    box-shadow: var(--shadow);
}

.header h1 {
    margin: 0 0 8px 0;
    font-size: 30px;
}

.header p {
    margin: 0;
    opacity: .9;
}

.rank-tabs {
    display: flex;
    gap: 10px;
    margin-top: 22px;
    flex-wrap: wrap;
}

.rank-tab {
    border: 1px solid rgba(255,255,255,.35);
    background: rgba(255,255,255,.12);
    color: white;
    border-radius: 12px;
    padding: 10px 18px;
    cursor: pointer;
    transition: .2s;
}

.rank-tab:hover {
    background: rgba(255,255,255,.22);
}

.rank-tab.active {
    background: white;
    color: #4f46e5;
}

.panel {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 18px;
    padding: 20px;
    margin-bottom: 20px;
    box-shadow: var(--shadow);
}

.filters {
    display: grid;
    grid-template-columns:
        1fr
        1fr
        1fr
        auto;
    gap: 14px;
    align-items: end;
}

.filter-item label {
    display: block;
    font-size: 13px;
    color: var(--muted);
    margin-bottom: 7px;
}

input,
select,
button {
    font: inherit;
}

input[type="date"],
select {
    width: 100%;
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 10px 12px;
    background: white;
}

.primary-button {
    border: 0;
    border-radius: 10px;
    padding: 10px 18px;
    background: var(--primary);
    color: white;
    cursor: pointer;
}

.primary-button:hover {
    background: var(--primary-dark);
}

.stats {
    display: grid;
    grid-template-columns:
        repeat(4, 1fr);
    gap: 14px;
    margin-bottom: 20px;
}

.stat-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 18px;
    box-shadow: var(--shadow);
}

.stat-label {
    font-size: 13px;
    color: var(--muted);
}

.stat-value {
    margin-top: 6px;
    font-size: 28px;
    font-weight: 700;
}

.chart-grid {
    display: grid;
    grid-template-columns:
        repeat(2, 1fr);
    gap: 18px;
}

.chart-card {
    background: white;
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 18px;
}

.chart-title {
    font-weight: 700;
    margin-bottom: 12px;
}

.chart {
    width: 100%;
    height: 330px;
}

.table-wrap {
    overflow-x: auto;
}

table {
    width: 100%;
    border-collapse: collapse;
    min-width: 950px;
}

th,
td {
    border-bottom: 1px solid var(--border);
    padding: 12px 10px;
    text-align: left;
    white-space: nowrap;
}

th {
    color: var(--muted);
    font-size: 13px;
    background: #fafafa;
}

tr:hover td {
    background: #fafafa;
}

.drama-link {
    color: var(--primary-dark);
    font-weight: 600;
    cursor: pointer;
}

.badge {
    display: inline-block;
    padding: 4px 9px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
}

.badge-stable {
    background: #ecfdf5;
    color: #047857;
}

.badge-new {
    background: #eff6ff;
    color: #1d4ed8;
}

.badge-drop {
    background: #fff7ed;
    color: #c2410c;
}

.badge-flash {
    background: #f3f4f6;
    color: #4b5563;
}

.badge-up {
    background: #ecfdf5;
    color: #047857;
}

.badge-down {
    background: #fef2f2;
    color: #b91c1c;
}

.badge-wave {
    background: #fffbeb;
    color: #a16207;
}

.back-button {
    border: 1px solid var(--border);
    background: white;
    border-radius: 10px;
    padding: 9px 15px;
    cursor: pointer;
    margin-bottom: 16px;
}

.drama-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 15px;
    margin-bottom: 15px;
}

.drama-title {
    font-size: 26px;
    font-weight: 750;
}

.metric-grid {
    display: grid;
    grid-template-columns:
        repeat(4, 1fr);
    gap: 12px;
    margin-bottom: 18px;
}

.metric {
    background: #f9fafb;
    border-radius: 12px;
    padding: 14px;
}

.metric-label {
    color: var(--muted);
    font-size: 12px;
}

.metric-value {
    font-size: 20px;
    font-weight: 700;
    margin-top: 5px;
}

.footer {
    text-align: center;
    color: var(--muted);
    padding: 30px 0 10px;
    font-size: 13px;
}

.hidden {
    display: none !important;
}

.small-note {
    color: var(--muted);
    font-size: 13px;
}

@media (max-width: 900px) {

    .filters {
        grid-template-columns:
            1fr 1fr;
    }

    .stats {
        grid-template-columns:
            repeat(2, 1fr);
    }

    .chart-grid {
        grid-template-columns:
            1fr;
    }

    .metric-grid {
        grid-template-columns:
            repeat(2, 1fr);
    }
}

@media (max-width: 600px) {

    .container {
        padding: 12px;
    }

    .header {
        padding: 22px;
    }

    .header h1 {
        font-size: 23px;
    }

    .filters {
        grid-template-columns:
            1fr;
    }

    .stats {
        grid-template-columns:
            1fr 1fr;
    }

    .metric-grid {
        grid-template-columns:
            1fr 1fr;
    }
}

</style>
"""


# ============================================================
# 17. Chart.js
# ============================================================

CHART_JS = """
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
"""


# ============================================================
# 18. JS
# ============================================================

HTML_JS = r"""
<script>

const ALL_DATA = __ALL_DATA__;
const SUMMARY_DATA = __SUMMARY_DATA__;
const CONFIG = __CONFIG__;
const DRAMA_DATA = __DRAMA_DATA__;

let currentRank = "sales";
let charts = [];


// ========================================================
// 格式化数字
// ========================================================

function fmt(value) {

    if (
        value === null ||
        value === undefined ||
        Number.isNaN(value)
    ) {
        return "-";
    }

    return Number(value).toLocaleString(
        "zh-CN"
    );
}


// ========================================================
// 标签
// ========================================================

function badge(text) {

    let cls = "badge";

    if (text === "稳定在榜")
        cls += " badge-stable";

    else if (text === "新晋榜单")
        cls += " badge-new";

    else if (text === "掉榜")
        cls += " badge-drop";

    else if (text === "闪现")
        cls += " badge-flash";

    else if (text === "上升")
        cls += " badge-up";

    else if (text === "下降")
        cls += " badge-down";

    else if (text === "波动")
        cls += " badge-wave";

    return `<span class="${cls}">${text}</span>`;
}


// ========================================================
// 初始化
// ========================================================

function init() {

    const dates = [
        ...new Set(
            ALL_DATA[currentRank]
                .map(x => x.日期)
        )
    ].sort();

    if (!dates.length)
        return;

    const end = dates[dates.length - 1];

    const startIndex = Math.max(
        0,
        dates.length - 30
    );

    const start = dates[startIndex];

    document.getElementById(
        "startDate"
    ).value = start;

    document.getElementById(
        "endDate"
    ).value = end;

    document.getElementById(
        "startDate"
    ).min = dates[0];

    document.getElementById(
        "startDate"
    ).max = end;

    document.getElementById(
        "endDate"
    ).min = dates[0];

    document.getElementById(
        "endDate"
    ).max = end;

    renderHome();
}


// ========================================================
// 切换榜单
// ========================================================

function switchRank(rank) {

    currentRank = rank;

    document
        .querySelectorAll(".rank-tab")
        .forEach(btn => {

            btn.classList.toggle(
                "active",
                btn.dataset.rank === rank
            );

        });

    document.getElementById(
        "homeView"
    ).classList.remove("hidden");

    document.getElementById(
        "dramaView"
    ).classList.add("hidden");

    document.getElementById(
        "pageTitle"
    ).textContent =
        CONFIG[rank].name;

    document.getElementById(
        "pageDescription"
    ).textContent =
        CONFIG[rank].description;

    const dates = [
        ...new Set(
            ALL_DATA[rank]
                .map(x => x.日期)
        )
    ].sort();

    if (!dates.length)
        return;

    const end = dates[dates.length - 1];

    const start = dates[
        Math.max(
            0,
            dates.length - 30
        )
    ];

    document.getElementById(
        "startDate"
    ).value = start;

    document.getElementById(
        "endDate"
    ).value = end;

    renderHome();
}


// ========================================================
// 获取日期范围
// ========================================================

function getRangeData() {

    const start =
        document.getElementById(
            "startDate"
        ).value;

    const end =
        document.getElementById(
            "endDate"
        ).value;

    return ALL_DATA[currentRank].filter(
        row =>
            row.日期 >= start &&
            row.日期 <= end
    );
}


// ========================================================
// 排序
// ========================================================

function sortSummary(rows) {

    const sort =
        document.getElementById(
            "sortSelect"
        ).value;

    rows.sort((a, b) => {

        if (sort === "days")
            return b.在榜天数 - a.在榜天数;

        if (sort === "best")
            return a.最高排名 - b.最高排名;

        if (sort === "initial") {

            const x =
                a.首字母.localeCompare(
                    b.首字母,
                    "zh"
                );

            if (x !== 0)
                return x;

            return a.剧名.localeCompare(
                b.剧名,
                "zh"
            );
        }

        return 0;
    });

    return rows;
}


// ========================================================
// 首页
// ========================================================

function renderHome() {

    clearCharts();

    const data = getRangeData();

    const start =
        document.getElementById(
            "startDate"
        ).value;

    const end =
        document.getElementById(
            "endDate"
        ).value;

    const dramas = [
        ...new Set(
            data.map(x => x.剧名)
        )
    ];

    document.getElementById(
        "totalDramas"
    ).textContent =
        dramas.length;

    const summary = [];

    dramas.forEach(drama => {

        const rows = data.filter(
            x => x.剧名 === drama
        );

        const ranks = rows
            .map(x => x.排名)
            .filter(x => x !== null);

        const dates = rows
            .map(x => x.日期)
            .sort();

        summary.push({

            剧名: drama,

            首字母:
                getInitialJS(drama),

            在榜天数:
                rows.length,

            最高排名:
                Math.min(...ranks),

            最低排名:
                Math.max(...ranks),

            首次上榜:
                dates[0],

            最后在榜:
                dates[dates.length - 1],

            榜单状态:
                calculateStatusJS(
                    dates,
                    start,
                    end
                ),

            趋势状态:
                calculateTrendJS(
                    ranks
                )
        });

    });

    sortSummary(summary);

    document.getElementById(
        "stableCount"
    ).textContent =
        summary.filter(
            x => x.榜单状态 === "稳定在榜"
        ).length;

    document.getElementById(
        "newCount"
    ).textContent =
        summary.filter(
            x => x.榜单状态 === "新晋榜单"
        ).length;

    document.getElementById(
        "dropFlashCount"
    ).textContent =
        summary.filter(
            x =>
                x.榜单状态 === "掉榜" ||
                x.榜单状态 === "闪现"
        ).length;

    document.getElementById(
        "rangeText"
    ).textContent =
        `${start} → ${end}`;

    const tbody =
        document.getElementById(
            "summaryTable"
        );

    tbody.innerHTML = "";

    summary.forEach((row, index) => {

        const tr =
            document.createElement("tr");

        tr.innerHTML = `

            <td>${index + 1}</td>

            <td>
                <span
                    class="drama-link"
                    onclick="openDrama('${escapeJS(row.剧名)}')"
                >
                    ${escapeHTML(row.剧名)}
                </span>
            </td>

            <td>${escapeHTML(row.首字母)}</td>

            <td>${row.在榜天数}</td>

            <td>${row.最高排名}</td>

            <td>${row.最低排名}</td>

            <td>${row.首次上榜}</td>

            <td>${row.最后在榜}</td>

            <td>${badge(row.榜单状态)}</td>

            <td>${badge(row.趋势状态)}</td>

        `;

        tbody.appendChild(tr);

    });
}


// ========================================================
// 拼音首字母
// ========================================================

function getInitialJS(text) {

    if (!text)
        return "#";

    const c = text.trim().charAt(0);

    if (
        /[A-Za-z]/.test(c)
    )
        return c.toUpperCase();

    if (
        /[0-9]/.test(c)
    )
        return "#";

    return c;
}


// ========================================================
// 榜单状态
// ========================================================

function calculateStatusJS(
    dates,
    start,
    end
) {

    if (!dates.length)
        return "闪现";

    const first = dates[0];

    const last =
        dates[dates.length - 1];

    if (
        first === start &&
        last === end
    )
        return "稳定在榜";

    if (
        first !== start &&
        last === end
    )
        return "新晋榜单";

    if (
        first === start &&
        last !== end
    )
        return "掉榜";

    return "闪现";
}


// ========================================================
// 趋势
// ========================================================

function calculateTrendJS(ranks) {

    if (ranks.length <= 1)
        return "波动";

    let positive = 0;
    let negative = 0;

    for (
        let i = 1;
        i < ranks.length;
        i++
    ) {

        const diff =
            ranks[i] -
            ranks[i - 1];

        if (diff > 0)
            positive++;

        if (diff < 0)
            negative++;
    }

    if (
        negative > 0 &&
        positive === 0
    )
        return "上升";

    if (
        positive > 0 &&
        negative === 0
    )
        return "下降";

    const first = ranks[0];

    const last =
        ranks[ranks.length - 1];

    if (
        Math.abs(last - first) <= 2
    )
        return "波动";

    if (last < first)
        return "上升";

    if (last > first)
        return "下降";

    return "波动";
}


// ========================================================
// 单剧页面
// ========================================================

function openDrama(drama) {

    document.getElementById(
        "homeView"
    ).classList.add("hidden");

    document.getElementById(
        "dramaView"
    ).classList.remove("hidden");

    document.getElementById(
        "dramaTitle"
    ).textContent = drama;

    document.getElementById(
        "dramaSubtitle"
    ).textContent =
        CONFIG[currentRank].name;

    renderDrama(drama);

    window.scrollTo({
        top: 0,
        behavior: "smooth"
    });
}


function closeDrama() {

    clearCharts();

    document.getElementById(
        "dramaView"
    ).classList.add("hidden");

    document.getElementById(
        "homeView"
    ).classList.remove("hidden");
}


// ========================================================
// 单剧图表
// ========================================================

function renderDrama(drama) {

    clearCharts();

    const rows =
        DRAMA_DATA[currentRank][drama]
        || [];

    if (!rows.length)
        return;

    const labels =
        rows.map(x => x.日期);

    const values = {
        ranking:
            rows.map(x => x.排名),

        views:
            rows.map(x => x.播放量),

        subs:
            rows.map(x => x.订阅数),

        allUid:
            rows.map(
                x => x.全部集弹幕UID数
            ),

        paidUid:
            rows.map(
                x => x.付费集弹幕UID数
            ),
    };

    document.getElementById(
        "dramaMeta"
    ).innerHTML = `

        <div class="metric">
            <div class="metric-label">
                在榜天数
            </div>
            <div class="metric-value">
                ${rows.length}
            </div>
        </div>

        <div class="metric">
            <div class="metric-label">
                最高排名
            </div>
            <div class="metric-value">
                ${fmt(
                    Math.min(
                        ...values.ranking
                            .filter(x => x !== null)
                    )
                )}
            </div>
        </div>

        <div class="metric">
            <div class="metric-label">
                最新播放量
            </div>
            <div class="metric-value">
                ${fmt(
                    lastValid(
                        values.views
                    )
                )}
            </div>
        </div>

        <div class="metric">
            <div class="metric-label">
                最新订阅数
            </div>
            <div class="metric-value">
                ${fmt(
                    lastValid(
                        values.subs
                    )
                )}
            </div>
        </div>
    `;

    makeLineChart(
        "rankingChart",
        "排名",
        labels,
        values.ranking,
        true
    );

    makeLineChart(
        "viewsChart",
        "播放量",
        labels,
        values.views
    );

    makeLineChart(
        "subsChart",
        "订阅数",
        labels,
        values.subs
    );

    if (
        CONFIG[currentRank].has_danmu
    ) {

        makeLineChart(
            "allUidChart",
            "全部集弹幕 UID",
            labels,
            values.allUid
        );

        makeLineChart(
            "paidUidChart",
            "付费集弹幕 UID",
            labels,
            values.paidUid
        );

    }

    renderDramaTable(rows);
}


// ========================================================
// Chart
// ========================================================

function makeLineChart(
    canvasId,
    label,
    labels,
    data,
    reverse = false
) {

    const canvas =
        document.getElementById(
            canvasId
        );

    if (!canvas)
        return;

    const chart =
        new Chart(
            canvas,
            {
                type: "line",

                data: {

                    labels: labels,

                    datasets: [{
                        label: label,

                        data: data,

                        borderWidth: 2,

                        pointRadius: 2,

                        tension: .25,

                        fill: false,
                    }]
                },

                options: {

                    responsive: true,

                    maintainAspectRatio: false,

                    interaction: {
                        mode: "index",
                        intersect: false
                    },

                    plugins: {

                        legend: {
                            display: true
                        },

                        tooltip: {

                            callbacks: {

                                label:
                                    function(context) {

                                        return (
                                            label +
                                            ": " +
                                            fmt(
                                                context.raw
                                            )
                                        );
                                    }
                            }
                        }
                    },

                    scales: {

                        y: {

                            reverse: reverse,

                            ticks: {

                                callback:
                                    function(value) {
                                        return fmt(value);
                                    }
                            }
                        }

                    }
                }
            }
        );

    charts.push(chart);
}


// ========================================================
// 表格
// ========================================================

function renderDramaTable(rows) {

    const tbody =
        document.getElementById(
            "dramaTable"
        );

    tbody.innerHTML = "";

    rows.forEach(row => {

        const tr =
            document.createElement("tr");

        tr.innerHTML = `

            <td>${row.日期}</td>

            <td>${fmt(row.排名)}</td>

            <td>${fmt(row.播放量)}</td>

            <td>${fmt(row.订阅数)}</td>

            ${
                CONFIG[currentRank].has_danmu
                ? `
                    <td>
                        ${fmt(
                            row.全部集弹幕UID数
                        )}
                    </td>

                    <td>
                        ${fmt(
                            row.付费集弹幕UID数
                        )}
                    </td>
                `
                : ""
            }

            <td>${fmt(row.总集数)}</td>

            <td>${fmt(row.付费集数)}</td>

        `;

        tbody.appendChild(tr);

    });
}


// ========================================================
// 清理图表
// ========================================================

function clearCharts() {

    charts.forEach(
        chart => chart.destroy()
    );

    charts = [];
}


// ========================================================
// 辅助
// ========================================================

function lastValid(arr) {

    for (
        let i = arr.length - 1;
        i >= 0;
        i--
    ) {

        if (
            arr[i] !== null &&
            arr[i] !== undefined
        )
            return arr[i];

    }

    return null;
}


function escapeHTML(text) {

    return String(text)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


function escapeJS(text) {

    return String(text)
        .replaceAll("\\", "\\\\")
        .replaceAll("'", "\\'")
        .replaceAll("\n", "\\n")
        .replaceAll("\r", "\\r");
}


init();

</script>
"""


# ============================================================
# 19. 生成 HTML
# ============================================================

def generate_html(
    datasets,
    summaries,
    drama_data,
    metadata
):

    all_data_json = json.dumps(
        datasets,
        ensure_ascii=False,
        separators=(",", ":")
    )

    summary_json = json.dumps(
        summaries,
        ensure_ascii=False,
        separators=(",", ":")
    )

    config_json = json.dumps(
        RANK_CONFIG,
        ensure_ascii=False,
        separators=(",", ":")
    )

    drama_json = json.dumps(
        drama_data,
        ensure_ascii=False,
        separators=(",", ":")
    )

    js = HTML_JS

    js = js.replace(
        "__ALL_DATA__",
        all_data_json
    )

    js = js.replace(
        "__SUMMARY_DATA__",
        summary_json
    )

    js = js.replace(
        "__CONFIG__",
        config_json
    )

    js = js.replace(
        "__DRAMA_DATA__",
        drama_json
    )

    # --------------------------------------------------------
    # 动态表头
    # --------------------------------------------------------

    sales_columns = ""

    if RANK_CONFIG["sales"]["has_danmu"]:
        sales_columns = """
            <th>全部集弹幕 UID</th>
            <th>付费集弹幕 UID</th>
        """

    # --------------------------------------------------------
    # HTML
    # --------------------------------------------------------

    title = (
        "猫耳三榜数据分析"
    )

    generated_at = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    html_doc = f"""
<!DOCTYPE html>

<html lang="zh-CN">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>
{title}
</title>

{CHART_JS}

{HTML_CSS}

</head>


<body>


<div class="container">


<!-- ================================================== -->
<!-- Header -->
<!-- ================================================== -->

<div class="header">

<h1 id="pageTitle">
猫耳销量月榜
</h1>

<p id="pageDescription">
销量月榜 Top 50 · 播放 / 订阅 / 弹幕 UID 深度分析
</p>


<div class="rank-tabs">

<button
    class="rank-tab active"
    data-rank="sales"
    onclick="switchRank('sales')"
>
销量月榜
</button>

<button
    class="rank-tab"
    data-rank="popularity"
    onclick="switchRank('popularity')"
>
人气月榜
</button>

<button
    class="rank-tab"
    data-rank="new"
    onclick="switchRank('new')"
>
新品日榜
</button>

</div>

</div>


<!-- ================================================== -->
<!-- 首页 -->
<!-- ================================================== -->

<div id="homeView">


<div class="panel">

<div class="filters">


<div class="filter-item">

<label>
开始日期
</label>

<input
    id="startDate"
    type="date"
>

</div>


<div class="filter-item">

<label>
结束日期
</label>

<input
    id="endDate"
    type="date"
>

</div>


<div class="filter-item">

<label>
排序方式
</label>

<select
    id="sortSelect"
    onchange="renderHome()"
>

<option value="days">
在榜天数
</option>

<option value="best">
最高排名
</option>

<option value="initial">
剧名首字母
</option>

</select>

</div>


<div class="filter-item">

<button
    class="primary-button"
    onclick="renderHome()"
>
应用筛选
</button>

</div>


</div>


<div class="small-note"
     style="margin-top:12px;"
     id="rangeText">
</div>

</div>


<!-- ================================================== -->
<!-- 统计 -->
<!-- ================================================== -->

<div class="stats">


<div class="stat-card">

<div class="stat-label">
剧目数量
</div>

<div
    class="stat-value"
    id="totalDramas"
>
-
</div>

</div>


<div class="stat-card">

<div class="stat-label">
稳定在榜
</div>

<div
    class="stat-value"
    id="stableCount"
>
-
</div>

</div>


<div class="stat-card">

<div class="stat-label">
新晋榜单
</div>

<div
    class="stat-value"
    id="newCount"
>
-
</div>

</div>


<div class="stat-card">

<div class="stat-label">
掉榜 / 闪现
</div>

<div
    class="stat-value"
    id="dropFlashCount"
>
-
</div>

</div>


</div>


<!-- ================================================== -->
<!-- 榜单 -->
<!-- ================================================== -->

<div class="panel">

<div style="
    display:flex;
    justify-content:space-between;
    align-items:center;
    margin-bottom:15px;
">

<h2 style="margin:0;">
剧目榜单
</h2>

<div
    class="small-note"
    id="rangeText2"
>
</div>

</div>


<div class="table-wrap">

<table>

<thead>

<tr>

<th>#</th>

<th>剧名</th>

<th>首字母</th>

<th>在榜天数</th>

<th>最高排名</th>

<th>最低排名</th>

<th>首次上榜</th>

<th>最后在榜</th>

<th>榜单状态</th>

<th>趋势状态</th>

</tr>

</thead>


<tbody id="summaryTable">
</tbody>


</table>

</div>

</div>


</div>


<!-- ================================================== -->
<!-- 单剧 -->
<!-- ================================================== -->

<div
    id="dramaView"
    class="hidden"
>


<button
    class="back-button"
    onclick="closeDrama()"
>
← 返回榜单
</button>


<div class="panel">


<div class="drama-header">

<div>

<div
    class="drama-title"
    id="dramaTitle"
>
</div>

<div
    class="small-note"
    id="dramaSubtitle"
>
</div>

</div>

</div>


<div
    class="metric-grid"
    id="dramaMeta"
>
</div>


</div>


<!-- 排名 -->

<div class="chart-grid">

<div class="chart-card">

<div class="chart-title">
排名走势
</div>

<div class="chart">
<canvas id="rankingChart"></canvas>
</div>

</div>


<div class="chart-card">

<div class="chart-title">
播放量
</div>

<div class="chart">
<canvas id="viewsChart"></canvas>
</div>

</div>


<div class="chart-card">

<div class="chart-title">
订阅数
</div>

<div class="chart">
<canvas id="subsChart"></canvas>
</div>

</div>


<div
    class="chart-card"
    id="allUidCard"
>

<div class="chart-title">
全部集弹幕 UID
</div>

<div class="chart">
<canvas id="allUidChart"></canvas>
</div>

</div>


<div
    class="chart-card"
    id="paidUidCard"
>

<div class="chart-title">
付费集弹幕 UID
</div>

<div class="chart">
<canvas id="paidUidChart"></canvas>
</div>

</div>

</div>


<!-- ================================================== -->
<!-- 明细 -->
<!-- ================================================== -->

<div class="panel"
     style="margin-top:20px;">

<h2>
每日详细数据
</h2>


<div class="table-wrap">

<table>

<thead>

<tr>

<th>日期</th>

<th>排名</th>

<th>播放量</th>

<th>订阅数</th>

{sales_columns}

<th>总集数</th>

<th>付费集数</th>

</tr>

</thead>


<tbody id="dramaTable">
</tbody>


</table>

</div>

</div>


</div>


<div class="footer">

猫耳三榜数据分析 · 静态网页

<br>

生成时间：
{generated_at}

</div>


</div>


{js}

</body>

</html>
"""

    return html_doc


# ============================================================
# 20. 主流程
# ============================================================

def main():

    print()
    print("=" * 70)
    print("🎙️ 猫耳三榜网页生成器")
    print("=" * 70)

    files_by_rank = discover_files()

    datasets = {}
    summaries = {}
    drama_data = {}
    metadata = {}

    # --------------------------------------------------------
    # 三榜分别处理
    # --------------------------------------------------------

    for rank_type in [
        "sales",
        "popularity",
        "new",
    ]:

        config = RANK_CONFIG[
            rank_type
        ]

        print()
        print(
            "-" * 70
        )

        print(
            f"处理：{config['name']}"
        )

        df = load_rank_data(
            rank_type,
            files_by_rank[rank_type]
        )

        if df.empty:

            print(
                "⚠️ 没有可用数据"
            )

            datasets[rank_type] = []
            summaries[rank_type] = []
            drama_data[rank_type] = {}
            metadata[rank_type] = {
                "first_date": None,
                "last_date": None,
                "days": 0,
                "rows": 0,
                "dramas": 0,
            }

            continue

        # ----------------------------------------------------
        # 日期
        # ----------------------------------------------------

        dates = sorted(
            df["日期"].unique()
        )

        first_date = dates[0]
        last_date = dates[-1]

        # ----------------------------------------------------
        # 数据
        # ----------------------------------------------------

        datasets[
            rank_type
        ] = dataframe_records(df)

        summaries[
            rank_type
        ] = build_summary(
            df,
            first_date,
            last_date
        )

        # ----------------------------------------------------
        # 单剧数据
        # ----------------------------------------------------

        drama_dict = {}

        for drama in sorted(
            df["剧名"].unique()
        ):

            drama_dict[
                drama
            ] = build_drama_data(
                df,
                drama
            )

        drama_data[
            rank_type
        ] = drama_dict

        metadata[
            rank_type
        ] = {

            "first_date":
                first_date,

            "last_date":
                last_date,

            "days":
                len(dates),

            "rows":
                len(df),

            "dramas":
                df["剧名"]
                .nunique(),

        }

        print(
            f"日期：{first_date} → {last_date}"
        )

        print(
            f"数据行数：{len(df):,}"
        )

        print(
            f"剧目数：{df['剧名'].nunique():,}"
        )

    # ========================================================
    # 生成网页
    # ========================================================

    html_doc = generate_html(
        datasets,
        summaries,
        drama_data,
        metadata
    )

    output_file = (
        SITE_DIR / "index.html"
    )

    output_file.write_text(
        html_doc,
        encoding="utf-8"
    )

    # ========================================================
    # 生成数据摘要 JSON
    # ========================================================

    metadata_file = (
        SITE_DIR / "metadata.json"
    )

    metadata_file.write_text(
        json.dumps(
            metadata,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    # ========================================================
    # 完成
    # ========================================================

    print()
    print("=" * 70)
    print("✅ 网页生成完成")
    print("=" * 70)

    print(
        f"HTML：{output_file}"
    )

    print(
        f"大小：{output_file.stat().st_size / 1024 / 1024:.2f} MB"
    )

    print()

    for rank_type, info in metadata.items():

        print(
            f"{RANK_CONFIG[rank_type]['name']}："
            f"{info['first_date']} → "
            f"{info['last_date']} | "
            f"{info['rows']:,} 行 | "
            f"{info['dramas']:,} 剧"
        )


# ============================================================
# 21. 执行
# ============================================================

if __name__ == "__main__":
    main()
