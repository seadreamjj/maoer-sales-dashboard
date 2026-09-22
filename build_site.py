# ============================================================
# 🎙️ 猫耳销量月榜跨期分析系统 V2
# ============================================================
#
# 功能：
#
# 1. 自动读取 Google Drive 中的销量月榜 CSV
# 2. 从文件名提取日期
# 3. 自动识别各种字段
# 4. 默认分析范围 = 最新日期往前 30 天
#
# 首页：
# 5. 首页日期选择
# 6. 日期选择后真正动态筛选数据
# 7. 剧名拼音首字母排序
# 8. 在榜天数排序
# 9. 最高排名排序
# 10. 榜单状态：
#       稳定在榜 / 新晋榜单 / 掉榜 / 闪现
# 11. 趋势状态：
#       上升 / 下降 / 波动
#
# 单剧页面：
# 12. 剧名
# 13. UID / 剧集ID
# 14. 日期选择
# 15. 排名曲线
# 16. 播放量：曲线 + 7日增量柱状图
# 17. 订阅数：曲线 + 7日增量柱状图
# 18. 全部ID：曲线 + 7日增量柱状图
# 19. 付费ID：曲线 + 7日增量柱状图
# 20. 每日详细数据表
# 21. 图表自动补齐日期轴：短缺口线性插值，并标记估算点
#
# 输出：
# 22. Excel
# 23. 多页 HTML
# 24. ZIP
# 25. 保存 Google Drive
# 26. Colab 自动下载 Excel + ZIP
#
# ============================================================


# ============================================================
# GitHub Pages 版本：本地/CI 环境配置
# ============================================================
import os
import re
import glob
import shutil
import datetime
import html
import json
import math
import warnings
from pathlib import Path

import pandas as pd
import numpy as np
from pypinyin import lazy_pinyin, Style

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "raw"
OUTPUT_DIR = BASE_DIR / "site"
EXPORT_DIR = BASE_DIR / "exports"
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_DIR = str(DATA_DIR)
TOP_N = 50
DEFAULT_DAYS = 30

# ============================================================
# 5. 从文件名提取日期
# ============================================================

def extract_date_from_filename(filepath):

    filename = os.path.basename(filepath)

    # 支持：
    #
    # 猫耳销量月榜20260807_0757.csv
    #
    # 猫耳销量月榜_含弹幕统计_20260327_1042.csv

    matches = re.findall(
        r"(20\d{2}\d{2}\d{2})",
        filename
    )

    if not matches:
        return None

    for date_str in reversed(matches):

        try:

            dt = datetime.datetime.strptime(
                date_str,
                "%Y%m%d"
            )

            return dt.strftime(
                "%Y-%m-%d"
            )

        except ValueError:
            continue

    return None


# ============================================================
# 6. 清理列名
# ============================================================

def clean_columns(df):

    df = df.copy()

    df.columns = [
        str(c).strip()
        for c in df.columns
    ]

    return df


# ============================================================
# 7. 查找字段
# ============================================================

def find_column(df, candidates):

    columns = list(df.columns)

    # --------------------------------------------------------
    # 精确匹配
    # --------------------------------------------------------

    for candidate in candidates:

        if candidate in columns:

            return candidate

    # --------------------------------------------------------
    # 标准化后匹配
    # --------------------------------------------------------

    normalized = {}

    for col in columns:

        key = (
            str(col)
            .replace(" ", "")
            .replace("\u3000", "")
            .replace("_", "")
            .lower()
        )

        normalized[key] = col

    for candidate in candidates:

        key = (
            str(candidate)
            .replace(" ", "")
            .replace("\u3000", "")
            .replace("_", "")
            .lower()
        )

        if key in normalized:

            return normalized[key]

    return None


# ============================================================
# 8. 数值字段
# ============================================================

def numeric_series(df, column):

    if column is None:

        return pd.Series(
            np.nan,
            index=df.index
        )

    return pd.to_numeric(
        df[column],
        errors="coerce"
    )


# ============================================================
# 9. 拼音首字母
# ============================================================

def get_initial(text):

    if pd.isna(text):

        return "#"

    text = str(text).strip()

    if not text:

        return "#"

    try:

        result = lazy_pinyin(
            text[0],
            style=Style.FIRST_LETTER
        )

        if result:

            letter = result[0].upper()

            if letter.isalpha():

                return letter

    except Exception:
        pass

    if text[0].isalpha():

        return text[0].upper()

    return "#"


# ============================================================
# 10. HTML 安全处理
# ============================================================

def safe_html(value):

    if value is None:
        return "--"

    try:

        if pd.isna(value):

            return "--"

    except Exception:
        pass

    return html.escape(
        str(value)
    )


# ============================================================
# 11. 读取所有 CSV
# ============================================================

def extract_file_version(filepath):
    """优先使用文件名中的 HHMM/HHMMSS，否则使用文件修改时间。"""
    filename = os.path.basename(filepath)
    date_match = re.search(r'(20\d{2}\d{2}\d{2})', filename)
    if not date_match:
        return datetime.datetime.fromtimestamp(os.path.getmtime(filepath))
    date_str = date_match.group(1)
    tail = filename[date_match.end():]
    time_match = re.search(r'(?:^|[_-])(\d{2})(\d{2})(\d{2})?(?=\D|$)', tail)
    if time_match:
        hh, mm = int(time_match.group(1)), int(time_match.group(2)); ss = int(time_match.group(3) or 0)
        try:
            return datetime.datetime.strptime(date_str + f'{hh:02d}{mm:02d}{ss:02d}', '%Y%m%d%H%M%S')
        except ValueError:
            pass
    return datetime.datetime.fromtimestamp(os.path.getmtime(filepath))


def read_csv_file(filepath):
    try:
        try: df = pd.read_csv(filepath, encoding='utf-8-sig')
        except UnicodeDecodeError: df = pd.read_csv(filepath, encoding='gb18030')
    except Exception as e:
        print(f'⚠️ 文件读取失败：{os.path.basename(filepath)}：{e}'); return None
    if df.empty:
        print(f'⚠️ 文件为空：{os.path.basename(filepath)}'); return None
    return clean_columns(df)


def load_rank_data(keyword, label):
    """读取榜单全部历史 CSV；同一天多文件只保留版本时间最晚的一份。"""
    csv_files = [f for f in glob.glob(os.path.join(TARGET_DIR, '*.csv')) if keyword in os.path.basename(f)]
    if not csv_files:
        print(f'⚠️ 没有找到{label} CSV'); return None
    by_date = {}
    for filepath in csv_files:
        date = extract_date_from_filename(filepath)
        if date is None:
            print(f'⚠️ 无法识别日期，跳过：{os.path.basename(filepath)}'); continue
        version = extract_file_version(filepath)
        if date not in by_date or version > by_date[date][0]: by_date[date] = (version, filepath)
    print(f'📄 {label}：找到 {len(csv_files)} 个文件，最终保留 {len(by_date)} 个统计日')
    all_dfs = []
    for date, (version, filepath) in sorted(by_date.items()):
        filename = os.path.basename(filepath); df = read_csv_file(filepath)
        if df is None: continue
        rank_col = find_column(df, ['排名','名次','rank','Rank']); name_col = find_column(df, ['剧名','作品名','剧目','作品','名称','标题'])
        if rank_col is None or name_col is None:
            print(f'⚠️ {filename} 缺少排名/剧名字段，跳过'); continue
        if rank_col != '排名': df.rename(columns={rank_col:'排名'}, inplace=True)
        if name_col != '剧名': df.rename(columns={name_col:'剧名'}, inplace=True)
        df['排名'] = pd.to_numeric(df['排名'], errors='coerce'); df['剧名'] = df['剧名'].astype(str).str.strip()
        df = df.dropna(subset=['排名']); df = df[(df['剧名']!='') & (df['剧名']!='nan')].copy()
        if df.empty: continue
        df['日期']=date; df['来源文件']=filename; df['文件版本时间']=version.strftime('%Y-%m-%d %H:%M:%S'); all_dfs.append(df)
        print(f'  ✅ {filename} → {date}，版本 {version:%Y-%m-%d %H:%M:%S}，{len(df)} 条')
    if not all_dfs: return None
    full_df=pd.concat(all_dfs,ignore_index=True); full_df['日期']=pd.to_datetime(full_df['日期'],errors='coerce').dt.strftime('%Y-%m-%d'); full_df=full_df.dropna(subset=['日期']).sort_values(['日期','排名','剧名']).reset_index(drop=True)
    duplicated=full_df.duplicated(subset=['日期','剧名'],keep='last')
    if duplicated.any():
        print(f'⚠️ {label}发现 {int(duplicated.sum())} 条同日期同剧重复记录，保留最后一条。'); full_df=full_df.loc[~duplicated].copy()
    return full_df.reset_index(drop=True)


def load_sales_rank_data(): return load_rank_data('销量月榜','销量月榜')
def load_popularity_rank_data(): return load_rank_data('人气月榜','人气月榜')
def load_new_rank_data(): return load_rank_data('新品日榜','新品日榜')


# ============================================================
# 12. 榜单趋势
# ============================================================

def calculate_trend(ranks):

    ranks = [
        float(x)
        for x in ranks
        if pd.notna(x)
    ]

    if len(ranks) <= 1:

        return "波动"

    # 排名越小越好
    first = ranks[0]
    last = ranks[-1]

    # 如果没有明显变化
    if last == first:

        return "波动"

    # 只看整个区间的首尾趋势
    # 同时考虑中间是否出现明显反向变化

    changes = []

    for i in range(
        1,
        len(ranks)
    ):

        changes.append(
            ranks[i] - ranks[i - 1]
        )

    # 排名整体下降 = 上升
    # 排名整体增加 = 下降

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

    # 首尾变化非常小
    if abs(last - first) <= 2:

        return "波动"

    if last < first:

        return "上升"

    if last > first:

        return "下降"

    return "波动"


# ============================================================
# 13. 榜单状态
# ============================================================

