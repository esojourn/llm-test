# llm-test

[English](README.md)

API 代理模型降级检测工具。

当你通过第三方 API 代理付费使用 Claude Opus 时，你怎么确认实际拿到的真的是 Opus，而不是更便宜的 Sonnet、Haiku，甚至是量化过的开源替代品？**llm-test** 通过对你的 API 端点运行 10 个独立探测，生成一个置信度评分来回答这个问题。

## 工作原理

llm-test 将**目标**端点（你要验证的代理）与**基线**（Anthropic 官方 API）进行对比。每个探测测试一个不同的维度——延迟、推理能力、长上下文检索、输出风格等。所有结果通过加权置信度公式汇总为一个最终判定：

```
>= 0.85  GENUINE_OPUS        所有探测与 Opus 一致
>= 0.70  LIKELY_OPUS          存在微小异常，大概率没问题
>= 0.50  SUSPICIOUS           信号混杂，需要进一步调查
>= 0.30  LIKELY_DOWNGRADE     多个危险信号
<  0.30  DEFINITE_DOWNGRADE   强证据表明不是 Opus
```

核心洞察：**单个探测不具有决定性，但同时伪造全部 10 个几乎不可能。** 代理可以在响应中伪造模型名称，可以人为增加延迟来假装更慢。但它无法让一个 Sonnet 级别的模型通过 Opus 级别的推理题，同时还要匹配 Opus 的输出风格、知识截止日期和长上下文检索能力。

## 快速开始

### Web 界面（推荐大多数用户使用）

```bash
# 1. 安装
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# 2. 启动 Web 服务器
llm-test serve

# 3. 在浏览器中打开 http://127.0.0.1:8000
#    输入你的 API 中转站 Base URL 和 Key，点击"开始验证"
```

### 命令行

```bash
# 1. 安装
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# 2. 配置端点
cp config/endpoints.yaml.example config/endpoints.yaml
# 编辑 config/endpoints.yaml —— 填入 API 密钥和代理 URL

# 3. 运行
llm-test run              # 完整测试套件
llm-test run --quick      # 快速模式（仅 metadata + identity + latency）
```

## 安装

需要 Python 3.11+。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# 开发环境
pip install -e ".[dev]"
```

## 配置

### 端点配置（`config/endpoints.yaml`）

定义一个基线（Anthropic 官方 API）和一个或多个待验证的目标：

```yaml
baseline:
  provider: anthropic
  api_key_env: ANTHROPIC_API_KEY       # 从此环境变量读取
  base_url: https://api.anthropic.com
  model: claude-opus-4-6

targets:
  - name: "my-proxy"
    provider: anthropic_compatible     # 或 "openai_compatible"
    api_key_env: MY_PROXY_API_KEY
    base_url: https://my-proxy.example.com
    model: claude-opus-4-6
```

支持三种 provider 类型：

| Provider | 协议 | 认证头 | 适用场景 |
|---|---|---|---|
| `anthropic` | Anthropic Messages API（官方 SDK） | `x-api-key` | 官方 API（基线） |
| `anthropic_compatible` | Anthropic Messages API（httpx） | `x-api-key` | 镜像 Anthropic API 的代理 |
| `openai_compatible` | OpenAI Chat Completions API（httpx） | `Authorization: Bearer` | 通过 OpenAI 格式暴露 Claude 的代理 |

### 测试配置（`config/default.yaml`）

控制哪些探测启用、权重以及采样数、上下文长度等参数。默认值适用于大多数场景，详见文件中的所有选项。

## CLI 用法

```bash
# 完整测试 —— 对所有目标运行所有已启用的探测
llm-test run

# 快速模式 —— 仅 metadata、identity 和 latency（速度快、成本低）
llm-test run --quick

# 运行指定探测
llm-test run --probe reasoning --probe latency

# 仅测试特定目标
llm-test run --target my-proxy

# 同时输出终端报告和 JSON 报告
llm-test run --output terminal --output json

# 重新展示已保存的报告
llm-test report results/latest.json

# --- 基线缓存（节省 API 成本） ---

