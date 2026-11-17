# VeriFlow — 自然语言 → 形式化验证 → 修复的工作流原型

VeriFlow 从自然语言描述出发，自动生成标准化 JSON 工作流，构建 JCPN（JSON-based Colored Petri Net）模型，
运行可达图形式化验证与缺陷定位，生成修复建议并在用户确认后应用，最终交付可验证的正确工作流。

形式化内核的实际语义、与设计记号的对应关系、以及明确的实现边界见
[`docs/FORMAL_CORE.md`](docs/FORMAL_CORE.md)。

## 快速启动

```powershell
cd veriflow
python -m pip install flask   # 首次
python app.py
```

启动后浏览器打开 http://127.0.0.1:5000 （本地地址，仅本地部署运行时使用；默认中文界面，顶部可切 EN）。

试用输入示例：
- 学生请假审批流程，三天以内辅导员审批，超过三天学院审批，通过后通知学生并登记
- 订单来了先校验库存，够就发货，不够通知补货，最后都通知客户
- 每天早上拉取业务数据，生成报表，推送日报

## 闭环流程（右侧 10 阶段管道）

需求录入 → 需求解析 → 需求澄清（必要时询问）→ 需求确认 →
流程规划 → JSON 中间表示 → JCPN 建模 → 形式化验证 →
缺陷修复（用户确认后应用）→ 输出工作流

### 澄清阶段的行为契约

澄清是"必要处确认"，不是"反复追问"，因此有三条硬约束：

1. **答案落槽位，不拼回原文**：`answers` 按 `question_id` 写入结构化槽位
   （`q_topic→topic`、`q_action→action`、`q_else→else`、`q_msg_platform→msg_platform`），
   主题槽位优先于原文关键词。把答案拼成一段新描述再重新猜测，会让"自生成"意图与
   缺主题同时成立，从而同一问题无限重问。
2. **主题必有出路**：主题命中模板 → 模板实例化；不入模板库 → 生成"主题骨架"
   （`gen_stage=generic_from_topic`，三步最小链），并在 `workflow.assumptions`
   里声明"步骤是骨架、业务动作待补充"。宁可交一个标注清楚的粗工作流，也不假装读懂。
3. **澄清预算**：同一个 `question_id` 只问一次。第二轮即使用户没答上来，也强制生成，
   并在阶段记录里标 `clarification_exhausted`。因此管道一定终止，不会死循环。

前端把 `options` 渲染成可点选芯片，点选即回答；自由文本回答仍可用，作用于当前
第一个未答问题。

## API

| 端点 | 说明 |
|---|---|
| `GET /` | 前端页面（webui/） |
| `POST /api/generate` | `{text}` → 管道执行；歧义时返回 `awaiting_clarification` + 澄清问题 |
| `POST /api/clarify` | `{text, answers}` → 按 question_id 落槽位后重新生成（同一问题不再重复追问） |
| `POST /api/confirm` | `{accepted: [repair_id]}` → 应用修复并重验证 |
| `POST /api/export` | 导出最终 JSON |
| `GET /api/health` | 健康检查 |
| `GET /api/samples` | 真实平台样本逐样本检测（顶栏"样本与检测过程"按钮加载） |

## 目录结构

```
veriflow/
├── app.py                  Flask 后端（阶段状态机 + REST）
├── nl2json.py              自然语言 → 标准化 JSON（模板库 + 规则引擎，可选 LLM）
├── preprocess.py           语法规范化（只报错不修复语义缺陷）
├── jcpn_builder.py         JCPN 建模（颜色/弧表达式结构 + provenance 映射 μ）
├── verification.py         可达图验证（绑定语义、终止标识分类、SCC 非终止、截断处理）
├── repair.py               修复建议 + 应用 + 结构校验 + 重验证闭环
├── adapters.py             平台适配器（n8n / Dify / Coze）
├── graph_static_checker.py 图结构基线 + JSON Schema 基线
├── defect_injector.py      缺陷注入器（受控负样本，注入点限定在主入口可达路径）
├── evaluation_strict.py    严格口径评估（松口径 / 严格 / 消融三档 + 定位）
├── export_report.py        把严格口径结果导出成网页用的 full_experiment_report.json
├── precompute_samples.py   逐样本预计算（供 /api/samples，避免线上实时跑）
├── tests/test_formal_core.py  形式化内核回归（24 例）
├── docs/FORMAL_CORE.md     形式化内核说明与实现边界
├── real_samples/           95 个真实平台工作流（n8n 41 / Dify 24 / Coze 30）
└── webui/                  双语前端（index.html / app.js / styles.css）
```