def calculate_rank_status(
    drama_df,
    first_date,
    last_date
):

    if drama_df.empty:

        return "闪现"

    dates = sorted(
        drama_df["日期"].unique()
    )

    first_drama_date = dates[0]

    last_drama_date = dates[-1]

    starts_first = (
        first_drama_date == first_date
    )

    ends_last = (
        last_drama_date == last_date
    )

    # --------------------------------------------------------
    # 从第一天到最后一天
    # --------------------------------------------------------

    if starts_first and ends_last:

        return "稳定在榜"

    # --------------------------------------------------------
    # 第一日没有，最后一天有
    # --------------------------------------------------------

    if not starts_first and ends_last:

        return "新晋榜单"

    # --------------------------------------------------------
    # 第一日有，最后一天没有
    # --------------------------------------------------------

    if starts_first and not ends_last:

        return "掉榜"

    # --------------------------------------------------------
    # 中途出现，中途消失
    # --------------------------------------------------------

    return "闪现"


# ============================================================
# 14. 汇总
# ============================================================

def build_summary(
    filtered_df,
    first_date,
    last_date
):

    rows = []

    for drama, group in filtered_df.groupby(
        "剧名"
    ):

        group = group.sort_values(
            "日期"
        )

        ranks = group["排名"].tolist()

        rows.append({

            "剧名": drama,

            "首字母": get_initial(
                drama
            ),

            "在榜天数": len(group),

            "最高排名": int(
                group["排名"].min()
            ),

            "最低排名": int(
                group["排名"].max()
            ),

            "首次上榜": group["日期"].iloc[0],

            "最后在榜": group["日期"].iloc[-1],

            "榜单状态": calculate_rank_status(
                group,
                first_date,
                last_date
            ),

            "趋势状态": calculate_trend(
                ranks
            )

        })

    return pd.DataFrame(rows)


# ============================================================
# 15. 查找剧目字段
# ============================================================

def detect_drama_columns(df):

    return {

        "uid": find_column(
            df,
            [
                "uid",
                "UID",
                "剧集ID",
                "剧集 Id",
                "ID",
                "id",
                "作品ID",
                "音频ID"
            ]
        ),

        "play": find_column(
            df,
            [
                "播放量",
                "播放",
                "播放数",
                "播放次数",
                "VV"
            ]
        ),

        "subscribe": find_column(
            df,
            [
                "订阅数",
                "订阅",
                "收藏数",
                "收藏"
            ]
        ),

        "total_id": find_column(
            df,
            [
                "全部集弹幕UID数",
                "全部ID数",
                "全部ID",
                "全部UID",
                "全部集UID数",
                "弹幕UID数",
                "UID数"
            ]
        ),

        "paid_id": find_column(
            df,
            [
                "付费集弹幕UID数",
                "付费ID数",
                "付费ID",
                "付费UID",
                "付费集UID数"
            ]
        ),

        "total_episodes": find_column(
            df,
            [
                "总集数",
                "集数",
                "总集"
            ]
        ),

        "paid_episodes": find_column(
            df,
            [
                "付费集数",
                "付费集"
            ]
        ),

        "latest_update": find_column(
            df,
            [
                "最新更新",
                "更新",
                "最新更新内容"
            ]
        )

    }


# ============================================================
# 16. JS / CSS
# ============================================================

HTML_CSS = r"""
<style>

:root {
    --bg: #f3f6fb;
    --card: #ffffff;
    --text: #172033;
    --muted: #718096;
    --border: #e7ebf2;
    --primary: #5b67d8;
    --primary-dark: #4653c4;
    --shadow:
        0 10px 35px rgba(28, 39, 72, .07);
    --radius: 18px;
}

* {
    box-sizing: border-box;
}

html {
    scroll-behavior: smooth;
}

body {
    margin: 0;
    background:
        radial-gradient(
            circle at 10% 0%,
            rgba(91,103,216,.08),
            transparent 28%
        ),
        var(--bg);
    color: var(--text);
    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        "PingFang SC",
        "Microsoft YaHei",
        sans-serif;
}

.container {
    width: min(1540px, 94%);
    margin: 0 auto;
    padding: 30px 0 70px;
}

.header {
    position: relative;
    overflow: hidden;
    background:
        linear-gradient(
            135deg,
            #5664d9 0%,
            #7451a8 55%,
            #8b5fbf 100%
        );
    color: white;
    padding: 38px 42px;
    border-radius: 24px;
    margin-bottom: 22px;
    box-shadow:
        0 18px 50px rgba(73, 67, 145, .20);
}

.header::after {
    content: "";
    position: absolute;
    width: 260px;
    height: 260px;
    right: -70px;
    top: -100px;
    border-radius: 50%;
    background: rgba(255,255,255,.10);
}

.header h1 {
    position: relative;
    z-index: 1;
    margin: 0 0 9px;
    font-size: clamp(25px, 3vw, 34px);
    letter-spacing: -.5px;
}

.header p {
    position: relative;
    z-index: 1;
    margin: 0;
    opacity: .88;
    font-size: 14px;
}

.panel,
.chart-card,
.stat-card {
    background: rgba(255,255,255,.96);
    border: 1px solid rgba(231,235,242,.9);
    box-shadow: var(--shadow);
}

.panel {
    border-radius: var(--radius);
    padding: 22px;
    margin-bottom: 20px;
}

.filters {
    display: grid;
    grid-template-columns:
        repeat(4, minmax(170px, 1fr));
    gap: 14px;
    align-items: end;
}

.filter-item label {
    display: block;
    font-size: 12px;
    font-weight: 650;
    color: var(--muted);
    margin-bottom: 7px;
}

select,
input[type=date] {
    width: 100%;
    height: 43px;
    padding: 0 13px;
    border-radius: 11px;
    border: 1px solid #dce2ec;
    background: white;
    color: var(--text);
    font-size: 14px;
    outline: none;
    transition: .18s ease;
}

select:hover,
input[type=date]:hover {
    border-color: #c4cbe0;
}

select:focus,
input[type=date]:focus {
    border-color: var(--primary);
    box-shadow:
        0 0 0 4px rgba(91,103,216,.11);
}

button {
    height: 43px;
    border: 0;
    border-radius: 11px;
    background:
        linear-gradient(
            135deg,
            var(--primary),
            #7058c9
        );
    color: white;
    font-size: 14px;
    font-weight: 650;
    cursor: pointer;
    box-shadow:
        0 7px 18px rgba(91,103,216,.20);
    transition:
        transform .16s ease,
        box-shadow .16s ease;
}

button:hover {
    transform: translateY(-1px);
    box-shadow:
        0 10px 22px rgba(91,103,216,.27);
}

button:active {
    transform: translateY(0);
}

.stats {
    display: grid;
    grid-template-columns:
        repeat(4, 1fr);
    gap: 14px;
    margin-bottom: 20px;
}

.stat-card {
    position: relative;
    overflow: hidden;
    padding: 21px;
    border-radius: 17px;
}

.stat-card::before {
    content: "";
    position: absolute;
    left: 0;
    top: 0;
    width: 4px;
    height: 100%;
    background: linear-gradient(
        180deg,
        var(--primary),
        #8b6bd1
    );
}

.stat-label {
    font-size: 12px;
    color: var(--muted);
    font-weight: 600;
}

.stat-value {
    margin-top: 7px;
    font-size: 29px;
    font-weight: 750;
    letter-spacing: -.7px;
}

.info-grid {
    display: grid;
    grid-template-columns:
        repeat(5, 1fr);
    gap: 12px;
}

.info-card {
    padding: 17px;
    border-radius: 14px;
    background:
        linear-gradient(
            145deg,
            #fafbfe,
            #f5f7fb
        );
    border: 1px solid var(--border);
    transition: transform .16s ease;
}

.info-card:hover {
    transform: translateY(-2px);
}

.info-label {
    font-size: 11px;
    color: var(--muted);
    font-weight: 600;
}

.info-value {
    margin-top: 7px;
    font-size: 18px;
    font-weight: 730;
    word-break: break-all;
}

.chart-card {
    border-radius: 20px;
    padding: 18px 20px 13px;
    margin-bottom: 18px;
}

.chart-head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 15px;
    padding: 2px 3px 4px;
}

.chart-title {
    font-size: 17px;
    font-weight: 750;
    letter-spacing: -.15px;
}

.chart-subtitle {
    margin-top: 4px;
    color: var(--muted);
    font-size: 11px;
}

.chart-legend-note {
    color: var(--muted);
    font-size: 11px;
    white-space: nowrap;
    padding-top: 3px;
}

.dot {
    display: inline-block;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    margin: 0 4px 0 8px;
    vertical-align: 1px;
}

.dot:first-child {
    margin-left: 0;
}

.dot-real {
    background: var(--primary);
}

.dot-estimated {
    background: #9b7bd2;
}

.plot-area {
    height: 410px;
}

.rank-plot {
    height: 390px;
}

.table-wrap {
    overflow-x: auto;
    border: 1px solid var(--border);
    border-radius: 13px;
}

table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    background: white;
}

th {
    position: sticky;
    top: 0;
    z-index: 1;
    background: #f7f8fc;
    color: #667085;
    font-size: 12px;
    font-weight: 700;
    padding: 13px 12px;
    text-align: left;
    white-space: nowrap;
    border-bottom: 1px solid var(--border);
}

td {
    padding: 12px;
    border-bottom: 1px solid #eef1f5;
    font-size: 13px;
    white-space: nowrap;
}

tbody tr:last-child td {
    border-bottom: 0;
}

tbody tr:hover td {
    background: #fafbff;
}

.drama-link {
    color: var(--primary);
    text-decoration: none;
    font-weight: 680;
}

.drama-link:hover {
    color: var(--primary-dark);
    text-decoration: underline;
}

.badge {
    display: inline-flex;
    align-items: center;
    padding: 4px 9px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    white-space: nowrap;
}

.rank-stable {
    background: #e9f7ef;
    color: #177447;
}

.rank-new {
    background: #e9f0ff;
    color: #3e62c7;
}

.rank-drop {
    background: #fff0ee;
    color: #c9473a;
}

.rank-flash {
    background: #f1ebff;
    color: #7549bd;
}

.trend-up {
    background: #e9f7ef;
    color: #177447;
}

.trend-down {
    background: #fff0ee;
    color: #c9473a;
}

.trend-wave {
    background: #fff6dd;
    color: #a16a00;
}

.back {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    color: var(--primary);
    text-decoration: none;
    margin: 0 0 15px 3px;
    font-size: 13px;
    font-weight: 700;
}

.back:hover {
    color: var(--primary-dark);
}

.no-data {
    text-align: center;
    padding: 45px;
    color: #9ca3af;
}

.footer {
    text-align: center;
    color: #9aa3b2;
    padding: 28px;
    font-size: 12px;
}

h2 {
    font-size: 18px;
    letter-spacing: -.2px;
}

@media(max-width: 1100px) {

    .info-grid {
        grid-template-columns:
            repeat(3, 1fr);
    }

}

@media(max-width: 900px) {

    .filters {
        grid-template-columns: 1fr 1fr;
    }

    .stats {
        grid-template-columns:
            repeat(2, 1fr);
    }

    .info-grid {
        grid-template-columns:
            repeat(2, 1fr);
    }

    .plot-area {
        height: 370px;
    }

}

@media(max-width: 600px) {

    .container {
        width: 94%;
        padding-top: 15px;
    }

    .header {
        padding: 27px 23px;
        border-radius: 19px;
    }

    .panel {
        padding: 16px;
    }

    .filters,
    .stats,
    .info-grid {
        grid-template-columns: 1fr;
    }

    .chart-card {
        padding: 15px 12px 8px;
    }

    .chart-head {
        display: block;
    }

    .chart-legend-note {
        margin-top: 7px;
    }

    .plot-area,
    .rank-plot {
        height: 330px;
    }

}

</style>
"""