# 一次性收集基线响应并缓存到磁盘
llm-test baseline

# 使用缓存运行测试（不再调用官方 API 获取基线）
llm-test run --baseline-cache cache/baseline.json

# 将延迟数据也纳入缓存（不推荐——时延数据依赖实时网络状况）
llm-test baseline --include-latency

# 自定义缓存输出路径
llm-test baseline --output path/to/cache.json
```

## 10 个探测维度

每个探测产生一个 0.0（确定不是 Opus）到 1.0（与 Opus 一致）的分数，加上一个置信度值。探测按信号强度加权——越难伪造的探测权重越高。

### 高信号

| 探测 | 权重 | 测试内容 |
|---|---|---|
| **reasoning** | 5.0 | 多步数学题、逻辑谜题、边界条件代码生成。Opus 能解决 Sonnet/Haiku 解不了的问题。这是代理最难伪造的维度。 |
| **needle** | 4.0 | 大海捞针：在长文档（10K-100K 字符）的不同深度嵌入一个随机验证码，要求模型检索。测试真实的上下文窗口能力。 |
| **baseline** | 4.0 | 向基线和目标发送相同的提示，通过 n-gram 重叠度比较响应相似性。相同的模型应该产生结构相似的输出。 |

### 中高信号

| 探测 | 权重 | 测试内容 |
|---|---|---|
| **latency** | 3.0 | 测量 tokens/秒和延迟。Opus 本质上比小模型更慢——一个以 Haiku 速度（>120 tok/s）响应却声称是 Opus 的代理非常可疑。**不对称评分**：比基线更慢 = 1.0 分（网络开销正常）；更快则线性插值，从 ratio=1.0 的 1.0 分降至 ratio=2.0+ 的 0.1 分。 |
| **knowledge** | 3.0 | 询问训练数据截止日期边界附近的事件。不同模型版本有不同的知识截止日期，因此模型对应该知道的事件回答错误（或对不应该知道的事件回答正确）会暴露其真实版本。 |
| **style** | 3.0 | 提取风格特征（响应长度、词汇丰富度、句式复杂度、对冲用语频率、格式化习惯）并比较目标与基线之间的分布差异。 |

### 中等信号

| 探测 | 权重 | 测试内容 |
|---|---|---|
| **identity** | 2.0 | 8 个创意提示来让模型暴露身份——直接询问、角色扮演场景、反向拼写、补全陷阱。区分特定的"Opus"自我识别（强信号）、泛化的"Claude"回答（弱正面）和非 Claude 身份（强负面）。可被系统提示覆盖，因此信号强度中等。 |
| **sysprompt** | 2.0 | 尝试提取注入的系统提示。很多代理会添加隐藏的系统提示如"You are Claude Opus"——如果泄露了，就是操纵的证据。默认禁用。 |
| **logprobs** | 2.0 | 比较 token 概率分布（需要 API 支持 logprob）。可用时非常可靠，但大多数 Anthropic 兼容 API 不暴露 logprob。默认禁用。 |

### 低信号

| 探测 | 权重 | 测试内容 |
|---|---|---|
| **metadata** | 1.0 | 检查 API 响应中的 `model` 字段，并检查 HTTP 头部中的代理指纹。很容易伪造，但不匹配是一个强烈的负面信号。 |

## 测试指南

### 推荐测试流程

```bash
# 第 1 步：一次性收集基线（节省后续测试的 API 成本）
llm-test baseline

# 第 2 步：快速检查（验证连通性和基本信号）
llm-test run --quick --baseline-cache cache/baseline.json --output terminal --output json

# 第 3 步：完整测试（所有 8 个启用的探测，更慢但更全面）
llm-test run --baseline-cache cache/baseline.json --output terminal --output json

# 第 4 步：查看详细结果
llm-test report results/latest.json        # 终端展示
cat results/latest.json | jq '.detailed_results'  # 原始 JSON
```

### 针对特定疑点的测试

```bash
# 怀疑速度太快？聚焦延迟探测
llm-test run --probe latency --baseline-cache cache/baseline.json

