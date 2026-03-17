# X Digest — 设计文档

> 自动化 X/Twitter 信息流精炼系统：从 For You timeline 抓取 → 过滤 → 排序 → 推送 → 训练推荐算法

## 1. 解决什么问题

jamie 需要跟踪 AI/LLM 领域动态，但 Twitter For You timeline 噪声太多（鸡汤、营销、无关内容），每天刷 timeline 浪费大量时间。

**目标：** 每小时自动生成一份 AI/LLM 精华 digest，同时反向训练 Twitter 推荐算法（标记无关内容为 "Not interested"），形成正循环。

## 2. 系统架构

```
┌─────────────────┐
│  Chrome (18800)  │  ← jamie 已登录的 Chrome，~/chrome-profile
│  x.com/home      │
└───────┬─────────┘
        │ CDP (Playwright)
        ▼
┌─────────────────┐     ┌──────────────────┐
│ scrape_timeline │────▶│ filter_digest.py │──▶ Markdown digest
│     .py         │     └──────────────────┘         │
└───────┬─────────┘                                   │
        │                                             ▼
        ▼                                    ┌────────────────┐
┌───────────────────┐                        │ Discord 频道    │
│ mark_not_interested│                       │ #x-digest       │
│       .py         │                        └────────────────┘
└───────────────────┘                                 │
        │                                             ▼
        ▼                                    ┌────────────────┐
   X 推荐算法训练                             │ GitHub repo     │
   (Not interested)                          │ digests/*.md    │
                                             └────────────────┘
```

### 数据流

1. **Scrape** → Playwright CDP 连接 Chrome → 打开 For You → 滚动 15 轮 → 提取 ~80-120 条推文 → JSON stdout
2. **Mark** → 从 JSON 识别非 AI 相关推文 → 逐条打开原帖 → 点 "Not interested"（每次最多 3 条，5-15s 随机延迟）
3. **Filter** → 从 JSON 过滤：去短文本、去 spam、**去非 AI 内容** → 按 engagement × 内容深度打分 → 取 top 30
4. **Archive** → 保存到 `digests/YYYY-MM-DD_HH.md` → git commit + push
5. **Deliver** → cron agent 读取 stdout → 发送到 Discord 频道

### 调度

- **OpenClaw cron job:** `x-digest`，every 1h
- **执行模型:** gemini-flash（省 token，只需跑脚本和转发输出）
- **Session:** isolated（不占主 session context）
- **Timeout:** 180s（滚动 + mark 需要时间）
- **投递频道:** Discord `#x-digest`（ID: `1483497635758215168`）

## 3. 核心组件

### 3.1 scrape_timeline.py

**职责：** 抓取 For You timeline 推文

| 参数 | 值 | 说明 |
|---|---|---|
| `SCROLL_ROUNDS` | 15 | 滚动轮次，每轮 1000px，约抓 80-120 条 |
| `SCROLL_PX` | 1000 | 每轮滚动像素 |
| `SCROLL_WAIT_MS` | 2000 | 每轮等待时间，让推文加载 |
| Chrome CDP | `127.0.0.1:18800` | 固定复用 `~/chrome-profile` |

**输出 JSON 结构：**
```json
{
  "displayName": "Greg Brockman",
  "handle": "gdb",
  "text": "gpt-5.4 has ramped faster than...",
  "time": "2026-03-17T12:00:00.000Z",
  "link": "https://x.com/gdb/status/123456",
  "replies": "42",
  "retweets": "223",
  "likes": "3.7K"
}
```

**去重：** 以 `link`（status URL）为 key，同一页面内不重复抓。

**已知限制：**
- 依赖 Chrome 保持登录态（`~/chrome-profile`）
- 依赖 Chrome 在 port 18800 运行
- For You tab 的 DOM selector 可能随 X 更新而变

### 3.2 filter_digest.py

**职责：** 从原始推文中筛选 AI/LLM 相关高质量内容

**过滤管线（按顺序）：**

1. **长度过滤** — 文本 < 30 字符的丢弃
2. **Spam 过滤** — 匹配 `SPAM_PATTERNS`（giveaway、airdrop、follow back 等）
3. **AI 相关性过滤** — 必须匹配 `AI_RELEVANCE_PATTERNS` 中至少一条，否则丢弃

**AI 相关性关键词覆盖范围：**

| 类别 | 示例关键词 |
|---|---|
| 核心 AI | AI, LLM, GPT-x, Claude, Gemini, agent, agentic |
| 技术 | transformer, diffusion, embedding, RAG, fine-tune, inference |
| 基础设施 | GPU, TPU, compute, chip, hardware |
| 公司 | OpenAI, Anthropic, Codex, Copilot, Cursor |
| 商业 | SaaS, startup, YC, funding, Series A-D |
| 开发 | coding, dev tool, developer, automation, workflow |
| 研究 | ARC-AGI, benchmark, RLHF, multimodal, reasoning |

