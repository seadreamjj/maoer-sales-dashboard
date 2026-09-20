# 猫耳销量月榜自动化 Dashboard

这是基于《猫耳销量月榜跨期分析系统 V2》的 GitHub Actions + GitHub Pages 版本。

## 自动化链路

每天北京时间 08:10：

1. GitHub Actions 启动
2. `fetch_rank.py` 请求猫耳月榜 Top 50
3. 逐剧获取播放量、订阅数、宣发策略、总集数、付费集数、全部集弹幕 UID、付费集弹幕 UID
4. 当天数据保存到 `data/raw/猫耳销量月榜YYYYMMDD.csv`
5. `build_site.py` 读取全部历史 CSV，运行 V2 跨期分析
6. 生成单页 Dashboard：`site/index.html`
7. 生成前端数据：`site/data/sales.json`
8. GitHub Pages 自动发布
9. 当天 CSV 自动提交回仓库，供下一次运行使用

因此不需要每天开电脑，也不需要每天运行 Colab。

## 第一次设置

### 1. 创建 GitHub Repository

建议使用 Public repository，以便使用 GitHub Free 的公开仓库 Actions + Pages 工作流。

### 2. 上传整个项目

仓库根目录应该直接包含：

```text
fetch_rank.py
build_site.py
requirements.txt
.github/workflows/deploy.yml
data/raw/
```

### 3. 设置猫耳 Cookie

不要把 Cookie 写入 `fetch_rank.py`。

进入：

`Settings → Secrets and variables → Actions → Secrets → New repository secret`

创建：

```text
Name: MAOER_COOKIE
Value: 你的猫耳 Cookie
```

Cookie 只通过 GitHub Actions Secret 注入运行环境。

### 4. 开启 GitHub Pages

进入：

`Settings → Pages → Build and deployment → Source → GitHub Actions`

然后在：

`Actions → 猫耳月榜自动抓取与 Dashboard 更新 → Run workflow`

手动运行一次。

## 日常运行

默认每天北京时间 08:10 自动运行。

也可以随时手动 `Run workflow`。

## 增量图表

Dashboard 支持手动切换：

- **7日增量**：当天值 − 7 个自然日前的值
- **每日增量**：当天值 − 前一天的值

播放量、订阅数、全部集弹幕 UID、付费集弹幕 UID 四组图表会同步切换。

## 数据口径

`fetch_rank.py` 沿用原始 Colab 抓取代码的核心口径：

- 月榜接口：`type=9&sub_type=3`
- Top 50
- 付费集：`need_pay != 0`
- 全部集弹幕 UID：所有集 UID 去重
- 付费集弹幕 UID：付费集 UID 去重
- 弹幕留存率：付费集弹幕 UID / 全部集弹幕 UID
- 收订比：付费集弹幕 UID / 订阅数

## 容错

- HTTP 429 / 5xx：自动有限重试并遵守服务端 `Retry-After`（如果返回）
- 单集弹幕请求失败：该集返回空 UID，不让整部剧直接中断
- 单部剧失败：继续抓后面的剧，并写入 `logs/`
- Top 50 全部失败：workflow 失败，不生成空数据覆盖历史
- Cookie 不打印到 Actions 日志

## 重要：Cookie 安全

不要把真实 Cookie 提交到 GitHub 文件、Issue、README、CSV 或日志中。

如果 Cookie 已经公开暴露，建议立即更换/重新获取后再放入 `MAOER_COOKIE` Secret。

## 关于历史数据

每天成功抓取的 CSV 会提交到 `data/raw/`，因此跨期分析可以持续累积历史数据。

这些 CSV 如果仓库是 Public，也会成为公开仓库内容。若你不希望公开历史原始数据，需要改成外部存储或私有数据方案，而不能直接把原始 CSV 提交到公开仓库。