# 怀疑不是同一个模型？聚焦推理 + 身份 + 基线对比
llm-test run --probe reasoning --probe identity --probe baseline

# 只测试多个目标中的某一个
llm-test run --target my-proxy --baseline-cache cache/baseline.json

# 仅输出 JSON（无终端输出，适用于 CI/脚本）
llm-test run --output json --baseline-cache cache/baseline.json
```

### 解读结果

- **所有探测 confidence < 0.75**：这些探测被排除在评分之外（可通过 `config/default.yaml` 中的 `scoring.confidence_threshold` 配置）。通常意味着发生了错误——检查 JSON 报告中的 `details.error` 字段。
- **高分但低置信度**：结果看起来不错但测量不可靠。增加采样次数或检查间歇性错误。
- **Latency score = 1.0 且低置信度**：基线对比不可用，探测回退到绝对吞吐量启发式模式。
- **Identity score = 0.6**：模型泛化地自称"Claude"但未明确说是"Opus"。模棱两可——可能是 Opus 但被系统提示覆盖了。

## 报告输出

### 终端输出

终端报告展示：
- 每个目标的 Provider 信息（类型、模型名、URL）
- 探测评分表格，包含 **Score** 和 **Confidence** 两列
- 判定分类和解释说明
- 因低置信度被排除的探测列表

### JSON 报告

使用 `--output json` 时，llm-test 在 `results/` 目录下写入带时间戳的报告文件（同时更新 `latest.json`）。报告采用 **v2 格式**，包含两个部分：

**`targets`** — 向后兼容的摘要：

```json
{
  "version": 2,
  "timestamp": "20260410_153000",
  "targets": {
    "my-proxy": {
      "overall_score": 0.82,
      "classification": "LIKELY_OPUS",
      "probe_scores": {"metadata": 1.0, "latency": 0.7, "reasoning": 0.85},
      "explanation": "Most probes are consistent with Opus, minor anomalies detected."
    }
  }
}
```

**`detailed_results`** — 每个目标、每个探测、每次 API 调用的完整诊断数据：

```json
{
  "detailed_results": {
    "my-proxy": {
      "endpoint": {
        "name": "my-proxy",
        "provider": "anthropic_compatible",
        "base_url": "https://my-proxy.example.com",
        "model": "claude-opus-4-6"
      },
      "probes": [
        {
          "probe_name": "reasoning",
          "score": 0.85,
          "confidence": 0.9,
          "details": {"correct": 4, "total": 5, "accuracy": 0.8, "tasks": [...]},
          "api_calls": [
            {
              "model_reported": "claude-opus-4-6-20260301",
              "content": "答案是 42，因为...",
              "input_tokens": 385,
              "output_tokens": 120,
              "stop_reason": "end_turn",
              "latency_ms": 4521.3,
              "ttfb_ms": 1230.5,
              "tokens_per_sec": 26.5
            }
          ]
        }
      ]
    }
  }
}
```

### 报告字段参考

**顶层字段：**

| 字段 | 说明 |
|---|---|
| `version` | 报告格式版本（当前为 `2`） |
| `timestamp` | 测试运行的 UTC 时间（`YYYYMMDD_HHMMSS`） |
| `targets` | 每个目标的汇总评分（向后兼容 v1） |
| `detailed_results` | 每个目标的完整诊断数据 |

**`targets.{name}` 字段：**

| 字段 | 说明 |
|---|---|
| `overall_score` | 加权聚合分数（0.0 - 1.0） |
| `classification` | 分类：`GENUINE_OPUS`、`LIKELY_OPUS`、`SUSPICIOUS`、`LIKELY_DOWNGRADE`、`DEFINITE_DOWNGRADE` |
| `probe_scores` | 探测名到分数的映射（包含所有探测，含被排除的） |
| `explanation` | 判定结果的人类可读解释 |

**`detailed_results.{name}.endpoint` 字段：**

| 字段 | 说明 |
|---|---|
| `name` | `endpoints.yaml` 中定义的目标名称 |
| `provider` | `anthropic`、`anthropic_compatible` 或 `openai_compatible` |
| `base_url` | API 端点 URL |
| `model` | 请求的模型名称 |

**`detailed_results.{name}.probes[]` 字段：**

| 字段 | 说明 |
|---|---|
| `probe_name` | 探测标识符 |
| `score` | 0.0（非 Opus）到 1.0（与 Opus 一致），自动钳位到此范围 |
| `confidence` | 此次测量的可靠性（0.0 - 1.0）。低于 `confidence_threshold`（默认 0.75）的探测不参与评分 |
| `details` | 探测专属的诊断数据（见下表） |
| `api_calls` | 此探测发起的所有 API 调用的数组 |

**各探测的 `details` 主要字段：**

| 探测 | `details` 中的关键字段 |
|---|---|
| metadata | `model_reported`、`model_expected`、`model_field_match`、`interesting_headers` |
| identity | `identity_votes`（每个模型家族的投票数）、`dominant_identity`、`prompts`（逐条提示结果） |
| latency | `per_length`（每个提示长度的统计）、`target_median_tps`、`speed_ratio` |
| reasoning | `correct`、`total`、`accuracy`、`tasks`（逐题的通过/失败及响应预览） |
| needle | `results`（按上下文长度和深度的结果）、`accuracy` |
| baseline | `avg_similarity`、`comparisons`（逐条提示的相似度和长度比） |
| knowledge | `results`（逐条知识点的匹配结果及提取的日期） |
| style | 语言风格特征分数和对比 |

**`api_calls[]` 字段：**

| 字段 | 说明 |
|---|---|
| `model_reported` | API 返回的模型名称 |
| `content` | 模型的完整响应文本 |
| `input_tokens` | 提示的 token 数 |
| `output_tokens` | 响应的 token 数 |
| `stop_reason` | 模型停止的原因（`end_turn`、`max_tokens` 等） |
| `latency_ms` | 请求总延迟（毫秒） |
| `ttfb_ms` | 首字节时间（毫秒） |
| `tokens_per_sec` | 输出吞吐量（output_tokens / 延迟秒数） |

`llm-test report` 命令同时兼容旧版（v1，无详细数据）和新版（v2）格式的报告文件。

## 数据存储

所有持久化数据保存在两个目录中：

```
cache/                              基线响应缓存（已 git-ignore）
  baseline.json                     所有探测的缓存基线响应

