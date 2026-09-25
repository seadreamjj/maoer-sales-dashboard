# mimi销量月榜自动化 Dashboard

这是基于《mimi销量月榜跨期分析系统 V2》的 GitHub Actions + GitHub Pages 版本。

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