PLOTLY_SCRIPT = """
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
"""


PLOTLY_SCRIPT = """
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
"""


# ============================================================
# 17. 榜单状态 badge
# ============================================================

def rank_badge(status):

    mapping = {

        "稳定在榜": "rank-stable",

        "新晋榜单": "rank-new",

        "掉榜": "rank-drop",

        "闪现": "rank-flash"

    }

    cls = mapping.get(
        status,
        "rank-flash"
    )

    return (
        f'<span class="badge {cls}">'
        f'{safe_html(status)}'
        f'</span>'
    )


def trend_badge(status):

    mapping = {

        "上升": "trend-up",

        "下降": "trend-down",

        "波动": "trend-wave"

    }

    cls = mapping.get(
        status,
        "trend-wave"
    )

    return (
        f'<span class="badge {cls}">'
        f'{safe_html(status)}'
        f'</span>'
    )


# ============================================================
# 18. Plotly 图表
# ============================================================

def prepare_chart_series(dates, values, max_gap=3):
    """
    图表专用数据预处理。

    规则：
    - 建立完整的每日日期轴
    - 中间缺失且连续缺失 <= max_gap 天：线性插值
    - 开头/结尾缺失：不补
    - 连续缺失 > max_gap 天：保持缺失
    - 不修改原始数据，只用于图表展示
    """

    temp = pd.DataFrame({
        "日期": pd.to_datetime(dates, errors="coerce"),
        "数值": pd.to_numeric(
            pd.Series(values).reset_index(drop=True),
            errors="coerce"
        )
    })

    temp = (
        temp.dropna(subset=["日期"])
        .sort_values("日期")
        .drop_duplicates("日期", keep="last")
        .set_index("日期")
    )

    if temp.empty:
        return pd.DataFrame(
            columns=["日期", "数值", "原始数据", "估算值"]
        )

    full_dates = pd.date_range(
        start=temp.index.min(),
        end=temp.index.max(),
        freq="D"
    )

    temp = temp.reindex(full_dates)

    temp["原始数据"] = temp["数值"].notna()

    # 仅对短的内部缺口进行线性插值
    temp["数值"] = (
        temp["数值"]
        .interpolate(
            method="linear",
            limit=max_gap,
            limit_area="inside"
        )
    )

    temp["估算值"] = (
        (~temp["原始数据"]) &
        temp["数值"].notna()
    )

    temp.index.name = "日期"

    return temp.reset_index()


def make_metric_chart(
    chart_id,
    title,
    dates,
    values,
    max_gap=3
):

    temp = prepare_chart_series(
        dates,
        values,
        max_gap=max_gap
    )

    # 7日增量现在是真正按“自然日”计算
    temp["7日增量"] = (
        temp["数值"] -
        temp["数值"].shift(7)
    )

    x = [
        d.strftime("%Y-%m-%d")
        for d in temp["日期"]
    ]

    y = [
        None if pd.isna(v) else float(v)
        for v in temp["数值"]
    ]

    delta = [
        None if pd.isna(v) else float(v)
        for v in temp["7日增量"]
    ]

    estimated = [
        bool(v)
        for v in temp["估算值"]
    ]

    payload = {
        "x": x,
        "y": y,
        "delta": delta,
        "estimated": estimated
    }

    data_json = json.dumps(
        payload,
        ensure_ascii=False
    )

    return f"""

<div class="chart-card">

    <div class="chart-head">
        <div>
            <div class="chart-title">
                {html.escape(title)}
            </div>
            <div class="chart-subtitle">
                累计值趋势 · 柱状图为 7 日自然日增量
            </div>
        </div>
        <div class="chart-legend-note">
            <span class="dot dot-real"></span>原始数据
            <span class="dot dot-estimated"></span>插值
        </div>
    </div>

    <div id="{chart_id}"
         class="plot-area">
    </div>

</div>

<script>

(function() {{

    const payload = {data_json};

    const realX = [];
    const realY = [];

    const estimatedX = [];
    const estimatedY = [];

    payload.x.forEach((x, i) => {{

        if (payload.y[i] === null)
            return;

        if (payload.estimated[i]) {{
            estimatedX.push(x);
            estimatedY.push(payload.y[i]);
        }} else {{
            realX.push(x);
            realY.push(payload.y[i]);
        }}

    }});

    const lineTrace = {{
        x: payload.x,
        y: payload.y,
        type: "scatter",
        mode: "lines",
        name: "{html.escape(title)}",
        yaxis: "y1",
        connectgaps: false,
        line: {{
            width: 3
        }},
        hovertemplate:
            "%{{x}}<br>" +
            "{html.escape(title)}：%{{y:,.0f}}" +
            "<extra></extra>"
    }};

    const realTrace = {{
        x: realX,
        y: realY,
        type: "scatter",
        mode: "markers",
        name: "原始数据",
        marker: {{
            size: 6
        }},
        yaxis: "y1",
        hovertemplate:
            "%{{x}}<br>" +
            "{html.escape(title)}：%{{y:,.0f}}" +
            "<br>原始数据" +
            "<extra></extra>"
    }};

    const estimatedTrace = {{
        x: estimatedX,
        y: estimatedY,
        type: "scatter",
        mode: "markers",
        name: "插值数据",
        marker: {{
            size: 7,
            symbol: "diamond"
        }},
        yaxis: "y1",
        hovertemplate:
            "%{{x}}<br>" +
            "{html.escape(title)}：%{{y:,.0f}}" +
            "<br>估算值（短缺口线性插值）" +
            "<extra></extra>"
    }};

    const barTrace = {{
        x: payload.x,
        y: payload.delta,
        type: "bar",
        name: "7日增量",
        yaxis: "y2",
        opacity: 0.24,
        hovertemplate:
            "%{{x}}<br>" +
            "7日增量：%{{y:,.0f}}" +
            "<extra></extra>"
    }};

    const layout = {{

        margin: {{
            l: 68,
            r: 72,
            t: 22,
            b: 58
        }},

        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",

        hovermode: "x unified",

        hoverlabel: {{
            bgcolor: "#1f2937",
            font: {{
                color: "#ffffff"
            }}
        }},

        legend: {{
            orientation: "h",
            x: 0,
            y: 1.06,
            font: {{
                size: 12
            }}
        }},

        xaxis: {{
            type: "date",
            showgrid: false,
            zeroline: false
        }},

        yaxis: {{
            title: "{html.escape(title)}",
            side: "left",
            showgrid: true,
            gridcolor: "rgba(148,163,184,.18)",
            zeroline: false
        }},

        yaxis2: {{
            title: "7日增量",
            overlaying: "y",
            side: "right",
            showgrid: false,
            zeroline: false
        }},

        bargap: 0.28,

        font: {{
            family:
                '-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif'
        }}
    }};

    Plotly.newPlot(
        "{chart_id}",
        [
            barTrace,
            lineTrace,
            realTrace,
            estimatedTrace
        ],
        layout,
        {{
            responsive: true,
            displaylogo: false,
            modeBarButtonsToRemove: [
                "lasso2d",
                "select2d"
            ]
        }}
    );

}})();

</script>

"""


# ============================================================
# 19. 排名图
# ============================================================

