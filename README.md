# 企业知识问答 Agent

员工输入制度或产品问题，模型检索资料、核对冲突并给出带原文引用的回答。支持问题和可选历史，输出 answer、citations、gaps、status。默认关键词检索，可选择向量混合召回。

## 安装与第一次运行

需要 Python 3.12+。先克隆仓库，再在项目根目录运行后续命令。仓库公开，无需登录即可查看和克隆。Windows 可用 py -3.12 替代 python。

~~~powershell
git clone https://github.com/lxcin/enterprise-knowledge-agent.git
cd enterprise-knowledge-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
~~~

Linux/macOS 使用 source .venv/bin/activate 激活环境，并按所用 shell 设置环境变量。下面的环境变量示例采用 PowerShell。

```powershell
python -m pip install -e .
$env:KNOWLEDGE_BASE_URL = 'https://api.deepseek.com'
$env:KNOWLEDGE_MODEL = 'deepseek-flash'
$env:KNOWLEDGE_API_KEY = $env:DEEPSEEK_API_KEY
python -X utf8 -m knowledge_agent '报销期限多久？' --trace
```

上例使用已有的 DeepSeek 环境变量，也可自行配置 KNOWLEDGE_API_KEY。默认 [data/](data/) 包含相互冲突的 D01、D02，预期答复应列出 30 天与 15 天并请求确认。--docs 指定资料目录，--history 指定包含 role 和 content 的 JSON 数组。

配置清单见 [.env.example](.env.example)。程序读取进程环境变量，模板文件需由使用者或环境管理工具加载。真实模型调用会发送问题与相关证据，仓库样例均为合成资料。

## 配置与上下文输入

| 配置 | 用途 | 何时需要 |
|---|---|---|
| KNOWLEDGE_BASE_URL | 问答服务的基础地址，程序追加 /chat/completions | 真实模型运行 |
| KNOWLEDGE_MODEL | 服务支持的模型名称 | 真实模型运行 |
| KNOWLEDGE_API_KEY | 问答服务密钥 | 服务要求认证时 |
| EMBEDDING_PROVIDER | api 或 local | 使用 --semantic 时 |
| EMBEDDING_BASE_URL、EMBEDDING_MODEL、EMBEDDING_API_KEY | 向量服务配置，程序追加 /embeddings | API 向量后端 |
| EMBEDDING_MODEL_PATH | 已准备好的完整模型目录 | 本地向量后端 |
| EMBEDDING_QUERY_PREFIX | 模型要求的查询前缀 | 可选，默认空 |

如果没有预先设置 DEEPSEEK_API_KEY，请通过自己的环境管理工具设置 KNOWLEDGE_API_KEY。.env.example 是变量清单，复制为 .env 并不会自动加载。服务要求的 /v1 等路径应保留在基础地址中，完整接口路径由程序追加。

API 向量后端可以这样配置，需将占位值替换成实际服务信息。

~~~powershell
$env:EMBEDDING_PROVIDER = 'api'
$env:EMBEDDING_BASE_URL = '<embedding 服务基础地址>'
$env:EMBEDDING_MODEL = '<embedding 模型名称>'
$env:EMBEDDING_API_KEY = '<embedding 服务密钥>'
python -X utf8 -m knowledge_agent '报销期限多久？' --semantic --trace
~~~

对话历史文件使用下面的 JSON 结构，保存为 history.json 后执行追问。

~~~json
[
  {"role": "user", "content": "报销期限多久？"},
  {"role": "assistant", "content": "D01 规定 30 天，D02 规定 15 天，适用关系尚待确认。"}
]
~~~

~~~powershell
python -X utf8 -m knowledge_agent '那超过了还能提交吗？' --history history.json --trace --max-steps 18
~~~

历史帮助模型理解“超过了”的含义，当前问题仍需检索原文。无模型凭据时可先运行文末的离线演示。

## 我们的思路

核心目标是让每个制度结论都能回到原文。让模型负责理解问题、改写检索词、判断证据是否足够及选择下一步；让程序负责执行工具、记录来源、校验引文和限制步数。

一次 search 尽量交付足够的材料，包括命中条款、同主题制度、表头脚注和明确链接。模型拿到证据后决定回答、核对冲突或继续搜索。关键词适合编号和精确术语，向量作为可选能力处理不同措辞；两者最终都返回实际原文。

我们优先用“替换材料后答案和动作是否变化”验证效果。只有 D01 时答 30 天，增加 D02 时说明冲突，增加明确替代依据时答 15 天。工具读取失败要报告缺口，达到执行上限要明确未完成。设计取舍及具体执行路径见[方案文档](docs/02-solution.md)。

## 工具与证据

search 返回相关原文、同主题制度和明确链接的条款。模型可在同一次调用中提供双语改写和假设性描述，用于寻找实际资料。证据不足时可换词重搜，也可 read 补读或 topic 枚举主题。

制度与产品事实必须本轮检索并引用。寒暄和纯澄清可直接回复。程序校验引文，再由模型审核结论与适用条件。--trace 包含查询、原文、补读缺口和审核反馈。模型失败时会记录具体错误类别，详见[方案](docs/02-solution.md)。