results/                            测试报告（已 git-ignore）
  report_YYYYMMDD_HHMMSS.json       每次运行的带时间戳报告（v2 格式）
  latest.json                       最近一次报告的副本
```

**`cache/baseline.json`** 保存缓存的基线 API 响应，避免每次运行都调用 Anthropic 官方 API。每条记录包含完整的 API 响应（模型输出、token 数、时延），以请求参数的 SHA-256 哈希为键。由 `llm-test baseline` 生成，由 `llm-test run --baseline-cache` 消费。

**`results/report_*.json`** 保存每次运行的完整测试记录。使用 `--output json` 的每次运行都会创建新的带时间戳文件，并覆盖 `latest.json`。报告是自包含的——包括端点配置、所有探测的评分与置信度、诊断详情和原始 API 调用数据。旧报告不会被自动删除，在 `results/` 中累积，方便历史对比。

**不保存的数据**（避免泄露敏感信息）：API 密钥、`api_key_env` 变量名，以及 API 响应中的完整 `raw_json`/`raw_headers`（它们回显请求内容且体积较大）。

## 评分公式

```
最终分数 = sum(score_i * weight_i * confidence_i) / sum(weight_i * confidence_i)
```

每个探测的贡献同时受其权重（该维度的重要性）和置信度（此次测量的可靠性）缩放。出错的探测获得 confidence=0.1 和 score=0.5，实际上将其从最终计算中移除。

**置信度阈值**：置信度低于 `scoring.confidence_threshold`（默认 0.75，可在 `config/default.yaml` 中配置）的探测会被完全排除在聚合之外。它们的分数仍然记录在报告中，但不影响最终判定。这可以防止不可靠的测量（如错误或缓存未命中）扭曲最终分数。被排除的探测会在解释文本中标注。

**分数钳位**：所有探测的 score 和 confidence 值自动钳位到 [0.0, 1.0] 范围，防止边界情况产生无效的聚合结果。

## 自定义探测扩展

添加新探测只需一个文件：

```python
# src/llm_test/probes/my_probe.py