**排序算法：**
```
score = (likes + retweets × 3 + replies × 2) × min(text_length / 280, 1.5)
```
- Retweet 权重 3x（传播意愿 > 点赞）
- Reply 权重 2x（引发讨论 > 点赞）
- 长文本有 bonus（最高 1.5x），鼓励实质性内容

**输出：** Top 30 条，Markdown 格式，每条带原帖链接。

### 3.3 mark_not_interested.py

**职责：** 反向训练 X 推荐算法，标记非 AI 内容为 "Not interested"

**安全约束：**

| 参数 | 值 | 原因 |
|---|---|---|
| `MAX_MARKS_PER_RUN` | 3 | 避免被检测为 bot |
| 操作间延迟 | 5-15s 随机 | 模拟人类行为 |
| 每次开新 page | 是 | 隔离操作，不影响主 Chrome 状态 |

**操作流程：**
1. 从 stdin 读 JSON → 筛出不匹配 `RELEVANT_PATTERNS` 的推文
2. 取前 3 条 → 逐条打开原帖 URL
3. 找到 `[data-testid="caret"]`（三点菜单）→ 点击
4. 在弹出菜单中找 "Not interested" → 点击
5. 随机等待 → 下一条

**当前状态：⚠️ 需要修复**
- X 的菜单 DOM 结构可能变化，`caret` selector 或 `menuitem` 文本可能需要更新
- 首次测试 3/3 均未找到 "Not interested" 选项
- 需要用浏览器手动调试确认当前正确的 selector

### 3.4 run_digest.sh

**职责：** 编排整个流程

```
Step 1: scrape_timeline.py → $RAW (JSON)
Step 2: $RAW | mark_not_interested.py (允许失败)
Step 3: $RAW | filter_digest.py → $DIGEST (Markdown)
Step 4: 保存到 digests/YYYY-MM-DD_HH.md
Step 5: git add + commit + push
Step 6: echo $DIGEST (供 cron agent 读取并发送)
```

**容错：**
- Step 2 (mark) 允许失败（`|| true`），不影响 digest 生成
- 空 scrape 或空 filter 结果 → exit 1，cron agent 不发消息

## 4. 文件结构

```
projects/x-digest/
├── DESIGN.md              # 本文档
├── README.md              # 项目简介
├── scrape_timeline.py     # 抓取脚本
├── filter_digest.py       # 过滤 + 排序 + 格式化
├── mark_not_interested.py # 反向训练 X 算法
├── run_digest.sh          # 编排脚本（cron 入口）
└── digests/               # 历史存档（git tracked）
    ├── .gitkeep
    └── YYYY-MM-DD_HH.md   # 每小时 digest
```

**GitHub repo:** `tuly-space/x-digest`（public）

## 5. 依赖

| 依赖 | 用途 |
|---|---|
| Python 3.13 + uv | 运行时 |
| playwright | 浏览器自动化（通过 `--with playwright` 动态安装） |
| Chrome @ 18800 | 已登录的 X 账号，`~/chrome-profile` |
| OpenClaw cron | 定时调度 |
| git + gh | digest 归档到 GitHub |

## 6. 迭代方向

### 短期（TODO）

- [ ] **修复 "Not interested" selector** — 调试 X 当前的菜单 DOM 结构
- [ ] **去重跨小时** — 同一条推可能连续多期出现，加基于 status ID 的去重
- [ ] **digest 去重** — 同一作者相似内容合并（如 dharmesh 的 A/B test 推文）

### 中期

- [ ] **LLM 二次过滤** — 用 gemini-flash 对 top 50 做语义判断，提升关键词无法覆盖的边缘 case 质量
- [ ] **自定义权重** — jamie 可以 boost/mute 特定作者或话题
- [ ] **互动反馈** — jamie 在 Discord 对 digest 某条点 ❤️ → 记录偏好 → 调整排序
- [ ] **每日汇总** — 除了小时级 digest，每天 23:00 UTC+8 出一份 daily top 10

### 长期

- [ ] **Newsletter 生成** — 周度/月度，从 daily digest 中二次精炼，加评论和上下文
- [ ] **多源聚合** — 除 X 外接入 Hacker News、Reddit、arXiv
- [ ] **知识库联动** — digest 内容自动收录到 knowledge-base（`projects/knowledge-base/`）

## 7. 运维

**检查 cron 状态：**
```bash
openclaw cron list
openclaw cron runs x-digest
```

**手动触发一次：**
```bash
cd projects/x-digest && bash run_digest.sh
```

**调整频率：**
```bash
openclaw cron edit <job-id> --every 2h  # 改为 2 小时
```

**暂停/恢复：**
```bash
openclaw cron disable <job-id>
openclaw cron enable <job-id>
```

**Chrome 挂了怎么办：**
```bash
DISPLAY=:99 /opt/google/chrome/chrome --user-data-dir="$HOME/chrome-profile" --remote-debugging-port=18800 about:blank &
```

---

_Last updated: 2026-03-17_
