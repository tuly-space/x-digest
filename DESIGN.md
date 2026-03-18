# X Digest — 设计文档

> 自动化 X/Twitter 信息流精炼系统：从 For You timeline 抓取 → LLM 分类 → 过滤去重 → 推送 Discord → 反向训练推荐算法

## 1. 解决什么问题

jamie 需要跟踪 timeline 动态，但 For You timeline 噪声太多（营销、情绪宣泄、无实质内容的 hype）。每天手动刷浪费时间，且没有任何机制优化推荐质量。

**目标：** 每小时自动生成一份精华 digest，同时反向训练 X 推荐算法，形成正循环。

## 2. 系统架构

### 数据流（单次 Playwright session）

```
Chrome (CDP :18800) ← jamie 的 ~/chrome-profile，已登录
        │
        ▼
scrape_and_process.py  ← 核心脚本，一次性完成 scrape + classify + mark
  ┌─────────────────────────────────────────────────┐
  │  for each scroll screen (15 rounds):            │
  │    1. 提取当屏新 tweet articles（还在 DOM 里）  │
  │    2. batch LLM classify（codex exec）           │
  │    3. 立即 like quality 推文（还在 DOM）         │
  │    3b. 立即 mark spam 推文 "Not interested"      │
  │    4. scroll to next screen                     │
  └─────────────────────────────────────────────────┘
        │ JSON stdout (全部 tweets，带 verdict 字段)
        ▼
auto_follow.py          ← 自动关注 quality 作者（最多 5/run）
        │
        ▼
filter_digest.py        ← 只取 verdict=quality，去重（seen_links.txt），排序
        │ Markdown
        ▼
digests/YYYY-MM-DD_HH.md → git commit + push
        │
        ▼
Discord forum #tweets（ID: 1483709877674053653）
  → 每小时一个 thread: "X Digest YYYY-MM-DD HH:00 UTC"
```

### 为什么 scrape + classify + mark 必须交叠

X timeline 在页面滚动时会卸载已滚出视口的 DOM 节点。如果先全量抓取再回头 mark，目标 article 已经不存在了。交叠方案（每屏抓完立即 mark）解决了这个问题。

## 3. 核心组件

### 3.1 scrape_and_process.py

**职责：** 一个 Playwright session 完成抓取 + LLM 分类 + spam 标记

**关键参数：**

| 参数 | 值 | 说明 |
|---|---|---|
| `SCROLL_ROUNDS` | 15 | 滚动轮次 |
| `SCROLL_PX` | 900 | 每轮滚动像素 |
| `SCROLL_WAIT_MS` | 1800 | 每轮等待（让推文加载） |
| `MAX_MARKS_PER_RUN` | 5 | 单次最多标记 spam 条数 |
| `MAX_LIKES_PER_RUN` | 10 | 单次最多 like 条数 |
| `LLM_MODEL` | `gpt-5.4-mini` | 分类用模型（codex exec） |

**handle 提取：** 直接从 tweet 链接的 href（`/username/status/xxx`）提取，不从 User-Name textContent 提取，避免带入时间戳（`· 17h`）等噪声。

**LLM 分类：** 把当屏所有 tweets 拼成批量 prompt，一次 `codex exec` 调用返回每条的 verdict（quality/spam/skip）。

**LLM 判定标准：**
- **quality** — 产品思考、工程实践、商业分析、AI agent/LLM 深度思考、有实质内容的创始人叙事
- **spam** — 营销推广、情绪宣泄、无实质内容的 hype、送礼活动、自我推销
- **skip** — 其他

**输出：** JSON 数组（stdout），每条带 `verdict` 字段。

### 3.2 auto_follow.py

**职责：** 自动关注 quality 推文的作者（如果还没关注）

- 从 stdin 读 classified JSON
- 取 quality 作者，去重，最多关注 5 个/run
- 访问 `x.com/@handle` profile 页，检查关注状态，点击 Follow
- handle 做了 fallback 清洗（`split("·")[0]`），兼容脏数据

### 3.3 filter_digest.py