from typing import Any
from . import BaseProbe, ProbeResult, register_probe
from ..client import EndpointClient

@register_probe
class MyProbe(BaseProbe):
    name = "my_probe"
    description = "此探测测试什么"

    async def run(
        self,
        target: EndpointClient,
        baseline: EndpointClient | None,
        config: dict[str, Any],
    ) -> ProbeResult:
        resp = await target.send_message(
            [{"role": "user", "content": "测试提示"}],
            max_tokens=256,
        )
        score = 1.0  # 你的评分逻辑
        return ProbeResult(
            probe_name=self.name,
            score=score,
            confidence=0.7,
            details={"info": "..."},
            raw_responses=[resp],
        )
```

然后在 `src/llm_test/probes/__init__.py` 的 `_load_probes()` 中添加 import，并可选地在 `config/default.yaml` 中添加配置项。

## Web 应用

llm-test 内置了一个 Web 界面，方便不想使用命令行的用户直接在浏览器中测试。

```bash
llm-test serve                    # 启动于 http://127.0.0.1:8000
llm-test serve --port 3000        # 自定义端口
llm-test serve --reload           # 开发模式，代码修改自动重启
```

### 功能

- **首页** — 输入中转站的 Base URL、API Key 和协议类型，点击即可开始测试。通过 SSE 实时显示每项探测的进度和结果。
- **报告页** — 可分享的测试报告，包含评级结果、各探测得分明细和完整诊断解释。每个报告有独立 URL（`/report/{id}`）。
- **方法论页** — 详细介绍 10 项探测的原理、评分公式、设计原则和已知局限性。
- **用户系统** — 可选的用户名密码注册登录。登录后测试报告自动保存到账户下。

### 技术架构

Web 应用是一个 FastAPI 服务，直接导入并在服务端运行现有的探测代码。这样做可以保护探测 prompt、评分逻辑和基线数据不暴露给客户端。

- **后端**：FastAPI + Jinja2 模板 + SQLAlchemy async
- **前端**：Tailwind CSS（暗色主题）+ Alpine.js 处理交互
- **数据库**：默认 SQLite（`data/llm_test.db`），生产环境使用 PostgreSQL（设置 `DATABASE_URL`）
- **认证**：bcrypt 密码哈希 + JWT Cookie
- **实时进度**：SSE（Server-Sent Events）

### 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///data/llm_test.db` | 数据库连接字符串。生产环境使用 `postgresql+asyncpg://...` |
| `SECRET_KEY` | `dev-secret-change-in-production` | JWT 签名密钥。**生产环境必须修改。** |

## 项目结构

```
src/llm_test/
  __init__.py
  cli.py          Click CLI 入口（run、report、baseline、serve）
  config.py       YAML + Pydantic 配置加载
  client.py       统一 API 客户端（anthropic SDK + httpx）
  cache.py        基线响应缓存（数据模型 + I/O）
  runner.py       异步探测编排器（含进度条）
  scoring.py      加权置信度聚合、Verdict + RunResult
  report.py       Rich 终端表格 + JSON 输出（v2 含完整详情）
  probes/
    __init__.py   BaseProbe、ProbeResult、@register_probe、注册表
    metadata.py   响应元数据检查
    latency.py    延迟/吞吐量画像
    reasoning.py  复杂多步推理任务
    needle.py     大海捞针长上下文测试
    identity.py   模型身份探测
    knowledge.py  知识截止日期验证
    style.py      输出风格指纹
    baseline.py   A/B 基线对比
    sysprompt.py  系统提示提取（可选）
    logprobs.py   Logprob 分析（可选）
  web/
    app.py            FastAPI 应用工厂
    database.py       SQLAlchemy async 引擎 + 会话
    models.py         User + TestReport 数据库模型
    auth.py           bcrypt + JWT 认证
    schemas.py        请求校验
    templates_conf.py Jinja2 模板配置
    routes/
      pages.py        页面路由（/、/methodology、/report、/login、/register）
      auth.py         注册/登录 API
      api.py          测试提交 + SSE 进度推送
    templates/        Jinja2 HTML 模板（暗色主题）
    static/           CSS + JS 静态文件

config/
  default.yaml            探测权重、参数、输出设置
  endpoints.yaml.example  端点配置模板

data/                     SQLite 数据库（已 git-ignore）
cache/                    基线响应缓存（已 git-ignore）
results/                  CLI 运行时输出（已 git-ignore）
alembic/                  数据库迁移（生产环境 PostgreSQL 使用）
```