def make_rank_chart(
    chart_id,
    dates,
    ranks
):

    temp = prepare_chart_series(
        dates,
        ranks,
        max_gap=1
    )

    x = [
        d.strftime("%Y-%m-%d")
        for d in temp["日期"]
    ]

    y = [
        None if pd.isna(v) else float(v)
        for v in temp["数值"]
    ]

    estimated = [
        bool(v)
        for v in temp["估算值"]
    ]

    payload = json.dumps(
        {
            "x": x,
            "y": y,
            "estimated": estimated
        },
        ensure_ascii=False
    )

    return f"""

<div class="chart-card">

    <div class="chart-head">
        <div>
            <div class="chart-title">
                排名变化
            </div>
            <div class="chart-subtitle">
                排名缺失最多仅插值 1 天，较长缺口保持断线
            </div>
        </div>
        <div class="chart-legend-note">
            <span class="dot dot-real"></span>原始
            <span class="dot dot-estimated"></span>插值
        </div>
    </div>

    <div id="{chart_id}"
         class="plot-area rank-plot">
    </div>

</div>

<script>

(function() {{

    const payload = {payload};

    const realX = [];
    const realY = [];

    const estimatedX = [];
    const estimatedY = [];

    payload.x.forEach((x, i) => {{

        if (payload.y[i] === null)
            return;

        if (payload.estimated[i]) {{
            estimatedX.push(x);
            estimatedY.push(payload.y[i]);
        }} else {{
            realX.push(x);
            realY.push(payload.y[i]);
        }}

    }});

    const lineTrace = {{
        x: payload.x,
        y: payload.y,
        type: "scatter",
        mode: "lines",
        name: "排名",
        connectgaps: false,
        line: {{
            width: 3
        }},
        hovertemplate:
            "%{{x}}<br>排名：%{{y:.0f}}" +
            "<extra></extra>"
    }};

    const realTrace = {{
        x: realX,
        y: realY,
        type: "scatter",
        mode: "markers",
        name: "原始",
        marker: {{
            size: 7
        }},
        hovertemplate:
            "%{{x}}<br>排名：%{{y:.0f}}" +
            "<br>原始数据" +
            "<extra></extra>"
    }};

    const estimatedTrace = {{
        x: estimatedX,
        y: estimatedY,
        type: "scatter",
        mode: "markers",
        name: "插值",
        marker: {{
            size: 8,
            symbol: "diamond"
        }},
        hovertemplate:
            "%{{x}}<br>排名：%{{y:.0f}}" +
            "<br>估算值" +
            "<extra></extra>"
    }};

    const layout = {{

        margin: {{
            l: 65,
            r: 30,
            t: 22,
            b: 58
        }},

        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",

        hovermode: "x unified",

        hoverlabel: {{
            bgcolor: "#1f2937",
            font: {{
                color: "#ffffff"
            }}
        }},

        legend: {{
            orientation: "h",
            x: 0,
            y: 1.06
        }},

        xaxis: {{
            type: "date",
            showgrid: false
        }},

        yaxis: {{
            title: "排名",
            autorange: "reversed",
            dtick: 5,
            showgrid: true,
            gridcolor: "rgba(148,163,184,.18)"
        }},

        font: {{
            family:
                '-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif'
        }}
    }};

    Plotly.newPlot(
        "{chart_id}",
        [
            lineTrace,
            realTrace,
            estimatedTrace
        ],
        layout,
        {{
            responsive: true,
            displaylogo: false,
            modeBarButtonsToRemove: [
                "lasso2d",
                "select2d"
            ]
        }}
    );

}})();

</script>

"""


# ============================================================
# 20. 单剧页面
#
# ★ 重点：
#   页面保存该剧完整历史数据
#   日期选择通过 JS 动态过滤
# ============================================================