**职责：** 过滤、去重、排序，输出 Markdown digest

**过滤管线：**
1. 只保留 `verdict=quality` 的推文
2. 跨轮次去重：检查 `seen_links.txt`，跳过上次 digest 已出现的链接
3. 按 engagement 打分排序，取 top N

**排序算法：**
```
score = (likes + retweets × 3 + replies × 2) × min(text_length / 280, 1.5)
```

**用法：**
```bash
cat classified.json | uv run python filter_digest.py --seen-file seen_links.txt
```

### 3.4 run_digest.sh

**职责：** 编排整个流程

```
Step 1-2-4 (interleaved): scrape_and_process.py → $CLASSIFIED (JSON)
Step 3: auto_follow.py（允许失败）
Step 5: filter_digest.py → $DIGEST (Markdown)
Step 6: 保存到 digests/YYYY-MM-DD_HH.md
Step 7: git add + commit + push
Step 8: echo $DIGEST（供 cron agent 读取并发帖）
```

**注意：** Discord 发帖（forum thread-create）目前由 cron agent 的 payload 配置完成，run_digest.sh 只负责输出 Markdown 正文。

## 4. 文件结构

```
projects/x-digest/
├── DESIGN.md                # 本文档
├── README.md                # 项目简介
├── scrape_and_process.py    # 核心：scrape + LLM classify + mark（交叠）
├── auto_follow.py           # 自动关注 quality 作者
├── filter_digest.py         # 过滤 + 排序 + 格式化
├── run_digest.sh            # 编排脚本（cron 入口）
├── seen_links.txt           # 跨轮次去重记录（本地，不进 git）
├── digests/                 # 历史存档（git tracked）
│   └── YYYY-MM-DD_HH.md
│
│   # 旧版脚本（保留，不再在主流程中使用）
├── scrape_timeline.py       # 旧：独立 scrape（不含 classify/mark）
├── llm_classify.py          # 旧：独立 LLM 分类
└── mark_not_interested.py   # 旧：独立 mark（有 timeline 已滚走的问题）
```

**GitHub repo:** `tuly-space/x-digest`（private）

## 5. 依赖

| 依赖 | 用途 |
|---|---|
| Python 3.13 + uv | 运行时 |
| playwright | 浏览器自动化（`uv run --with playwright`） |
| Chrome @ :18800 | 已登录 X 的 Chrome，`~/chrome-profile` |
| codex CLI | LLM 分类（`codex exec --model gpt-5.4-mini`） |
| OpenClaw cron | 定时调度，每小时一次 |
| git | digest 归档到 GitHub |

## 6. 迭代方向

### 近期
- [ ] **run_digest.sh 直接发帖** — 把 forum thread-create 写进 shell 脚本，不依赖 cron agent payload
- [ ] **quality 阈值调优** — 观察实际 digest 质量，调整 LLM prompt 严格程度
- [ ] **自动关注改进** — 识别已关注（Following 状态）避免重复尝试

### 中期
- [ ] **jamie 反馈回路** — Discord 某条 ❤️ → 记录偏好 → 调整 LLM 评判权重
- [ ] **每日汇总** — 每天 23:00 CST 从当天 hourly digest 中再提炼 daily top 10
- [ ] **知识库联动** — quality tweets 自动录入 `projects/knowledge-base/`

### 长期
- [ ] **Newsletter** — 周度从 daily top 10 生成，加 tuly 评论
- [ ] **多源聚合** — Hacker News、Reddit、arXiv

## 7. 运维

**手动触发：**
```bash
cd projects/x-digest && bash run_digest.sh
```

**查 cron 状态：**
```bash
openclaw cron list
openclaw cron runs x-digest
```

**Chrome 挂了：**
```bash
DISPLAY=:99 /opt/google/chrome/chrome --user-data-dir="$HOME/chrome-profile" --remote-debugging-port=18800 about:blank &
```

**重置去重状态（强制下次全量输出）：**
```bash
echo -n > projects/x-digest/seen_links.txt
```

---

_Last updated: 2026-03-18_