`real_samples/` 是全部真实样本（n8n 41、Dify 24、Coze 162 采集池；评测按 seed=42 取其中 30 个 Coze 为底版），来源与许可见 [`real_samples/SOURCES.md`](real_samples/SOURCES.md)。

## 评估（当前代码实测，严格口径）

数据：95 个真实平台底版（n8n 41 / Dify 24 / Coze 30）+ 460 个受控注入缺陷（6 类）。
状态上限 20000；定位真值 = 注入前后结构差异涉及的节点集合（不读注入器标签）。

| 口径 | Precision | Recall | F1 | Accuracy |
|---|---|---|---|---|
| L 松（任一缺陷即 TP，旧口径） | 99.8% | 100.0% | 99.9% | 99.8% |
| **S 严格（类型 + 定位）** | **99.8%** | **99.8%** | **99.8%** | **99.6%** |
| A 消融（只用状态空间，去掉静态类型规则） | 99.7% | 80.2% | 88.9% | 83.4% |

同数据基线：Graph static P98.7 / R81.5 / F1 89.3 / Acc83.8；JSON Schema P0 / R0（只查语法，查不出语义缺陷）。

`real_samples/` 是全部真实样本（n8n 41、Dify 24、Coze 162 采集池；评测按 seed=42 取其中 30 个 Coze 为底版），来源与许可见 [`real_samples/SOURCES.md`](real_samples/SOURCES.md)；注入方式见 `defect_injector.py`，逐条检测见网页「样本与检测过程」（`/api/samples`）。

按类命中率（严格）：abnormal_loop 100% · broken_message 99.0% · isolated_node 100% ·
missing_branch 100% · unreachable_node 100% · variable_constraint 100%（消融口径 0%，
即该类完全依赖静态类型规则）。按平台：n8n 100% · Coze 100% · Dify 99.2%。

> 口径说明（与上一版相比改了什么，为什么）：
> 1. **Dify iteration 子画布不再拍平**。迭代体节点带 `iteration_id`，容器到子图入口没有显式边；
>    旧适配器把它们当顶层节点，子图直接判不可达。现在按内部边还原成 `while.body`（仅线性链，
>    否则如实告警并保持拍平）。`dify_webrag.yml`、`difyaws_claude3_code_translation.yml` 因此从
>    误报变为通过。
> 2. **Dify if-else 按 n 路分支建模**。`sourceHandle` 的 case UUID 原样作为分支标签，
>    不再降维成 `false`；`difyaws_generate_image_video.yml`、`simple_kimi` 一类多 case 样本的漏检随之消失。
> 3. **悬空分支按平台语义 = 实例结束**，并入 `P_f` 并写 `implicit_termination` 记录；
>    `difyaws_apply_guardrails.yml`（官方样例，if 只有 true 边）因此不再算缺陷。
>    需要 WF-net 严格读法时用 `VERIFLOW_STRICT_BRANCH=1`，此时该类以 `missing_branch` 呈现。
> 4. **注入器的 missing_branch 改为「摘掉分支子图」**：只删分支边、保留目标子图，缺陷的可观察后果是
>    子图不可达；按平台语义，单纯删边而不留子图并不构成缺陷。
> 5. **截断不再输出未证实结论**：状态超限时，依赖可达图的死锁/残留/非终止/从未触发一律抑制，
>    只报 `analysis_incomplete` 并列出被抑制项；静态可判的结构不可达与类型规则照常上报。