## 可选向量模型

启用 --semantic 后需要显式配置 embedding 后端。默认运行只需标准库。

| 后端 | 配置 | 依赖 |
|---|---|---|
| API | EMBEDDING_PROVIDER=api、EMBEDDING_BASE_URL、EMBEDDING_MODEL，按服务要求提供 EMBEDDING_API_KEY | 标准库 |
| 本地目录 | EMBEDDING_PROVIDER=local、EMBEDDING_MODEL_PATH | local-vector 可选安装组 |

两种后端都支持 EMBEDDING_QUERY_PREFIX，按所选模型的要求填写。问答模型与 embedding 配置独立。

```powershell
# 使用已准备的本地模型目录
python -m pip install -e ".[local-vector]"
$env:EMBEDDING_PROVIDER = 'local'
$env:EMBEDDING_MODEL_PATH = 'E:\models\your-embedding-model'
python -X utf8 -m knowledge_agent '报销期限多久？' --semantic --trace
```

可选安装组提供适配代码和依赖声明，模型文件由部署者准备。向量索引在启动时建立于内存，适合当前小语料。

## 导入 PDF 或 Markdown

```powershell
python -m pip install -r requirements.txt
python -X utf8 -m knowledge_agent.ingest 'E:\资料\报销办法.pdf' --docs corpus --doc-id D01 --version-date 2026-01-01 --topic '报销提交期限'
python -X utf8 -m knowledge_agent '报销期限多久？' --docs corpus --trace
```

输入也可为 UTF-8 Markdown。导入保留原件、document.json 和必要页面图，同一版本重复导入会报错。同一事项的资料使用一致主题标签。图表页可用 --visual-page 3 指定，渲染依赖 PATH 中的 Poppler pdftoppm。可选 --ocr-language chi_sim+eng 需要 Tesseract 和语言包，读图问答需要视觉模型。

复杂合并表格、跨页表格和多栏页面需人工核对原件。Word 可先导出为 PDF。

## 测试与评审

```powershell
python -B -X utf8 -m unittest discover -s tests -v
python -B -X utf8 tests/run_live.py
python -B -X utf8 tests/run_live.py --case conflict --workers 1
```

离线测试无需密钥。PDF 测试需要 requirements.txt 中的依赖，页面渲染测试另需 Poppler。缺少可选测试依赖时 unittest 会显示跳过，不能据此视为完整验收。真实用例脚本需要模型配置，逐条输出实际结果和 Trace，检查失败返回非零退出码。

当前离线测试实际执行 42 项并全部通过。真实问答记录来自历次迭代，包含失败与复跑。当前可配置 embedding API 使用模拟响应验收，完整后端联调仍待配置后执行。

| 评审内容 | 入口 |
|---|---|
| 需求与成功标准 | [01-requirements.md](docs/01-requirements.md) |
| 工具、决策、切片与模型配置 | [02-solution.md](docs/02-solution.md) |
| 验收结果和已知限制 | [03-evaluation.md](docs/03-evaluation.md) |
| AI 辅助与人工决策 | [04-ai-usage.md](docs/04-ai-usage.md) |
| 经验和下一步 | [05-retrospective.md](docs/05-retrospective.md) |
| 当前测试记录 | [submission-tests.txt](examples/submission-tests.txt) |
| 真实输入、输出和补跑 | [输入](examples/live-inputs.json)、[最新输出与 Trace](examples/submission-live.jsonl)、[历史复跑](examples/live-retry.jsonl) |

代码位于 [src/](src/)，测试位于 [tests/](tests/)，合成语料位于 [data/](data/)。目录组织参考 [GitHub 交付示例](https://github.com/lwz1357/agent-campus-submission-example)。


## 无模型服务时的离线演示

    python -X utf8 -m knowledge_agent.offline --case normal
    python -X utf8 -m knowledge_agent.offline --case conflict
    python -X utf8 -m knowledge_agent.offline --case missing
    python -X utf8 -m knowledge_agent.offline --case tool-failure

输出明确标注 offline_mock。该入口使用预设动作和固定审核，只验证工具执行、引用校验与状态转换。真实模型驱动记录见 examples/submission-live.jsonl。离线模式无需密钥或向量模型。

## 执行上限与记录

真实 CLI 支持 --max-steps，默认 18。达到上限返回 incomplete，已有持续工具失败则返回 tool_error。Trace 包含 step、decision.action、工具参数、简短 reason、返回原文或错误以及下一步动作。reason 是操作依据摘要。历史记录生成于旧版本时可能缺少这些字段。

## 提交信息

选题为第三题“企业知识问答 Agent”。仓库地址为 [lxcin/enterprise-knowledge-agent](https://github.com/lxcin/enterprise-knowledge-agent)，当前为公开仓库，评审无需额外授权。用 git rev-parse HEAD 取得最终 commit SHA。

实际投入用时由用户确认未计时，无法可靠恢复累计时长。开发跨多个会话完成，会话跨度不作为工作时长。已验证范围与未完成项见评估文档。