## 相关工具

本工具是自包含的，但借鉴了以下项目的思路：

- **[Promptfoo](https://github.com/promptfoo/promptfoo)** -- LLM 输出评估和对比的 CLI 工具。可作为外部交叉验证。
- **[LLMTest_NeedleInAHaystack](https://github.com/gkamradt/LLMTest_NeedleInAHaystack)** -- Gregory Kamradt 的大海捞针原始测试。我们的 `needle` 探测实现了类似的方法论。
- **[lm-evaluation-harness](https://github.com/EleutherAI/lm-evaluation-harness)** -- 包含数百个数据集的学术基准评测框架。可与 llm-test 互补进行深度能力分析。

## 基线缓存

默认情况下，每次 `llm-test run` 都会调用 Anthropic 官方 API 进行基线对比，涉及 4 个探测（baseline、latency、style、knowledge）。由于在相同模型 + temperature 0 下，基于内容的对比结果是相对稳定的，你可以一次性收集基线响应并在后续运行中重复使用。

```bash
# 第 1 步：收集基线（一次性，或在模型更新时刷新）
llm-test baseline

# 第 2 步：后续运行使用缓存
llm-test run --baseline-cache cache/baseline.json
```

**工作原理：**

- `llm-test baseline` 对官方 API 运行所有需要基线的探测，并将每个响应保存到 `cache/baseline.json`（可通过 `--output` 自定义路径）。
- `llm-test run --baseline-cache` 加载缓存并从中返回响应，而不调用 API。探测接收到的 `CachedEndpointClient` 实现了与 `EndpointClient` 相同的接口——探测代码无需任何修改。
- **延迟探测默认排除在缓存之外**，因为其时延数据（tokens/秒、延迟）依赖实时服务器负载，缓存后会产生误导。排除时，延迟探测会自动回退到绝对吞吐量启发式模式。使用 `--include-latency` 可覆盖此行为。
- 缓存包含基线端点配置的 `config_hash`。如果你更改了基线模型或 URL，会打印警告，此时应重新运行 `llm-test baseline`。
- 缓存键是 `(messages, system, max_tokens, temperature)` 的 SHA-256 哈希。如果探测的提示词被更新，缓存会自动未命中，对应探测优雅降级（score=0.5, confidence=0.1）。

**何时需要刷新缓存：**

- Claude 部署了新的模型版本后
- 修改了 `config/endpoints.yaml` 中的基线模型后
- 修改了 `config/default.yaml` 中的探测提示词或参数后

## 成本说明

完整测试运行会向基线和每个目标发起大量 API 调用。默认设置下每个目标的大致成本：

- **快速模式**（`--quick`）：约 15 次 API 调用，成本极低
- **完整运行**：约 80-100 次 API 调用，包括一些长上下文调用（needle 探测）。每个目标大约预算 $1-3，取决于上下文长度配置。
- **使用基线缓存**（`--baseline-cache`）：消除所有基线 API 调用（每个目标约 15-20 次），成本大约减半。

要降低成本，可在 `config/default.yaml` 中禁用高成本探测（`needle`、`baseline`），或使用 `--probe` 仅运行特定探测。

## 许可证

MIT
