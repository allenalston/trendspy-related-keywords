# TrendSpy Related Keywords Monitor

[English](README_EN.md) | 简体中文

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/allenalston/trendspy-related-keywords/actions/workflows/ci.yml/badge.svg)](https://github.com/allenalston/trendspy-related-keywords/actions/workflows/ci.yml)

一个轻量、可自托管的 **Google Trends 相关飙升词（Rising Related Queries）监控工具**。

专注把一件事做到极致：**固定词根 → 可靠采集 → 历史去重 → 每日一封低噪音日报**。

---

## 核心特性

- **零门槛上手 + 场景词根预设**：默认生成本地 Markdown / HTML / CSV 报告，不配邮箱也能 3 分钟出结果；内置 `saas-tools`、`ai-products`、`ecommerce` 等经过验证的词根预设（`trends-monitor init --preset saas-tools`）。
- **精准降噪（告别泛词和垃圾词）**：支持**单词根 Google Trends 行业分类 `cat`**（例如给 `Python` 指定 `cat: 31` 编程分类，彻底过滤“蟒蛇”）、**正则黑白名单过滤**与**最小词数限制**。
- **跨天去重 + 零成本趋势动量标签**：内置单文件 SQLite 历史库，优先高亮 **✨ 今日新发现飙升词（New）**，并零额外请求自动计算 **🔥 连续飙升天数（Streak）** 与 **🚀 加速信号**；每条词附带 **Trends · Google · Exact** 一键验证直达链接。
- **稳健防 429 与分片断点续跑**：支持**多代理自动轮换（`TRENDS_PROXIES`）**、**分片采集（`--limit N` 配合 `--resume`）**、有限次指数退避重试，以及可选商业数据源 **`provider: serpapi`**（重度用户填 Key 即享 0 限流）。
- **合并单封精美日报 & 零服务器部署**：一次采集只发**一封**汇总邮件（自动兼容 `465 SSL` 与 `587 STARTTLS`），支持飞书 / 企业微信 / 通用 JSON Webhook，内置 GitHub Actions / Docker / `systemd` 模板。

---

## 5 分钟快速开始

### 1. 安装

推荐使用 `uv` 或标准 `venv`（需要 Python 3.10+）：

```bash
git clone https://github.com/allenalston/trendspy-related-keywords.git
cd trendspy-related-keywords

# 方式 A：使用 venv + pip
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .

# 方式 B：使用 uv
uv sync
```

### 2. 不改配置，立即试用一次

```bash
trends-monitor run -k AI -k Python --timeframe "now 7-d"
```

运行完成后，终端会输出采集统计，同时在 `data/YYYY-MM-DD/` 下生成：
- `digest_YYYY-MM-DD.md`（Markdown 日报）
- `digest_YYYY-MM-DD.html`（可在浏览器直接打开的图文日报）
- `daily_report_YYYY-MM-DD.csv`（完整结构化数据）
- `raw/related_queries_*.json`（单词根原始数据）

### 3. 初始化正式配置（支持场景预设）

```bash
# 查看内置词根与降噪预设（default / saas-tools / ai-products / ecommerce）
trends-monitor init --list-presets

# 例如：用工具站/独立开发需求词根预设初始化
trends-monitor init --preset saas-tools
```

这会在当前目录生成：
- `config.yaml`：维护监控词根（支持为单个词根配独立 `cat` 分类 / `geo` / `timeframe`）、过滤规则、限流策略和通知开关。
- `.env`：存放敏感信息（代理池、SerpApi Key、SMTP 密码、Webhook URL），已被 `.gitignore` 忽略。

验证配置与连通性：

```bash
# 校验配置、SQLite 存储与已启用的通知渠道
trends-monitor check

# 额外执行一次真实 Google Trends 1 词连通性探测
trends-monitor check --live
```

---

## 常用命令

| 命令 | 说明 |
| --- | --- |
| `trends-monitor init [--preset saas-tools]` | 使用内置预设生成 `config.yaml` 和 `.env`（`--list-presets` 查看全部） |
| `trends-monitor run` | 按配置执行一次完整采集、去重、过滤并发送日报 |
| `trends-monitor run -k Python --geo US --cat 31` | 临时指定词根、地区和行业分类运行（支持重复 `-k`） |
| `trends-monitor run --limit 15` | 分片采集：本次最多跑 15 个词根，剩余留作 pending 供下次 `--resume` |
| `trends-monitor run --resume` | 从上一次中断、分片或部分失败的任务继续，只补跑未成功词根 |
| `trends-monitor run --no-notify` | 仅采集并输出本地报告，跳过邮件和 Webhook 推送 |
| `trends-monitor check [--live]` | 检查配置、数据源 Provider、SMTP 登录、Webhook 与 Trends 连通性 |
| `trends-monitor notify [--date YYYY-MM-DD]` | 不重新抓数据，直接从历史库重发某天日报 |
| `trends-monitor history --min-streak 2 --new-only` | 在终端筛选连续飙升或新发现历史词（支持 `--export out.csv`） |

---

## 配置说明

完整注释见 [`config.example.yaml`](config.example.yaml) 和 [`.env.example`](.env.example)。

### 通知渠道（全部可选）

| 渠道 | `config.yaml` 开关 | `.env` 环境变量 |
| --- | --- | --- |
| 本地报告 (MD/HTML) | `notifications.local.enabled: true` | 无需配置 |
| 邮件 (SMTP SSL / STARTTLS) | `notifications.email.enabled: true` | `TRENDS_SMTP_SERVER`, `TRENDS_SMTP_PORT`, `TRENDS_SENDER_EMAIL`, `TRENDS_SENDER_PASSWORD`, `TRENDS_RECIPIENT_EMAIL` |
| 飞书群机器人 | `notifications.feishu.enabled: true` | `TRENDS_FEISHU_WEBHOOK` |
| 企业微信群机器人 | `notifications.wecom.enabled: true` | `TRENDS_WECOM_WEBHOOK` |
| 通用 JSON Webhook (n8n/Zapier 等) | `notifications.webhook.enabled: true` | `TRENDS_WEBHOOK_URL` |

> **SMTP 端口说明**：`TRENDS_SMTP_PORT=465` 会自动使用 `SMTP_SSL`（适合 QQ、163、阿里云企业邮箱）；`587` 会自动使用 `SMTP + STARTTLS`（适合 Gmail 应用专用密码）。多收件人用英文逗号分隔。

---

## 定时运行与部署方案

本工具是**短时批处理任务**（无需 24 小时常驻监听端口、内存占用 < 100MB、状态仅为一个 SQLite 文件），选择部署环境时主要权衡**成本、SQLite 持久化与出口 IP 触发 Google 429 的概率**：

| 部署位置 | 费用 | 429 风险 | 跨天去重持久化 | 适合人群 |
| --- | --- | --- | --- | --- |
| **GitHub Actions**（已内置模板） | 免费 | 中高（Azure 机房 IP，少量词可用，词多建议配代理） | 内置 Cache 自动恢复 | 新手 / 无服务器用户，快速零成本试跑 |
| **本机 / Mac mini / NAS / 树莓派** | 免费 | **最低**（家庭宽带或稳定个人网络，Google 最友好） | 天然本地持久化 | **最推荐自用**（适合有常开机设备的用户） |
| **海外轻量 VPS**（配 `systemd` / Docker） | 约 $3–5/月 | 中（机房 IP，需控频或配代理） | 天然本地持久化 | 长期监控 30+ 词根的重度用户 |
| **PaaS Cron**（Railway / Render / Zeabur 等） | 免费起 | 中（机房 IP） | 需挂载持久卷存 SQLite | 不想折腾 Linux 运维的开发者 |
| **青龙面板**（若已有） | 免费 | 取决于宿主机网络 | 天然本地持久化 | 已有青龙定时面板的 NAS / VPS 用户 |

> **选型提示**：
> - 不建议部署在无状态、有短超时限制的 Serverless 平台（如 Vercel / Cloudflare Pages），因为多词限流等待通常需要数分钟。
> - 无论部署在哪里，如果词根较多（30+）开始频繁遇到 429，在 `.env` 或 GitHub Secrets 中配置住宅/稳定代理 `TRENDS_PROXY=...` 即可明显改善。

### 方案 A：GitHub Actions（免费、零服务器）

项目已内置 [`.github/workflows/daily-monitor.yml`](.github/workflows/daily-monitor.yml)：

1. Fork 本仓库。
2. 将 `config.example.yaml` 复制为 `config.yaml` 并修改你的关键词与通知开关，提交到你自己的仓库（建议先从 `.gitignore` 移除 `config.yaml` 或设为私有仓库）。
3. 在 GitHub 仓库的 **Settings → Secrets and variables → Actions** 中按需添加 Secrets（如 `TRENDS_SMTP_SERVER`、`TRENDS_SENDER_EMAIL`、`TRENDS_SENDER_PASSWORD`、`TRENDS_RECIPIENT_EMAIL`、`TRENDS_FEISHU_WEBHOOK`、`TRENDS_PROXY` 等）。
4. 在 Actions 页面手动点击 **Run workflow** 测试一次；之后每天会自动定时运行，并通过 Actions Cache 自动持久化 `data/trends_history.sqlite3` 以支持跨天去重，同时将每日报告保存为 30 天可下载 Artifact。

### 方案 B：Docker / Docker Compose

```bash
cp config.example.yaml config.yaml
cp .env.example .env
docker compose run --rm trends-monitor
```

配合宿主机 `crontab` 每天定时触发即可。

### 方案 C：Linux `systemd` Timer

项目提供了现成模板：[`deploy/systemd/trends-monitor.service`](deploy/systemd/trends-monitor.service) 与 [`deploy/systemd/trends-monitor.timer`](deploy/systemd/trends-monitor.timer)（自带 15 分钟随机延迟，避免固定整点请求）。

---

## 关于数据指标与 HTTP 429 的说明

1. **正确理解指标语义**：
   - **Rising 百分比（如 `+1200%` 或 `Breakout`）** 是 Google Trends 在当前时间窗口内的**相对增长信号**，不等于绝对搜索量、SEO 竞争难度或商业价值。
   - **New 标记** 表示该相关词**首次被本工具记录**（或在超过 `dedup_days` 去重窗口后再次出现），不代表它首次出现在互联网。
2. **应对 Google Trends 429 限流**：
   - 默认推荐 `timeframe: "now 7-d"` 或 `"now 1-d"`（自定义短日期范围有时会返回空的 `rising` 列表）。
   - 如果词根数量较多（例如 30~100 个），建议适当调大 `rate_limit.min_delay_seconds` / `batch_interval_seconds`，或在 `.env` 中配置住宅/稳定代理 `TRENDS_PROXY=http://...`。
   - 即使部分词触发 429，本工具会记录失败详情并继续跑完其余词根；稍后执行 `trends-monitor run --resume` 即可只补跑失败的词根。

---

## 从 v0.1.0 升级说明

- 原始脚本版本已通过 Git Tag [`v0.1.0`](https://github.com/allenalston/trendspy-related-keywords/releases/tag/v0.1.0) 完整归档，老用户可随时切换回旧版。
- **为什么移除了旧版 `itchat-uos` 个人微信登录？** 微信网页版/UOS 协议目前风控极严，普遍存在无法登录或封号风险。v0.2.0 改为零封号风险的**企业微信机器人、飞书机器人、通用 Webhook 与单封汇总邮件**。
- 配置文件从修改 `config.py` 源码改为独立的 `config.yaml` + `.env`。

---

## 开发与贡献

欢迎提交 Issue 和 PR！详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

```bash
pip install -e ".[dev]"
ruff check src tests
pytest
```

## License

本项目基于 [MIT License](LICENSE) 开源。