def generate_drama_page(
    drama,
    drama_full_df
):

    safe_name = re.sub(
        r'[\\/:*?"<>|]',
        "_",
        str(drama)
    )

    page_filename = (
        f"剧目_{safe_name}.html"
    )

    page_path = os.path.join(
        OUTPUT_DIR,
        page_filename
    )

    drama_df = (
        drama_full_df
        .sort_values("日期")
        .copy()
    )

    mapping = detect_drama_columns(
        drama_df
    )

    # --------------------------------------------------------
    # 把数据转成 JSON
    # --------------------------------------------------------

    records = []

    for _, row in drama_df.iterrows():

        item = {}

        for col in drama_df.columns:

            value = row[col]

            if pd.isna(value):

                item[col] = None

            elif isinstance(
                value,
                (
                    np.integer,
                    np.int64
                )
            ):

                item[col] = int(value)

            elif isinstance(
                value,
                (
                    np.floating,
                    np.float64
                )
            ):

                item[col] = float(value)

            else:

                item[col] = str(value)

        records.append(item)

    data_json = json.dumps(
        records,
        ensure_ascii=False
    )

    # --------------------------------------------------------
    # 全部日期
    # --------------------------------------------------------

    dates = sorted(
        drama_df["日期"].unique()
    )

    first_date = dates[0]

    last_date = dates[-1]

    # --------------------------------------------------------
    # 信息卡
    # --------------------------------------------------------

    latest = drama_df.iloc[-1]

    info_fields = [

        ("排名", "排名"),

        ("剧名", "剧名"),

        ("UID / 剧集ID", mapping["uid"]),

        ("播放量", mapping["play"]),

        ("订阅数", mapping["subscribe"]),

        ("总集数", mapping["total_episodes"]),

        ("付费集数", mapping["paid_episodes"]),

        ("全部ID数", mapping["total_id"]),

        ("付费ID数", mapping["paid_id"]),

        ("最新更新", mapping["latest_update"])

    ]

    info_html = ""

    for label, col in info_fields:

        if col is None:

            value = "--"

        else:

            value = latest.get(
                col,
                "--"
            )

            if pd.isna(value):

                value = "--"

        info_html += f"""

        <div class="info-card">

            <div class="info-label">
                {html.escape(label)}
            </div>

            <div class="info-value">
                {safe_html(value)}
            </div>

        </div>

        """

    # --------------------------------------------------------
    # 直接生成初始图表
    # --------------------------------------------------------

    charts_html = ""

    charts_html += make_rank_chart(
        "rank_chart",
        drama_df["日期"].tolist(),
        drama_df["排名"].tolist()
    )

    metric_configs = [

        (
            "play",
            "播放量",
            "播放量",
            "play_chart"
        ),

        (
            "subscribe",
            "订阅数",
            "订阅数",
            "subscribe_chart"
        ),

        (
            "total_id",
            "全部ID数",
            "全部ID数",
            "total_id_chart"
        ),

        (
            "paid_id",
            "付费ID数",
            "付费ID数",
            "paid_id_chart"
        )

    ]

    for key, title, ylabel, chart_id in metric_configs:

        col = mapping.get(key)

        if col is None:
            continue

        charts_html += make_metric_chart(
            chart_id,
            title,
            drama_df["日期"],
            drama_df[col]
        )

    # --------------------------------------------------------
    # 表格列
    # --------------------------------------------------------

    table_columns = [
        "日期",
        "排名"
    ]

    for col in [

        mapping["play"],
        mapping["subscribe"],
        mapping["total_id"],
        mapping["paid_id"]

    ]:

        if (
            col
            and col not in table_columns
        ):

            table_columns.append(
                col
            )

    headers = "".join(
        f"<th>{safe_html(c)}</th>"
        for c in table_columns
    )

    table_rows = ""

    for _, row in drama_df.iterrows():

        table_rows += "<tr>"

        for col in table_columns:

            value = row.get(
                col,
                "--"
            )

            table_rows += (
                f"<td>{safe_html(value)}</td>"
            )

        table_rows += "</tr>"

    # --------------------------------------------------------
    # HTML
    # --------------------------------------------------------

    content = f"""

<!DOCTYPE html>

<html lang="zh-CN">

<head>

<meta charset="UTF-8">

<meta name="viewport"
      content="width=device-width, initial-scale=1.0">

<title>
{html.escape(drama)}
</title>

{PLOTLY_SCRIPT}

{HTML_CSS}

</head>

<body>

<div class="container">

<a class="back"
   href="index.html">
← 返回剧目总览
</a>

<div class="header">

<h1>
{html.escape(drama)}
</h1>

<p>
猫耳销量月榜单剧目详情
</p>

</div>


<!-- ===================================================== -->
<!-- 日期选择 -->
<!-- ===================================================== -->

<div class="panel">

<div class="filters">

<div class="filter-item">

<label>
开始日期
</label>

<input
    id="startDate"
    type="date"
    min="{first_date}"
    max="{last_date}"
    value="{first_date}"
>

</div>


<div class="filter-item">

<label>
结束日期
</label>

<input
    id="endDate"
    type="date"
    min="{first_date}"
    max="{last_date}"
    value="{last_date}"
>

</div>


<div class="filter-item">

<button
    onclick="applyDateRange()"
>
应用日期范围
</button>

</div>

<div class="filter-item">

<label>
当前统计范围
</label>

<div id="rangeText">
{first_date} → {last_date}
</div>

</div>

</div>

</div>


<!-- ===================================================== -->
<!-- 信息 -->
<!-- ===================================================== -->

<div class="panel">

<div class="info-grid">

{info_html}

</div>

</div>


<!-- ===================================================== -->
<!-- 动态图表 -->
<!-- ===================================================== -->

<div id="chartsArea">

{charts_html}

</div>


<!-- ===================================================== -->
<!-- 每日数据 -->
<!-- ===================================================== -->

<div class="panel">

<h2>
每日详细数据
</h2>

<div class="table-wrap">

<table>

<thead>

<tr>

{headers}

</tr>

</thead>

<tbody id="detailTable">

{table_rows}

</tbody>

</table>

</div>

</div>


<div class="footer">

猫耳销量月榜跨期分析系统

</div>

</div>


<script>

const ALL_DATA =
    {data_json};


const MAPPING =
{{
    rank: "排名",
    play: {json.dumps(mapping["play"])},
    subscribe: {json.dumps(mapping["subscribe"])},
    total_id: {json.dumps(mapping["total_id"])},
    paid_id: {json.dumps(mapping["paid_id"])}
}};


function applyDateRange() {{

    let start =
        document.getElementById(
            "startDate"
        ).value;

    let end =
        document.getElementById(
            "endDate"
        ).value;

    if (!start || !end) {{

        return;

    }}

    if (start > end) {{

        alert(
            "开始日期不能晚于结束日期"
        );

        return;

    }}

    const filtered =
        ALL_DATA.filter(
            row =>
                row["日期"] >= start &&
                row["日期"] <= end
        );

    document.getElementById(
        "rangeText"
    ).innerText =
        start + " → " + end;


    updateTable(filtered);

    updateCharts(filtered);

}}


function updateTable(data) {{

    const tbody =
        document.getElementById(
            "detailTable"
        );

    tbody.innerHTML = "";

    if (data.length === 0) {{

        tbody.innerHTML =
            '<tr><td colspan="10" class="no-data">' +
            '该时间段没有数据' +
            '</td></tr>';

        return;

    }}


    data.forEach(row => {{

        let tr =
            document.createElement("tr");

        const columns =
            ["日期"];

        if (MAPPING.rank)
            columns.push(MAPPING.rank);

        if (MAPPING.play)
            columns.push(MAPPING.play);

        if (MAPPING.subscribe)
            columns.push(MAPPING.subscribe);

        if (MAPPING.total_id)
            columns.push(MAPPING.total_id);

        if (MAPPING.paid_id)
            columns.push(MAPPING.paid_id);


        columns.forEach(col => {{

            let td =
                document.createElement("td");

            let value =
                row[col];

            if (
                value === null ||
                value === undefined
            ) {{

                value = "--";

            }}

            td.innerText =
                value;

            tr.appendChild(td);

        }});

        tbody.appendChild(tr);

    }});

}}


function prepareChartSeries(data, column, maxGap = 3) {{

    if (!data || data.length === 0)
        return [];

    const sorted = [...data].sort(
        (a, b) =>
            a["日期"].localeCompare(b["日期"])
    );

    const values = {{}};

    sorted.forEach(row => {{

        const date = row["日期"];

        const value = row[column];

        values[date] =
            value === null ||
            value === undefined ||
            value === ""
                ? null
                : Number(value);

    }});

    const start =
        new Date(sorted[0]["日期"] + "T00:00:00");

    const end =
        new Date(
            sorted[sorted.length - 1]["日期"] +
            "T00:00:00"
        );

    const result = [];

    let current = new Date(start);

    while (current <= end) {{

        const date =
            current.getFullYear() +
            "-" +
            String(current.getMonth() + 1).padStart(2, "0") +
            "-" +
            String(current.getDate()).padStart(2, "0");

        const hasOriginal =
            Object.prototype.hasOwnProperty.call(
                values,
                date
            );

        result.push({{
            date: date,
            value: hasOriginal
                ? values[date]
                : null,
            original: hasOriginal
        }});

        current.setDate(
            current.getDate() + 1
        );
    }}

    // ----------------------------------------------------
    // 只对 <= maxGap 天的内部缺口进行线性插值
    // ----------------------------------------------------

    for (let i = 0; i < result.length; i++) {{

        if (result[i].value !== null)
            continue;

        let left = i - 1;

        while (
            left >= 0 &&
            result[left].value === null
        ) {{
            left--;
        }}

        let right = i + 1;

        while (
            right < result.length &&
            result[right].value === null
        ) {{
            right++;
        }}

        if (
            left >= 0 &&
            right < result.length
        ) {{

            const gap =
                right - left - 1;

            if (gap <= maxGap) {{

                const leftValue =
                    result[left].value;

                const rightValue =
                    result[right].value;

                const step =
                    (
                        rightValue -
                        leftValue
                    ) / (right - left);

                result[i].value =
                    leftValue +
                    step * (i - left);

                result[i].estimated = true;

            }}

        }}

    }}

    result.forEach(item => {{

        if (item.estimated !== true)
            item.estimated = false;

    }});

    return result;
}}


function renderMetricChart(
    elementId,
    data,
    column,
    title,
    maxGap = 3
) {{

    const element =
        document.getElementById(elementId);

    if (!element || !column)
        return;

    const series =
        prepareChartSeries(
            data,
            column,
            maxGap
        );

    const dates =
        series.map(
            item => item.date
        );

    const values =
        series.map(
            item => item.value
        );

    const estimated =
        series.map(
            item => item.estimated
        );

    const delta =
        values.map(
            (value, index) => {{

                if (
                    index < 7 ||
                    value === null
                )
                    return null;

                const old =
                    values[index - 7];

                if (
                    old === null ||
                    old === undefined
                )
                    return null;

                return value - old;

            }}
        );

    const realX = [];
    const realY = [];

    const estimatedX = [];
    const estimatedY = [];

    dates.forEach((date, index) => {{

        if (values[index] === null)
            return;

        if (estimated[index]) {{
            estimatedX.push(date);
            estimatedY.push(values[index]);
        }} else {{
            realX.push(date);
            realY.push(values[index]);
        }}

    }});

    Plotly.react(
        elementId,

        [

            {{

                x: dates,
                y: delta,

                type: "bar",

                name: "7日增量",

                yaxis: "y2",

                opacity: 0.24,

                hovertemplate:
                    "%{{x}}<br>" +
                    "7日增量：%{{y:,.0f}}" +
                    "<extra></extra>"

            }},

            {{

                x: dates,
                y: values,

                type: "scatter",

                mode: "lines",

                name: title,

                yaxis: "y1",

                connectgaps: false,

                line: {{
                    width: 3
                }},

                hovertemplate:
                    "%{{x}}<br>" +
                    title +
                    "：%{{y:,.0f}}" +
                    "<extra></extra>"

            }},

            {{

                x: realX,
                y: realY,

                type: "scatter",

                mode: "markers",

                name: "原始数据",

                marker: {{
                    size: 6
                }},

                hovertemplate:
                    "%{{x}}<br>" +
                    title +
                    "：%{{y:,.0f}}" +
                    "<br>原始数据" +
                    "<extra></extra>"

            }},

            {{

                x: estimatedX,
                y: estimatedY,

                type: "scatter",

                mode: "markers",

                name: "插值数据",

                marker: {{
                    size: 7,
                    symbol: "diamond"
                }},

                hovertemplate:
                    "%{{x}}<br>" +
                    title +
                    "：%{{y:,.0f}}" +
                    "<br>估算值（短缺口线性插值）" +
                    "<extra></extra>"

            }}

        ],

        {{

            margin: {{
                l: 68,
                r: 72,
                t: 22,
                b: 58
            }},

            paper_bgcolor:
                "rgba(0,0,0,0)",

            plot_bgcolor:
                "rgba(0,0,0,0)",

            hovermode:
                "x unified",

            legend: {{
                orientation: "h",
                x: 0,
                y: 1.06
            }},

            xaxis: {{
                type: "date",
                showgrid: false
            }},

            yaxis: {{
                title: title,
                showgrid: true,
                gridcolor:
                    "rgba(148,163,184,.18)"
            }},

            yaxis2: {{
                title: "7日增量",
                overlaying: "y",
                side: "right",
                showgrid: false
            }},

            bargap: 0.28
        }},

        {{
            responsive: true,
            displaylogo: false,
            modeBarButtonsToRemove: [
                "lasso2d",
                "select2d"
            ]
        }}
    );

}}


function renderRankChart(data) {{

    const element =
        document.getElementById(
            "rank_chart"
        );

    if (!element)
        return;

    const series =
        prepareChartSeries(
            data,
            MAPPING.rank,
            1
        );

    const dates =
        series.map(
            item => item.date
        );

    const values =
        series.map(
            item => item.value
        );

    const realX = [];
    const realY = [];

    const estimatedX = [];
    const estimatedY = [];

    series.forEach(item => {{

        if (item.value === null)
            return;

        if (item.estimated) {{
            estimatedX.push(item.date);
            estimatedY.push(item.value);
        }} else {{
            realX.push(item.date);
            realY.push(item.value);
        }}

    }});

    Plotly.react(
        "rank_chart",

        [

            {{

                x: dates,
                y: values,

                type: "scatter",

                mode: "lines",

                name: "排名",

                connectgaps: false,

                line: {{
                    width: 3
                }},

                hovertemplate:
                    "%{{x}}<br>" +
                    "排名：%{{y:.0f}}" +
                    "<extra></extra>"

            }},

            {{

                x: realX,
                y: realY,

                type: "scatter",

                mode: "markers",

                name: "原始",

                marker: {{
                    size: 7
                }},

                hovertemplate:
                    "%{{x}}<br>" +
                    "排名：%{{y:.0f}}" +
                    "<br>原始数据" +
                    "<extra></extra>"

            }},

            {{

                x: estimatedX,
                y: estimatedY,

                type: "scatter",

                mode: "markers",

                name: "插值",

                marker: {{
                    size: 8,
                    symbol: "diamond"
                }},

                hovertemplate:
                    "%{{x}}<br>" +
                    "排名：%{{y:.0f}}" +
                    "<br>估算值" +
                    "<extra></extra>"

            }}

        ],

        {{

            margin: {{
                l: 65,
                r: 30,
                t: 22,
                b: 58
            }},

            paper_bgcolor:
                "rgba(0,0,0,0)",

            plot_bgcolor:
                "rgba(0,0,0,0)",

            hovermode:
                "x unified",

            legend: {{
                orientation: "h",
                x: 0,
                y: 1.06
            }},

            xaxis: {{
                type: "date",
                showgrid: false
            }},

            yaxis: {{
                title: "排名",
                autorange: "reversed",
                dtick: 5,
                showgrid: true,
                gridcolor:
                    "rgba(148,163,184,.18)"
            }}

        }},

        {{
            responsive: true,
            displaylogo: false,
            modeBarButtonsToRemove: [
                "lasso2d",
                "select2d"
            ]
        }}
    );

}}


function updateCharts(data) {{

    if (data.length === 0)
        return;

    // 排名：最多补 1 天
    renderRankChart(data);

    const configs = [

        {{
            key: "play",
            id: "play_chart",
            title: "播放量"
        }},

        {{
            key: "subscribe",
            id: "subscribe_chart",
            title: "订阅数"
        }},

        {{
            key: "total_id",
            id: "total_id_chart",
            title: "全部ID数"
        }},

        {{
            key: "paid_id",
            id: "paid_id_chart",
            title: "付费ID数"
        }}

    ];

    configs.forEach(
        config => {{

            const column =
                MAPPING[config.key];

            if (!column)
                return;

            renderMetricChart(
                config.id,
                data,
                column,
                config.title,
                3
            );

        }}
    );

}}


// 页面首次加载
document.addEventListener(
    "DOMContentLoaded",
    function() {{

        applyDateRange();

    }}
);

</script>

</body>

</html>

"""

    with open(
        page_path,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(content)

    return page_filename


# ============================================================
# 21. 首页
#
# ★ 首页保存全部历史数据
# ★ 日期选择由 JS 动态计算
# ============================================================

def generate_sales_page(full_df, default_start, default_end):
    '''生成最终单页 Dashboard：index.html + data/sales.json。'''
    index_path = OUTPUT_DIR / "sales.html"
    data_dir = OUTPUT_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    def jsonable(v):
        if pd.isna(v):
            return None
        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (np.floating,)):
            return float(v)
        return v

    records = []
    for _, row in full_df.iterrows():
        item = {str(col): jsonable(row[col]) for col in full_df.columns}
        item["日期"] = str(row["日期"])
        item["首字母"] = get_initial(row["剧名"])
        records.append(item)

    payload = {
        "meta": {
            "data_start": str(full_df["日期"].min()),
            "data_end": str(full_df["日期"].max()),
            "default_start": default_start,
            "default_end": default_end,
            "drama_count": int(full_df["剧名"].nunique()),
            "record_count": int(len(full_df)),
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds")
        },
        "records": records
    }
    (data_dir / "sales.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8"
    )

    first_date = str(full_df["日期"].min())
    last_date = str(full_df["日期"].max())

    # 浏览器端完成全部历史筛选、汇总和图表；服务器只负责生成 JSON。
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>猫耳销量月榜 · Dashboard</title>
{HTML_CSS}
<style>
body{{background:#f5f7fb;color:#172033}}
.container{{max-width:1500px;margin:auto}}
.hero{{display:flex;justify-content:space-between;align-items:flex-end;gap:20px;margin-bottom:20px}}
.hero h1{{margin-bottom:6px}}
.hero p{{margin:0;color:#718096}}
.status{{font-size:12px;color:#667085;background:#fff;border:1px solid #e5e7eb;padding:8px 12px;border-radius:999px}}
.controls{{display:grid;grid-template-columns:repeat(5,minmax(150px,1fr));gap:14px;align-items:end}}
.filter-item label{{display:block;font-size:12px;color:#667085;margin-bottom:6px}}
.filter-item input,.filter-item select{{width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid #d9dee8;border-radius:10px;background:white}}
.kpis{{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin:18px 0}}
.kpi{{background:#fff;border:1px solid #e7eaf0;border-radius:14px;padding:16px;box-shadow:0 3px 12px rgba(15,23,42,.04)}}
.kpi .label{{font-size:12px;color:#667085}} .kpi .value{{font-size:26px;font-weight:700;margin-top:6px}}
.panel{{background:#fff;border:1px solid #e7eaf0;border-radius:14px;padding:18px;margin-bottom:18px;box-shadow:0 3px 12px rgba(15,23,42,.04)}}
.panel-head{{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px}}
.panel-head h2{{margin:0;font-size:17px}}
.table-wrap{{overflow:auto}}
table{{width:100%;border-collapse:collapse}} th,td{{padding:11px 10px;border-bottom:1px solid #edf0f5;text-align:left;white-space:nowrap}} th{{font-size:12px;color:#667085;background:#fafbfc;position:sticky;top:0}} td{{font-size:13px}}
.drama-link{{border:0;background:none;padding:0;color:#2563eb;cursor:pointer;font-weight:600;text-align:left}}
.badge{{display:inline-flex;align-items:center;padding:4px 8px;border-radius:999px;font-size:11px;background:#f1f5f9}}
.detail{{display:none;position:fixed;inset:0;background:rgba(15,23,42,.48);z-index:50;padding:24px;overflow:auto}}
.detail.open{{display:block}}
.detail-card{{max-width:1250px;margin:20px auto;background:#fff;border-radius:18px;padding:22px;box-shadow:0 20px 60px rgba(0,0,0,.2)}}
.detail-head{{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}}
.detail-title{{font-size:24px;font-weight:750;margin:0 0 6px}}
.close{{border:0;background:#f1f5f9;border-radius:10px;padding:9px 13px;cursor:pointer}}
.chart-grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}}
.chart{{height:380px}}
.metric-note{{font-size:12px;color:#667085;margin-top:6px}}
.empty{{padding:30px;text-align:center;color:#98a2b3}}
@media(max-width:1000px){{.controls{{grid-template-columns:repeat(2,1fr)}}.kpis{{grid-template-columns:repeat(2,1fr)}}.chart-grid{{grid-template-columns:1fr}}}}
@media(max-width:600px){{.hero{{display:block}}.controls{{grid-template-columns:1fr}}.kpis{{grid-template-columns:1fr 1fr}}.detail{{padding:8px}}.detail-card{{padding:14px}}}}
</style>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
</head>
<body>
<div class="container">
  <div class="hero">
    <div><h1>🎙️ 猫耳销量月榜跨期分析 Dashboard</h1><p>历史榜单 · 榜单状态 · 趋势 · 剧目指标</p></div>
    <div class="status" id="status">正在加载数据…</div>
  </div>

  <div class="panel">
    <div class="controls">
      <div class="filter-item"><label>开始日期</label><input id="startDate" type="date" min="{first_date}" max="{last_date}" value="{default_start}"></div>
      <div class="filter-item"><label>结束日期</label><input id="endDate" type="date" min="{first_date}" max="{last_date}" value="{default_end}"></div>
      <div class="filter-item"><label>排序方式</label><select id="sortSelect"><option value="days">在榜天数</option><option value="best">最高排名</option><option value="initial">剧名首字母</option><option value="last">当前排名</option></select></div>
      <div class="filter-item"><label>图表增量</label><select id="deltaMode"><option value="7">7日增量</option><option value="1">每日增量</option></select></div>
      <div class="filter-item"><label>剧目搜索</label><input id="search" placeholder="输入剧名…"></div>
    </div>
  </div>

  <div class="kpis">
    <div class="kpi"><div class="label">时间范围剧目</div><div class="value" id="totalDramas">—</div></div>
    <div class="kpi"><div class="label">稳定在榜</div><div class="value" id="stableCount">—</div></div>
    <div class="kpi"><div class="label">新晋榜单</div><div class="value" id="newCount">—</div></div>
    <div class="kpi"><div class="label">掉榜 / 闪现</div><div class="value" id="dropFlashCount">—</div></div>
    <div class="kpi"><div class="label">数据日期</div><div class="value" id="rangeText" style="font-size:16px">—</div></div>
  </div>

  <div class="panel">
    <div class="panel-head"><h2>剧目跨期汇总</h2><span id="resultCount" class="status"></span></div>
    <div class="table-wrap"><table><thead><tr><th>#</th><th>剧名</th><th>首字母</th><th>在榜天数</th><th>最高名次</th><th>最低名次</th><th>首次</th><th>当前</th><th>榜单状态</th><th>趋势</th></tr></thead><tbody id="summaryTable"></tbody></table></div>
  </div>
</div>

<div class="detail" id="detail">
  <div class="detail-card">
    <div class="detail-head"><div><div class="detail-title" id="detailTitle"></div><div class="metric-note" id="detailMeta"></div></div><button class="close" onclick="closeDetail()">关闭</button></div>
    <div class="chart-grid">
      <div class="panel"><div class="panel-head"><h2>播放量</h2></div><div id="chartViews" class="chart"></div></div>
      <div class="panel"><div class="panel-head"><h2>订阅数</h2></div><div id="chartSubs" class="chart"></div></div>
      <div class="panel"><div class="panel-head"><h2>全部集弹幕 UID</h2></div><div id="chartAllUid" class="chart"></div></div>
      <div class="panel"><div class="panel-head"><h2>付费集弹幕 UID</h2></div><div id="chartPaidUid" class="chart"></div></div>
    </div>
  </div>
</div>

<script>
let APP=null, CURRENT=null;
const $=id=>document.getElementById(id);
function initial(text){{
  text=(text??'').toString().trim(); if(!text) return '#';
  const c=text[0]; if(/[A-Za-z]/.test(c)) return c.toUpperCase();
  return '#';
}}
function num(v){{const n=Number(v); return Number.isFinite(n)?n:null}}
function inRange(d,s,e){{return d>=s&&d<=e}}
function rankStatus(rows,s,e){{
  const dates=[...new Set(rows.map(r=>r['日期']))].sort();
  if(!dates.length) return '闪现';
  const startsFirst=dates[0]===s; const endsLast=dates[dates.length-1]===e;
  if(startsFirst&&endsLast) return '稳定在榜';
  if(!startsFirst&&endsLast) return '新晋榜单';
  if(startsFirst&&!endsLast) return '掉榜';
  return '闪现';
}}
function dateDiff(a,b){{return Math.round((new Date(b)-new Date(a))/86400000)}}
function trendStatus(rows){{
  const rs=rows.filter(r=>num(r['排名'])!=null).sort((a,b)=>a['日期'].localeCompare(b['日期']));
  const ranks=rs.map(r=>num(r['排名'])); if(ranks.length<=1) return '波动';
  const changes=[]; for(let i=1;i<ranks.length;i++) changes.push(ranks[i]-ranks[i-1]);
  const positive=changes.filter(x=>x>0).length, negative=changes.filter(x=>x<0).length;
  const first=ranks[0], last=ranks[ranks.length-1];
  if(last===first) return '波动'; if(negative>0&&positive===0) return '上升'; if(positive>0&&negative===0) return '下降';
  if(Math.abs(last-first)<=2) return '波动'; if(last<first) return '上升'; if(last>first) return '下降'; return '波动';
}}
function buildSummary(filtered,s,e){{
  const map=new Map(); filtered.forEach(r=>{{const n=r['剧名']; if(!map.has(n))map.set(n,[]);map.get(n).push(r)}});
  const out=[]; for(const [drama,rows] of map){{
    rows.sort((a,b)=>a['日期'].localeCompare(b['日期'])); const ranks=rows.map(r=>num(r['排名'])).filter(v=>v!=null);
    out.push({{drama,initial:(rows.find(r=>r['首字母'])||{{}})['首字母']||initial(drama),days:new Set(rows.map(r=>r['日期'])).size,best:Math.min(...ranks),worst:Math.max(...ranks),first:ranks[0]??'—',last:ranks[ranks.length-1]??'—',rankStatus:rankStatus(rows,s,e),trendStatus:trendStatus(rows)}});
  }} return out;
}}
function badge(x){{return `<span class="badge">${{x}}</span>`}}
function sortSummary(a,type){{a.sort((x,y)=> type==='days' ? (y.days-x.days||x.best-y.best) : type==='best' ? (x.best-y.best||y.days-x.days) : type==='initial' ? (x.initial.localeCompare(y.initial,'zh-CN')||x.drama.localeCompare(y.drama,'zh-CN')) : ((Number(x.last)||999)-(Number(y.last)||999)||x.drama.localeCompare(y.drama,'zh-CN')))}}
function applyFilter(){{
  if(!APP)return; let s=$('startDate').value,e=$('endDate').value; if(s>e){{alert('开始日期不能晚于结束日期');return}}
  let filtered=APP.records.filter(r=>inRange(r['日期'],s,e)); const q=$('search').value.trim().toLowerCase(); if(q)filtered=filtered.filter(r=>String(r['剧名']).toLowerCase().includes(q));
  const summary=buildSummary(filtered,s,e); sortSummary(summary,$('sortSelect').value);
  $('totalDramas').textContent=summary.length; $('stableCount').textContent=summary.filter(x=>x.rankStatus==='稳定在榜').length; $('newCount').textContent=summary.filter(x=>x.rankStatus==='新晋榜单').length; $('dropFlashCount').textContent=summary.filter(x=>x.rankStatus==='掉榜'||x.rankStatus==='闪现').length; $('rangeText').textContent=s+' → '+e; $('resultCount').textContent=`${{summary.length}} 部`;
  $('summaryTable').innerHTML=summary.length?summary.map((x,i)=>`<tr><td>${{i+1}}</td><td><button class="drama-link" onclick='openDetail(${{JSON.stringify(x.drama)}})'>${{x.drama}}</button></td><td>${{x.initial}}</td><td>${{x.days}}</td><td>#${{x.best}}</td><td>#${{x.worst}}</td><td>#${{x.first}}</td><td>#${{x.last}}</td><td>${{badge(x.rankStatus)}}</td><td>${{badge(x.trendStatus)}}</td></tr>`).join(''):'<tr><td colspan="10" class="empty">该时间段没有数据</td></tr>';
}}
function prepare(rows,key){{
  const m=new Map(); rows.forEach(r=>{{const d=r['日期']; const v=num(r[key]); if(v!=null)m.set(d,v)}}); if(!m.size)return [];
  const ds=[...m.keys()].sort(); const start=new Date(ds[0]), end=new Date(ds[ds.length-1]); const arr=[]; for(let d=new Date(start);d<=end;d.setDate(d.getDate()+1)){{const iso=d.toISOString().slice(0,10);arr.push({{d:iso,v:m.has(iso)?m.get(iso):null}})}}
  for(let i=0;i<arr.length;i++){{if(arr[i].v==null){{let l=i-1,r=i+1;while(l>=0&&arr[l].v==null)l--;while(r<arr.length&&arr[r].v==null)r++;if(l>=0&&r<arr.length&&r-l-1<=3)arr[i].v=arr[l].v+(arr[r].v-arr[l].v)*(i-l)/(r-l)}}}}
  return arr;
}}
function drawChart(id,title,rows,key,mode){{
  const a=prepare(rows,key); const step=Number(mode); const base=a.map(x=>x.v); const delta=a.map((x,i)=>i>=step&&x.v!=null&&base[i-step]!=null?x.v-base[i-step]:null);
  const x=a.map(z=>z.d); Plotly.newPlot(id,[{{x,y:base,name:'累计值',mode:'lines',line:{{width:2}}}},{{x,y:delta,name:step===7?'7日增量':'每日增量',type:'bar',opacity:.45,yaxis:'y2'}}],{{title:{{text:title,font:{{size:14}}}},margin:{{l:50,r:50,t:45,b:45}},hovermode:'x unified',legend:{{orientation:'h'}},yaxis:{{title:'累计值'}},yaxis2:{{title:step===7?'7日增量':'每日增量',overlaying:'y',side:'right'}},xaxis:{{type:'date'}}}},{{responsive:true,displaylogo:false}});
}}
function openDetail(drama){{
  CURRENT=drama; const rows=APP.records.filter(r=>r['剧名']===drama).sort((a,b)=>a['日期'].localeCompare(b['日期'])); $('detailTitle').textContent=drama; $('detailMeta').textContent=`${{rows[0]?.['日期']||''}} → ${{rows[rows.length-1]?.['日期']||''}} · 图表当前使用 ${{$('deltaMode').value==='7'?'7日增量':'每日增量'}}`;
  const mode=$('deltaMode').value; drawChart('chartViews','播放量',rows,'播放量',mode); drawChart('chartSubs','订阅数',rows,'订阅数',mode); drawChart('chartAllUid','全部集弹幕 UID 数',rows,'全部集弹幕UID数',mode); drawChart('chartPaidUid','付费集弹幕 UID 数',rows,'付费集弹幕UID数',mode); $('detail').classList.add('open');
}}
function closeDetail(){{$('detail').classList.remove('open');}}
$('sortSelect').addEventListener('change',applyFilter); $('search').addEventListener('input',applyFilter); $('startDate').addEventListener('change',applyFilter); $('endDate').addEventListener('change',applyFilter); $('deltaMode').addEventListener('change',()=>{{if(CURRENT)openDetail(CURRENT)}}); $('detail').addEventListener('click',e=>{{if(e.target.id==='detail')closeDetail()}});
fetch('data/sales.json').then(r=>r.json()).then(data=>{{APP=data;$('status').textContent=`数据：${{data.meta.data_start}} → ${{data.meta.data_end}} · ${{data.meta.record_count.toLocaleString()}} 条`;applyFilter()}}).catch(err=>{{console.error(err);$('status').textContent='数据加载失败'}});
</script>
</body></html>'''
    index_path.write_text(html, encoding='utf-8')
    return str(index_path)

# ============================================================
# 22. 人气月榜 / 新品日榜页面 + 首页榜单选择
# ============================================================

def dataframe_payload(df):
    records=[]
    for _,row in df.iterrows():
        item={}
        for col in df.columns:
            value=row[col]
            if pd.isna(value): item[str(col)]=None
            elif isinstance(value,(np.integer,np.int64)): item[str(col)]=int(value)
            elif isinstance(value,(np.floating,np.float64)): item[str(col)]=float(value)
            else: item[str(col)]=str(value)
        item['日期']=str(row['日期']); records.append(item)
    return records


def generate_basic_rank_page(df,page_name,title,subtitle,json_name):
    if df is None or df.empty: return None
    data_dir=OUTPUT_DIR/'data'; data_dir.mkdir(parents=True,exist_ok=True); dates=sorted(df['日期'].unique())
    payload={'meta':{'data_start':dates[0],'data_end':dates[-1],'record_count':int(len(df)),'drama_count':int(df['剧名'].nunique()),'generated_at':datetime.datetime.now().isoformat(timespec='seconds')},'records':dataframe_payload(df)}
    (data_dir/json_name).write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    first,last=dates[0],dates[-1]
    active_pop='active' if json_name=='popularity.json' else ''; active_new='active' if json_name=='new.json' else ''
    page=f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>{html.escape(title)}</title>{HTML_CSS}<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script><style>
.nav{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px}}.nav a{{text-decoration:none;padding:9px 14px;border-radius:10px;background:#eef1ff;color:#4b56b8;font-weight:700;font-size:13px}}.nav a.active{{background:#5b67d8;color:white}}.controls{{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:14px;align-items:end}}.filter-item label{{display:block;font-size:12px;color:#667085;margin-bottom:6px}}.filter-item input,.filter-item select{{width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid #d9dee8;border-radius:10px;background:white}}.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:18px 0}}.kpi{{background:#fff;border:1px solid #e7eaf0;border-radius:14px;padding:16px}}.kpi .label{{font-size:12px;color:#667085}}.kpi .value{{font-size:26px;font-weight:700;margin-top:6px}}.panel{{background:#fff;border:1px solid #e7eaf0;border-radius:14px;padding:18px;margin-bottom:18px;box-shadow:0 3px 12px rgba(15,23,42,.04)}}.table-wrap{{overflow:auto}}table{{width:100%;border-collapse:collapse}}th,td{{padding:11px 10px;border-bottom:1px solid #edf0f5;text-align:left;white-space:nowrap}}th{{font-size:12px;color:#667085;background:#fafbfc;position:sticky;top:0}}td{{font-size:13px}}.chart{{height:390px}}.muted{{font-size:12px;color:#718096}}@media(max-width:900px){{.controls{{grid-template-columns:1fr 1fr}}.kpis{{grid-template-columns:1fr 1fr}}}}@media(max-width:600px){{.controls,.kpis{{grid-template-columns:1fr}}}}
</style></head><body><div class="container"><div class="header"><h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></div><div class="nav"><a href="index.html">榜单选择</a><a href="sales.html">销量月榜</a><a href="popularity.html" class="{active_pop}">人气月榜</a><a href="new.html" class="{active_new}">新品日榜</a></div><div class="panel"><div class="controls"><div class="filter-item"><label>开始日期</label><input id="start" type="date" min="{first}" max="{last}" value="{first}"></div><div class="filter-item"><label>结束日期</label><input id="end" type="date" min="{first}" max="{last}" value="{last}"></div><div class="filter-item"><label>排序</label><select id="sort"><option value="days">在榜天数</option><option value="best">最高排名</option><option value="name">剧名</option></select></div><div class="filter-item"><label>搜索</label><input id="search" placeholder="输入剧名…"></div></div></div><div class="kpis"><div class="kpi"><div class="label">剧目数</div><div class="value" id="dramas">—</div></div><div class="kpi"><div class="label">记录数</div><div class="value" id="records">—</div></div><div class="kpi"><div class="label">数据日期</div><div class="value" id="days">—</div></div><div class="kpi"><div class="label">最高排名剧目</div><div class="value" id="bestDrama" style="font-size:16px">—</div></div></div><div class="panel"><div class="panel-head"><h2>大盘趋势</h2></div><div id="chart" class="chart"></div><div class="muted">累计播放量 / 订阅数；缺失日期不视为 0，图表仅对短内部缺口做线性插值。</div></div><div class="panel"><div class="panel-head"><h2>剧目跨期汇总</h2></div><div class="table-wrap"><table><thead><tr><th>#</th><th>剧名</th><th>在榜天数</th><th>最高排名</th><th>最低排名</th><th>首次上榜</th><th>最后在榜</th></tr></thead><tbody id="table"></tbody></table></div></div></div><script>
const DATA={json.dumps(payload,ensure_ascii=False,separators=(',',':'))};const $=id=>document.getElementById(id);const num=v=>{{const n=Number(v);return Number.isFinite(n)?n:null}};
function summary(rows){{const m=new Map();rows.forEach(r=>{{if(!m.has(r['剧名']))m.set(r['剧名'],[]);m.get(r['剧名']).push(r)}});return [...m].map(([name,a])=>{{a.sort((x,y)=>x['日期'].localeCompare(y['日期']));const ranks=a.map(x=>num(x['排名'])).filter(x=>x!=null);return {{name,days:new Set(a.map(x=>x['日期'])).size,best:Math.min(...ranks),worst:Math.max(...ranks),first:a[0]['日期'],last:a[a.length-1]['日期']}}}})}}
function series(rows,key){{const m=new Map();rows.forEach(r=>{{const v=num(r[key]);if(v!=null)m.set(r['日期'],v)}});if(!m.size)return[];const ds=[...m.keys()].sort();const out=[];for(let d=new Date(ds[0]);d<=new Date(ds.at(-1));d.setDate(d.getDate()+1)){{const k=d.toISOString().slice(0,10);out.push({{x:k,y:m.has(k)?m.get(k):null}})}}for(let i=0;i<out.length;i++)if(out[i].y==null){{let l=i-1,r=i+1;while(l>=0&&out[l].y==null)l--;while(r<out.length&&out[r].y==null)r++;if(l>=0&&r<out.length&&r-l-1<=3)out[i].y=out[l].y+(out[r].y-out[l].y)*(i-l)/(r-l)}}return out}}
function render(){{let s=$('start').value,e=$('end').value,rows=DATA.records.filter(r=>r['日期']>=s&&r['日期']<=e);const q=$('search').value.trim().toLowerCase();if(q)rows=rows.filter(r=>String(r['剧名']).toLowerCase().includes(q));let sm=summary(rows);const sort=$('sort').value;sm.sort((a,b)=>sort==='days'?b.days-a.days:sort==='best'?a.best-b.best:a.name.localeCompare(b.name,'zh-CN'));$('dramas').textContent=sm.length.toLocaleString();$('records').textContent=rows.length.toLocaleString();$('days').textContent=s+' → '+e;$('bestDrama').textContent=sm.length?sm.slice().sort((a,b)=>a.best-b.best)[0].name:'—';$('table').innerHTML=sm.length?sm.map((x,i)=>`<tr><td>${{i+1}}</td><td>${{x.name}}</td><td>${{x.days}}</td><td>#${{x.best}}</td><td>#${{x.worst}}</td><td>${{x.first}}</td><td>${{x.last}}</td></tr>`).join(''):'<tr><td colspan="7">该时间段没有数据</td></tr>';const pv=series(rows,'播放量'),sub=series(rows,'订阅数');Plotly.newPlot('chart',[{{x:pv.map(x=>x.x),y:pv.map(x=>x.y),name:'播放量',mode:'lines'}},{{x:sub.map(x=>x.x),y:sub.map(x=>x.y),name:'订阅数',mode:'lines',yaxis:'y2'}}],{{hovermode:'x unified',margin:{{l:60,r:60,t:20,b:45}},yaxis:{{title:'播放量'}},yaxis2:{{title:'订阅数',overlaying:'y',side:'right'}},xaxis:{{type:'date'}}}},{{responsive:true,displaylogo:false}})}}
['start','end','sort','search'].forEach(id=>$(id).addEventListener('input',render));render();</script></body></html>'''
    path=OUTPUT_DIR/page_name; path.write_text(page,encoding='utf-8'); return str(path)


def generate_home_page(available):
    cards=[]
    for _,title,desc,file in available:
        cards.append(f'<a href="{file}" style="text-decoration:none;background:white;border:1px solid #e7ebf2;border-radius:18px;padding:24px;box-shadow:0 8px 28px rgba(28,39,72,.07);color:#172033"><div style="font-size:22px;font-weight:750">{html.escape(title)}</div><div style="margin-top:8px;color:#718096;font-size:13px">{html.escape(desc)}</div></a>')
    content=f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>猫耳榜单分析</title>{HTML_CSS}</head><body><div class="container"><div class="header"><h1>🎙️ 猫耳广播剧榜单分析</h1><p>销量月榜 · 人气月榜 · 新品日榜</p></div><div style="display:grid;grid-template-columns:repeat(3,1fr);gap:18px">{''.join(cards)}</div><div class="footer">数据持续按日积累；缺失日期与重复版本由构建程序自动处理。</div></div></body></html>'''
    path=OUTPUT_DIR/'index.html';path.write_text(content,encoding='utf-8');return str(path)


# ============================================================
# 22. 生成 Excel
#
# ★ Excel 只记录指定时间段
# ★ 这里在 Python 中完成
# ============================================================

def generate_excel(
    filtered_df,
    summary,
    start_date,
    end_date
):

    filename = (
        "猫耳销量月榜跨期分析_"
        f"{start_date.replace('-', '')}_"
        f"{end_date.replace('-', '')}.xlsx"
    )

    path = os.path.join(
        str(EXPORT_DIR),
        filename
    )

    # --------------------------------------------------------
    # 每日排名
    # --------------------------------------------------------

    ranking_columns = [
        "日期",
        "排名",
        "剧名"
    ]

    ranking_df = (
        filtered_df[
            ranking_columns
        ]
        .copy()
        .sort_values(
            [
                "日期",
                "排名"
            ]
        )
    )

    # --------------------------------------------------------
    # 剧目汇总
    # --------------------------------------------------------

    summary_excel = (
        summary
        .copy()
        .sort_values(
            [
                "在榜天数",
                "最高排名"
            ],
            ascending=[
                False,
                True
            ]
        )
    )

    # --------------------------------------------------------
    # 写入
    # --------------------------------------------------------

    with pd.ExcelWriter(
        path,
        engine="openpyxl"
    ) as writer:

        ranking_df.to_excel(
            writer,
            sheet_name="每日排名",
            index=False
        )

        summary_excel.to_excel(
            writer,
            sheet_name="剧目汇总",
            index=False
        )

    return path


# ============================================================
# 23. 清理旧 HTML
# ============================================================

def clean_output_directory():

    if not os.path.exists(
        OUTPUT_DIR
    ):

        os.makedirs(
            OUTPUT_DIR
        )

        return

    for name in os.listdir(
        OUTPUT_DIR
    ):

        path = os.path.join(
            OUTPUT_DIR,
            name
        )

        try:

            if os.path.isfile(path):

                os.remove(path)

            elif os.path.isdir(path):

                shutil.rmtree(path)

        except Exception as e:

            print(
                f"⚠️ 无法删除：{path}"
            )

            print(
                e
            )


# ============================================================
# 24. 运行分析
# ============================================================

def run_analysis():
    sales_df=load_sales_rank_data(); popularity_df=load_popularity_rank_data(); new_df=load_new_rank_data()
    if sales_df is None and popularity_df is None and new_df is None:
        print('❌ 三个榜单都没有有效数据。'); return None
    clean_output_directory(); available=[]; excel_path=None
    if sales_df is not None and not sales_df.empty:
        dates=sorted(sales_df['日期'].unique()); latest=pd.to_datetime(dates[-1]); earliest=pd.to_datetime(dates[0]); default_start=max(earliest,latest-pd.Timedelta(days=DEFAULT_DAYS-1)).strftime('%Y-%m-%d'); default_end=latest.strftime('%Y-%m-%d')
        generate_sales_page(sales_df,default_start,default_end); available.append(('sales','销量月榜',f'{dates[0]} → {dates[-1]} · Top 50 深度分析','sales.html'))
        start_date=os.environ.get('ANALYSIS_START',default_start); end_date=os.environ.get('ANALYSIS_END',default_end); filtered=sales_df[(sales_df['日期']>=start_date)&(sales_df['日期']<=end_date)].copy()
        if filtered.empty: filtered=sales_df.copy(); start_date=default_start; end_date=default_end
        summary=build_summary(filtered,filtered['日期'].min(),filtered['日期'].max()); excel_path=generate_excel(filtered,summary,start_date,end_date)
    if popularity_df is not None and not popularity_df.empty:
        dates=sorted(popularity_df['日期'].unique()); generate_basic_rank_page(popularity_df,'popularity.html','猫耳人气月榜','Top 100 · 排名 / 播放量 / 订阅数历史分析','popularity.json'); available.append(('popularity','人气月榜',f'{dates[0]} → {dates[-1]} · Top 100','popularity.html'))
    if new_df is not None and not new_df.empty:
        dates=sorted(new_df['日期'].unique()); generate_basic_rank_page(new_df,'new.html','猫耳新品日榜','Top 30 · 排名 / 播放量 / 订阅数历史分析','new.json'); available.append(('new','新品日榜',f'{dates[0]} → {dates[-1]} · Top 30','new.html'))
    generate_home_page(available)
    metadata={'updated_at':datetime.datetime.now().isoformat(timespec='seconds'),'boards':[x[0] for x in available],'architecture':'separate-fetch-and-build'}
    (OUTPUT_DIR/'build-info.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    print('🎉 GitHub Pages 网站构建完成'); print(f'🌐 网站目录：{OUTPUT_DIR}');
    if excel_path: print(f'📊 Excel：{excel_path}')
    return {'sales':sales_df,'popularity':popularity_df,'new':new_df,'excel_path':excel_path}


# ============================================================
# 25. 执行
# ============================================================

if __name__ == "__main__":
    result = run_analysis()