### 干净底版上的报告（1 个真阳性 + 1 个结论不可用）

| 底版 | 报告结论 | 判定 |
|---|---|---|
| `difyaws_AgentCore-Memory-1.yml` | 2 条 unreachable_node（`mechanism=no_structural_path`） | **真阳性**：原始 DSL 里 `1759201306129 -> 17592016133500` 是一个没有任何入边的独立组件，任何引擎都跑不到它；不计入误报（`clean_fp_counts.adjusted=0`） |
| `difyaws_eks_upgrade_planning.yml` | `analysis_incomplete` | 状态空间超过 20000，结论不可用；不算缺陷、不算"通过" |

上一版列出的 5 个误报中，`dify_webrag.yml`、`difyaws_claude3_code_translation.yml`（iteration 拍平）、
`difyaws_apply_guardrails.yml`（单分支 if）已由语义修正消除；`eks_upgrade_planning` 由"8 deadlock + 8 missing_branch"
改为只报"结论不可用"。

### 已知的漏检/边界（不隐藏）

- 严格口径 1 例漏检：`broken_message` 注入到 `difyaws_eks_upgrade_planning.yml`（截断底版），
  状态空间结论被抑制，只能报 `analysis_incomplete`。这是"宁可说不知道"的代价。
- `variable_constraint` 的检出完全来自静态类型规则（`output_type != input_type`），
  可达图本身对该类不敏感；消融口径把它去掉了，所以消融 F1 为 88.9%。
- "消息是否需要应答"仍来自平台适配层的 `pairing` 字段：若适配器把应答型消息标成通知型，
  该缺陷不会被发现（见 `docs/FORMAL_CORE.md` §5）。
- Coze 的循环容器（type 28/21）仍按拍平处理（数据集前 30 个 Coze 样本中未出现循环节点），
  若出现循环体子图，同一套线性链判定逻辑尚未接入。
- 分支语义、截断纪律、静态不可达的完整说明与两种读法的开关见 `docs/FORMAL_CORE.md` §4.1、§8、§9。

### 网页上的检测清单

`/api/samples` 返回 `checklist`（9 条性质：选项可完成性、正确完成性、无死变迁、终止性、
分支完整性、消息配对、类型化数据流、结构合法性、截断诚实性），每条写明形式化依据、
判定方式（`static` / `state_space` / `meta`）与可靠性边界；同一次响应还带
`by_type`、`by_platform`、`clean_fp`、`clean_fp_counts`、`clean_inconclusive`、`semantics`，
页面「样本与检测过程」直接渲染这些字段，避免网页与内核口径脱节。

## 复现

```powershell
python -m unittest discover -s tests -v        # 形式化内核回归（24 例，含两种分支读法）
python evaluation_strict.py                    # 三口径评估（约 110 s，写 evaluation_strict_report.{json,md}）
$env:VERIFLOW_STRICT_BRANCH="1"; python evaluation_strict.py   # 严格读法口径（可选）
python export_report.py                        # 同步到网页用的 full_experiment_report.json
python precompute_samples.py                   # 重新生成 samples_precomputed.json（95 样本，约 26 s）
```

## 已知局限

- variable_constraint（数据域不一致）不自动修复，需人工复核（对应"不修复语义缺陷"边界）。
- 模板库内置 8 个高频场景；未命中时走通用步骤解析，复杂嵌套结构建议提供更完整的描述。
- 会话状态存内存（单用户演示），生产需换持久化。
- 并行分支按 OR-join 处理（与 n8n / Dify 实际执行一致），不是严格 AND-join 的同步语义（见 docs/FORMAL_CORE.md §6）。
- 状态空间上限 20000 是为 Render 免费实例的内存留出的余量；超限时只报"结论不可用"，不猜测。
