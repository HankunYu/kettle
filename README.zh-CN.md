# kettle

[English](README.md) | 简体中文

kettle 盯着"某件事发生了没有"这类问题。在你配置的时间点，用能搜索网页、读取网页的 AI
(Claude Code,或 Anthropic / OpenAI / Gemini 的 API)把每个问题查一遍，一旦答案变成"发生了",
就把摘要和来源通过 [Bark](https://github.com/Finb/Bark) 推送到你的 iPhone。

监控规则不用自己写：用大白话描述你在等什么,AI 会先搜索现状、找权威来源、写好精确的判定标准，
然后自动开始监控。如果这件事其实已经发生了，会直接告诉你，不再加入监控。

典型用途：某个固件重新支持越狱、某款产品在你所在地区开放预订、某个库发布了某个功能、
某条官方公告发布了。

## 环境要求

- Linux + systemd(user units)。CLI 在 macOS 上也能运行，但定时调度需要自己安排;
  不支持 Windows(文件锁用的是 `fcntl`)。
- Python 3.11+。只用标准库，无需安装依赖。
- 一个研究引擎(见[引擎](#引擎)):已安装并登录的 [Claude Code](https://code.claude.com)(默认),
  或者 Anthropic / OpenAI / Gemini 的 API key。
- iOS 上的 [Bark](https://github.com/Finb/Bark) App,用于接收推送。

## 安装

```sh
cp config.example.toml config.toml   # 填入 bark_key;远程访问时设置 [server] host/token
python -m kettle test-notify         # 验证推送链路
./install.sh                         # 安装 systemd user units:探测 timer + web 服务
```

`install.sh` 会把 `systemd/` 里的 `@KETTLE_DIR@` / `@PYTHON@` 换成当前目录和 `python3`
的路径。想在注销后继续运行，执行一次 `loginctl enable-linger`。

API key 放在 `.env`(gitignored),每行一个，只需要填你用到的引擎:

```sh
cat > .env <<'KEYS'
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...
KEYS
chmod 600 .env
```

## 引擎

探测和新建监控时的分析在 `config.toml` 里各自选择引擎(`[probe]` 和 `[analyze]`;`[analyze]`
没写的项沿用 `[probe]`)。比如可以用更强的模型建监控，用便宜的模型做日常探测。

| `engine` | 调研方式 | 凭据 |
|---|---|---|
| `claude-code`(默认) | headless `claude -p` + WebSearch / WebFetch | Claude Code 登录，或 `ANTHROPIC_API_KEY` |
| `anthropic` | Messages API + web search / web fetch 服务端工具 | `ANTHROPIC_API_KEY` |
| `openai` | Responses API + `web_search` | `OPENAI_API_KEY` |
| `gemini` | `generateContent` + Google Search grounding + URL context | `GEMINI_API_KEY` |

- `claude-code` 默认用你的 Claude 订阅;`.env` 里有 `ANTHROPIC_API_KEY` 时改走 API 计费，这个 key
  只注入给 `claude` 子进程。不要把它放进全局 shell 环境变量：那样你平时交互使用的 Claude Code
  也会改走 API 计费。Max 和 Team 套餐每月附带
  [API credits](https://support.claude.com/en/articles/17154008-monthly-api-credits-for-max-and-team-plans),
  可以用来支付 API 用量。
- API 引擎不需要 CLI,通常也快得多(几秒而不是几分钟)。`anthropic` 引擎抓取网页时绕过缓存，
  探测能看到最新内容。
- 能否读取指定网页很关键：好的判定标准会写"抓取这个 URL 并核对 X",只靠搜索的回答更容易漏掉刚发生的变化。
  prompt 是按 Claude 调的，换成其他厂商后，前几次结果最好人工看一下。

## 定时

```toml
[schedule]
times = ["09:30", "21:30"]   # 本地时间，一天几次都可以
```

每个时间点，每个监控中的问题探测一次。kettle 按问题判断("上一个时间点之后还没探测过"),
所以关机或睡眠错过的时间点会在之后补上，中途重启会接着跑，多个驱动方式同时运行也不会重复探测。
有两种驱动方式，同时用也安全:

- `kettle serve` 内置调度器(每分钟检查一次)。
- `kettle run` 探测到期的问题后退出。systemd timer 每 15 分钟调用一次;用 cron 也一样。

`times = []` 关闭定时探测。修改定时不需要重启。

## 费用

每个监控中的问题在每个时间点调研一次，新建监控时的分析会跑一次更长的调研。Claude Code 用订阅时
计入套餐用量限额;API 引擎按 token 计费，另加各家的搜索费用。模型、轮数上限和超时都可以在
`config.toml` 里按任务分别配置。

## 用法

```sh
python -m kettle analyze "想监控的事"               # AI 调研并自动加入监控
python -m kettle list                              # 查看问题与状态
python -m kettle add "问题" --criteria "什么算有结果"  # 手动添加
python -m kettle probe <id> [--no-notify]          # 立即探测一次
python -m kettle reset <id>                        # 已解决的问题重新监视
python -m kettle remove <id>                       # 删除问题
python -m kettle run [--all]                       # 探测到期的问题(--all:立即探测全部 watching 的问题)
python -m kettle serve                             # HTTP API + 网页(web service 调用)
```

探测判定为"有结果"时,kettle 推送摘要和来源，把问题标记为 `resolved`,之后不再探测;
没有结果则静默。连续 3 次探测失败会推送一条警告。`--no-notify` 只探测，不推送，也不标记 resolved。

问题格式见 `questions.example.toml`;`questions.toml` 由 kettle 自动生成和重写。

## 网页 / API

`python -m kettle serve` 后打开 `http://<host>:<port>/`(默认端口 8730)。网页上可以新建监控、
查看后台任务进度、立即探测、重新监视、编辑判定标准、删除、查看探测历史;手机可用，支持深色模式。

`/api/*` 需要 `Authorization: Bearer <token>`(token 在 `config.toml` 的 `[server]` 里)。
分析和探测要几分钟，这些接口会立即返回一个 job,轮询 job 获取结果。

| Method | Path | 说明 |
|---|---|---|
| `POST` | `/api/analyze` | `{"intent": "...", "notify": true}` → 调研并开始监控，返回 job |
| `GET` | `/api/jobs` / `/api/jobs/{id}` | 最近的后台任务 / 单个任务的状态与结果 |
| `GET` | `/api/questions` | 问题列表(含状态与最近结果) |
| `POST` | `/api/questions` | 手动添加 `{"question", "criteria", "id"?}` |
| `PATCH` | `/api/questions/{id}` | 修改 `question` / `criteria` |
| `DELETE` | `/api/questions/{id}` | 删除(探测历史保留) |
| `POST` | `/api/questions/{id}/probe` | 立即探测，返回 job |
| `POST` | `/api/questions/{id}/reset` | 重新监视 |
| `GET` | `/api/questions/{id}/history?limit=50` | 探测历史 |
| `GET` | `/api/schedule` | 探测时间、下次运行时间、当前正在探测的问题 |

```sh
curl -X POST http://host:8730/api/analyze \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"intent": "Switch 2 什么时候出国行"}'
```

### iPhone 快捷指令

用语音或分享菜单提交监控。在「快捷指令」App 里新建快捷指令，依次添加:

1. **要求输入**(Ask for Input):类型选「文本」,提示 `想监控什么?`
2. **获取 URL 的内容**(Get Contents of URL):`http://<你的地址>:8730/api/analyze`。
   点「显示更多」后设置:
   - 方法:`POST`
   - 头部:`Authorization` = `Bearer <token>`
   - 请求体:JSON,添加一个文本字段 `intent` = 「提供的输入」
3. **显示通知**:`已提交，分析完成后会推送`

取名比如「监控」,之后可以说"嘿 Siri,监控"。想从其他 App 直接提交选中的文字或链接：在设置里打开
「在共享表单中显示」(文本、URL),`intent` 改用「快捷指令输入」,为空时再回退到「要求输入」。
调试时可以在第 2 步后加「显示结果」,查看服务器返回的内容。

### 安全

- 服务是明文 HTTP,token 会以明文在网络上传输。只在内网监听，或者放在提供 HTTPS 的反向代理 /
  隧道后面再暴露到公网。
- `host` 不是本机地址时必须设置 token;用 `openssl rand -hex 24` 生成足够长的随机值。
- 拿到 token 的人可以增删问题，并触发会消耗你 Claude 用量的分析和探测。
- 模型只能搜索网页和读取网页:`claude-code` 只允许 `WebSearch` 和 `WebFetch` 两个工具，API 引擎只有
  各家服务端的搜索工具。都不能读写本地文件，也不能执行命令。

## 文件

- `kettle/`:代码。`cli` / `server` 是入口,`service` 是共用的业务操作,`research` 存放 prompt 并解析结果,
  `engines/` 每个引擎一个模块,`schedule` / `scheduler` 计算时间点并运行内置调度器,`store` 负责文件读写
  (flock 加锁,timer 与 web 服务可以同时运行),`jobs` 是后台任务,`notify` 发送 Bark 推送。
- `web/index.html`:网页。
- `questions.toml`:问题定义(gitignored)。可以手动编辑，但 kettle 会重写它，只保留文件头注释。
  格式见 `questions.example.toml`。
- `config.toml` / `.env`:配置与密钥(gitignored)。
- `state.json` / `probes.jsonl`:状态与探测历史(gitignored)。
- `systemd/`:user unit 模板，由 `install.sh` 填充路径并安装。

## License

[MIT](LICENSE)
