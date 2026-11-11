# 评估

## 当前验证入口

[当前离线测试记录](../examples/submission-tests.txt) 实际执行 42 项，全部通过，无跳过。覆盖检索、证据扩展、冲突与引用、路由、PDF 导入、可配置向量接口和模型错误分类。

[真实验收输入](../examples/live-inputs.json) 定义八组问题、历史、资料变体和故障注入。运行 tests/run_live.py 可重跑。本次按完整规范复跑的[真实输出与 Trace](../examples/submission-live.jsonl) 共 8/8 组通过自动检查。以下历史材料保留原始失败与复跑。可选 embedding 后端的端到端验收仍未完成。

## 历次必验场景

| 用例 | 预期及已有实际结果 |
|---|---|
| normal | 仅 D01，引用原文回答费用发生后 30 天。 |
| changed | 替换 D01 后，同一问题回答 45 天。 |
| conflict | 读到 D01 与 D02 后返回 conflict，引用 30 天和 15 天并请求确认。 |
| replacement | 读取 D04 替代依据后，引用 D02 和 D04 回答 15 天。 |
| missing | 补搜后无依据返回 insufficient_evidence。首次运行发生模型接口错误，复跑通过。 |
| paraphrase | 保留费用发生日起算。增强检索首轮状态选成 insufficient_evidence，调整提示词后复测为 answered。 |
| followup | 结合历史查询逾期条款，引用书面说明和财务审核要求。 |
| tool-failure | 注入 D02 读取失败，两次尝试后返回 tool_error。 |

[首次完整真实记录](../examples/live-results.jsonl) 有 7/8 组通过自动检查，[资料不足复跑](../examples/live-retry.jsonl) 通过。每条 actual.trace 保留完整工具动作和结果。

[增强检索记录](../examples/search-bundle-results.jsonl) 中，normal、changed、conflict、replacement、followup 只调用一次 search。paraphrase 首轮状态不符合预期，[单用例复测](../examples/search-bundle-retry.jsonl) 通过状态检查。部分回答使用了“整份制度未规定”的过度概括，随后提示词增加了限定已读证据的要求。

## 其他能力

| 能力 | 材料与验证范围 |
|---|---|
| 双语与假设查询 | [真实英文问答](../examples/bilingual-results.json) 一次检索找出中文冲突双方；尚未单独测量假设描述的增益。 |
| 检索路由 | [真实记录](../examples/prompt-results.json) 中，寒暄与纯澄清直接回复，要求跳过检索的制度问题仍检索并引用。 |
| 向量召回 | [历史原型对比](../examples/semantic-retrieval.json) 中，关键词未命中的口语问题通过向量找到了逾期条款。该实验使用当时开发机模型，当前已改为显式后端配置。 |
| embedding 预留接口 | 当前离线测试覆盖配置错误、API 模拟响应、归一化及自定义提供者。真实 embedding 服务和新的本地目录模式尚未联调。 |
| PDF 与原图 | 离线测试覆盖正文、表格、扫描页渲染和读取。OCR 与真实视觉问答尚未完整验收。 |
| 模型错误定位 | 当前测试区分 HTTP、超时、连接失败、响应结构错误、空内容、输出截断、无效 JSON。使用模拟响应验证。 |

本轮修正了查询计数，工具一次执行两个不同查询即可满足补搜条件。新增回归验证该场景无需额外 search。当前模型请求不自动重试，避免增加不可见调用。

## 结果解读与限制

自动检查比较状态、必要引文和重试次数，人工仍需核对整段答案是否受证据支持。所有材料为合成资料，结果不能代表企业大语料的召回率。主题与显式链接的质量影响冲突查证完整性。

旧模型错误记录未区分网络与输出格式问题，无法仅凭历史日志确定原因。最新适配器能记录具体类别，但没有重现之前的服务异常。

语义审核及 conversation 分类依赖模型，可能遗漏错误。检索可能召回不相关资料，当前失败处理较保守。内存索引启动成本、图像上下文大小和复杂版面处理仍需针对真实规模验证。

历次离线日志保留在 examples，包括 [初始测试](../examples/test-results.txt)、[证据包测试](../examples/search-bundle-tests.txt)、[双语测试](../examples/bilingual-tests.txt)、[向量原型测试](../examples/semantic-tests.txt)、[路由测试](../examples/prompt-tests.txt) 和 [后端接口测试](../examples/embedding-provider-tests.txt)。


## 完整考核规范补齐

| 要求 | 当前材料 |
|---|---|
| 无密钥离线入口 | python -m knowledge_agent.offline，明确标注预设流程和 Mock 审核。 |
| 正常、资料不足、工具失败的离线运行 | [正常](../examples/offline-normal.json)、[冲突](../examples/offline-conflict.json)、[不足](../examples/offline-missing.json)、[工具失败](../examples/offline-tool-failure.json) |
| 执行上限 | --max-steps 默认 18；[单步上限示例](../examples/budget-limit.json) 返回 incomplete。 |
| 步骤、参数、返回与决策依据 | [本次完整真实记录](../examples/submission-live.jsonl) 的 actual.trace 中提供 step、decision、工具观察和最终动作。 |
| 全部业务验收 | 八组用例包括六项必验、原文替换和明确替代关系，本次自动检查 8/8 通过。 |
| 题号与实际用时 | 第三题，用户确认未计时。 |
| GitHub 提交 | [GitHub 仓库](https://github.com/lxcin/enterprise-knowledge-agent) 为私有，评审访问权限由提交者按指定账号设置。 |

本次 normal 路径为 search → finish；missing 路径为 search → 换词 search → finish；tool-failure 路径在检索观察到 D02 两次读取失败后 finish，程序返回 tool_error。实际工具参数和简要依据均在记录中，模型内部思维过程未作为交付材料。

[首次带步骤的记录](../examples/submission-live-initial.jsonl) 中部分动作缺少 reason。之后把 reason 设为必填并重新执行，最终记录的已执行动作均包含操作依据。离线测试相应标记了预设动作理由。

自动检查通过仍不代表自然语言表述没有缺陷。本次 paraphrase 回答把正常期限称为“最晚”，随后给出逾期审核条件；人工评审应确认这种措辞不会被理解为绝对禁止逾期。语义精度继续作为已知限制。
