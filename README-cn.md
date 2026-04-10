# llm-test

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
| **latency** | 3.0 | 测量 tokens/秒和延迟。Opus 本质上比小模型更慢——一个以 Haiku 速度（>120 tok/s）响应却声称是 Opus 的代理非常可疑。**不对称评分**：比基线更慢没问题（网络开销）；更快才是危险信号。 |
| **knowledge** | 3.0 | 询问训练数据截止日期边界附近的事件。不同模型版本有不同的知识截止日期，因此模型对应该知道的事件回答错误（或对不应该知道的事件回答正确）会暴露其真实版本。 |
| **style** | 3.0 | 提取风格特征（响应长度、词汇丰富度、句式复杂度、对冲用语频率、格式化习惯）并比较目标与基线之间的分布差异。 |

### 中等信号

| 探测 | 权重 | 测试内容 |
|---|---|---|
| **identity** | 2.0 | 8 个创意提示来让模型暴露身份——直接询问、角色扮演场景、反向拼写、补全陷阱。可被系统提示覆盖，因此信号强度中等。 |
| **sysprompt** | 2.0 | 尝试提取注入的系统提示。很多代理会添加隐藏的系统提示如"You are Claude Opus"——如果泄露了，就是操纵的证据。默认禁用。 |
| **logprobs** | 2.0 | 比较 token 概率分布（需要 API 支持 logprob）。可用时非常可靠，但大多数 Anthropic 兼容 API 不暴露 logprob。默认禁用。 |

### 低信号

| 探测 | 权重 | 测试内容 |
|---|---|---|
| **metadata** | 1.0 | 检查 API 响应中的 `model` 字段，并检查 HTTP 头部中的代理指纹。很容易伪造，但不匹配是一个强烈的负面信号。 |

## 评分公式

```
最终分数 = sum(score_i * weight_i * confidence_i) / sum(weight_i * confidence_i)
```

每个探测的贡献同时受其权重（该维度的重要性）和置信度（此次测量的可靠性）缩放。出错的探测获得 confidence=0.1 和 score=0.5，实际上将其从最终计算中移除。

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

## 项目结构

```
src/llm_test/
  __init__.py
  cli.py          Click CLI 入口
  config.py       YAML + Pydantic 配置加载
  client.py       统一 API 客户端（anthropic SDK + httpx）
  runner.py       异步探测编排器（含进度条）
  scoring.py      加权置信度聚合 + 判定
  report.py       Rich 终端表格 + JSON 输出
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

config/
  default.yaml            探测权重、参数、输出设置
  endpoints.yaml.example  端点配置模板

results/                  运行时输出（已 git-ignore）
```

## 相关工具

本工具是自包含的，但借鉴了以下项目的思路：

- **[Promptfoo](https://github.com/promptfoo/promptfoo)** -- LLM 输出评估和对比的 CLI 工具。可作为外部交叉验证。
- **[LLMTest_NeedleInAHaystack](https://github.com/gkamradt/LLMTest_NeedleInAHaystack)** -- Gregory Kamradt 的大海捞针原始测试。我们的 `needle` 探测实现了类似的方法论。
- **[lm-evaluation-harness](https://github.com/EleutherAI/lm-evaluation-harness)** -- 包含数百个数据集的学术基准评测框架。可与 llm-test 互补进行深度能力分析。

## 成本说明

完整测试运行会向基线和每个目标发起大量 API 调用。默认设置下每个目标的大致成本：

- **快速模式**（`--quick`）：约 15 次 API 调用，成本极低
- **完整运行**：约 80-100 次 API 调用，包括一些长上下文调用（needle 探测）。每个目标大约预算 $1-3，取决于上下文长度配置。

要降低成本，可在 `config/default.yaml` 中禁用高成本探测（`needle`、`baseline`），或使用 `--probe` 仅运行特定探测。

## 许可证

MIT
