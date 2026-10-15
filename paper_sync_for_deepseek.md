# 同步给 DeepSeek 的论文修改材料：Baseline 强化 + Table 3 真实数据

> 用途：本文档自包含，可直接整段发给 DeepSeek。目标是让它独立完成 JSS 论文中
> （1）基线体系强化（按审稿人意见新增 graph-based static checker）、
> （2）实验数据集与 Table 3 结果更新（真实平台数据，50 个评测样本）。
> 下面 **【中文】** 是给使用者的操作说明，**【英文正文】** 是可直接替换进论文的英文段落。
> 所有数字均为代码实跑结果（2026-10-15），脚本与数据在 GitHub 仓库 `yrqq-190/veriflow`。

---

## 一、审稿人意见（要回应什么）

【中文】审稿人指出：现有三个 baseline（manual / JSON Schema / end-to-end execution）
里，JSON Schema 只是语法校验，**不是 behavioral verification 的有竞争力的对照**。
要求：要么增加一个更强的自动化基线 **graph-based static workflow checker**
（含 reachability、in/out degree、branch completeness、SCC/loop、message pairing），
要么充分论证现有三个基线已足够回答研究问题。

【中文】我们已经按第一条意见**实现并评估**了这个强基线（记为 B2），并把 JSON Schema
严格限定为纯语法基线（B1），manual inspection 保留为 B3；对 end-to-end execution
testing 给出"为何不作为主对照"的说明。这是最稳妥的回应方式，不要试图只靠文字辩护。

---

## 二、系统现在实际做到了什么（供 DeepSeek 准确表述，勿夸大）

【中文】以下是已实现、可运行、已用真实数据验证的模块。

### 2.1 B1 — JSON Schema validation（纯语法基线）
- 检查项：每个节点的必填字段（task/message/if/while 的最小字段）、节点类型枚举、
  节点 ID 唯一性、边引用完整性（边的端点必须存在）。
- **不包含**任何行为规则：不检查分支是否完整、循环是否有出口、节点是否可达、消息是否配对。
- 这是有意为之：Schema 是"字段/结构约束"的代表，受控注入保持 JSON 语法有效，
  因此它对五类语义缺陷的检出为 0 —— 这正是"Schema 不是行为验证"的实证。

### 2.2 B2 — Graph-based static workflow checker（新增的强基线，审稿人点名的五项全覆盖）
输入仅为节点/边/字段，**不构建状态空间、不做可达图分析**：
1. **Reachability**：从结构入口（入度为 0 且非孤立的节点）做 BFS，标记未访问节点为不可达。
2. **In/out degree**：入度与出度均为 0 的节点判为孤立节点。
3. **Branch completeness**：if 节点缺少 `else` 声明、且不存在 `branch=false` 的出边时，
   判为缺失分支。
4. **SCC / loop**：用 **Tarjan 算法**计算强连通分量，对存在环且无出边到分量外的 SCC
   报告非终止循环风险；同时识别显式声明 `exit ≠ true` 的 while 节点。
5. **Message pairing**：消息节点无后继（发送后流程无以为继）判为消息断裂；
   但对 Dify/Coze 的 `answer` 类**单向回复型终端**（send-only + out，输出即合法结束）豁免，
   避免误报。
- **能力边界（要在论文里写清楚，这是 JCPN 的增益来源）**：
  - 无法识别"消息节点有出边、但发送后没有对应接收节点"的配对语义问题；
  - 无法识别数据类型/数据颜色约束冲突。

### 2.3 Proposed — JCPN verification
- 可达图（reachability graph）分析：不可达节点、意外死锁、非终止循环（SCC）。
- 显式 provenance 映射 μ（source JSON id → JCPN 元素），支持把缺陷回溯到源节点。
- 消息适配语义：n8n 配对模式；Dify/Coze 仅映射 `t_send`，发送后无接收的保留为
  broken-message 候选。
- 数据颜色集 Θ_data 一致性检查：相邻任务的输出颜色（output_type）与输入颜色
  （input_type）不一致时报告 variable-constraint error（**轻量实现，仅在显式类型标注下生效，
  不建模完整数据域传播与变量作用域**——这是 future work，不要写成已完全解决）。

### 2.4 真实数据集（这是重点，替换原稿的合成数据描述）
- 从 **n8n 和 Dify** 公开导出的真实生产模板采集（GitHub 官方/社区仓库；
  其中 21 个 Dify DSL 来自 `aws-samples/dify-aws-tool`，MIT-0 许可）。
- 共采集 **36 个真实工作流**（n8n 11、Dify 25）；Coze 因工作流导出属于付费功能、
  公开渠道无 DSL，未纳入（适配器 `parse_coze` 已按规范实现，留作未来数据）。
- 选取其中 **25 个通过 JCPN 验证的干净底版**（节点数 3–30；平台分布 n8n 8、Dify 17），
  覆盖审批、RAG 问答、LLM Agent、翻译、代码解释、图像/视频生成、MCP、通知等。
- 对每个底版保留 1 个干净版本、并注入 **1 个**受控缺陷，得到 **50 个评测样本**。
- 五类缺陷，每类 5 个：missing branch / isolated node / abnormal loop /
  broken message interaction / variable-constraint error。
- 每次注入都保持 JSON 语法有效（注入后再做语法校验）。
- 【中文】受控注入的 ground truth 是确定的（缺陷类型与位置由注入器记录）。
  原稿里"two annotators, 96% agreement"的表述若要保留，应改为针对**采集底版的正确性/
  缺陷候选的人工核验**，而不是对自动注入负样本的标注；请 DeepSeek 调整措辞，避免失实。

### 2.5 Table 3 实测结果（50 个真实样本；请直接使用这些数字，不要沿用旧稿数字）

| Method | Precision | Recall | F1 | Accuracy |
| --- | --- | --- | --- | --- |
| B1 JSON Schema validation | 0.0% | 0.0% | 0.0% | 50.0% |
| B2 Graph-based static checker | 100.0% | 60.0% | 75.0% | 80.0% |
| **Proposed JCPN method** | **100.0%** | **100.0%** | **100.0%** | **100.0%** |

JCPN 混淆矩阵：TP=25，FP=0，FN=0，TN=25。

各缺陷类型检出数（每类注入 5 个）：

| Defect type | Injected | JCPN | Graph | Schema |
| --- | --- | --- | --- | --- |
| Missing branch | 5 | 5 | 5 | 0 |
| Isolated node | 5 | 5 | 5 | 0 |
| Abnormal loop | 5 | 5 | 5 | 0 |
| Broken message interaction | 5 | 5 | 0 | 0 |
| Variable-constraint error | 5 | 5 | 0 | 0 |

【中文】如何读这张表（务必让 DeepSeek 在正文讲出这个故事）：
- B1 Schema 对五类行为缺陷全部漏检（Recall 0），证明语法/字段校验不是行为验证。
- B2 Graph 能检出三类**纯结构**缺陷（缺分支、孤立、无出口环），但对**消息配对语义**和
  **数据颜色约束**两类缺陷无效（Recall 60%）——这正是它与形式化方法的差距。
- JCPN 在可达图 + provenance 回溯之外，额外建模消息配对与数据颜色，故五类均检出。
- 100% 是**受控注入**（每类缺陷都在检测能力范围内）下的结果，正文需明确这一限定；
  并说明真实（未注入）模板上仍有需人工复核的复杂情形（如 Dify iteration 迭代节点），
  避免给审稿人"完美得不真实"的印象。
- Graph 对 25 个干净底版 FP=0（Precision 100%），说明这是一个公平的强基线，而不是稻草人。

---

## 三、建议替换进论文的英文正文

### 3.1 Baselines 段落（替换原稿中关于三种 baseline 的两段）

**【英文正文】**
To compare the proposed approach with common forms of workflow validation, four reference points are considered. The first is **manual inspection**, in which reviewers with workflow-modeling experience judge correctness from the representation. The second is **JSON Schema validation**, which is restricted to syntactic and field-level constraints—required fields, node-type enumeration, identifier uniqueness, and referential integrity of edges—and deliberately contains no behavioral rules. The third is an **automated graph-based static checker** that operates only on the workflow graph (nodes, edges, and node-level attributes) and implements five structural checks: (i) reachability from the structural entry nodes by breadth-first search; (ii) in/out-degree analysis for isolated nodes; (iii) branch completeness for conditional nodes; (iv) non-terminating-loop detection via strongly connected components (Tarjan's algorithm) together with explicit loop-exit declarations; and (v) message-endpoint analysis that flags a message node with no successor, while exempting platform-native single-reply terminal nodes (e.g., Dify/Coze answer nodes). The fourth is the **proposed JCPN verification**.

These reference points are ordered by the depth of behavioral semantics they capture: human review, syntactic validation, graph-structural analysis, and state-space formal verification. End-to-end execution testing was considered as an additional dynamic baseline but is not reported as a primary comparator because the defect classes of interest—particularly unreachable branches, missing responses, and non-terminating loops—are either non-executable or do not terminate under the very defects being tested, and dynamic execution requires concrete runtime data and external service bindings that are not available for exported templates. It is discussed as a complementary technique rather than a structural comparator.

The graph-based static checker is deliberately a strong baseline: it incorporates the exact static analyses that do not require a state space, so any gap between it and JCPN can be attributed specifically to the semantic elements the graph abstraction cannot express—message pairing and data-color consistency—rather than to an artificially weak comparator.

### 3.2 Dataset 段落（替换原稿关于 50 个模板与标注的段落）

**【英文正文】**
The evaluation dataset was constructed from public workflow templates collected from n8n and Dify. Templates were retained when they provided explicit node types and explicit control-flow relations; after removing non-executable canvas artifacts and duplicate cases, 36 real exported workflows (11 from n8n, 25 from Dify) were collected, spanning approval flows, retrieval-augmented question answering, LLM agents, translation, code interpretation, image/video generation, MCP integrations, and notification workflows. Coze workflows were not included because workflow export is restricted to paid plans and no DSL sample is publicly available; the Coze adapter is implemented according to the platform specification and reserved for future data.

From these templates, 25 base workflows verified as defect-free (between 3 and 30 nodes; 8 n8n and 17 Dify) were selected. Each base workflow contributes two cases: one clean case and one defective case produced by a single controlled mutation, yielding 50 cases in total. The mutation preserves JSON syntactic validity, which is re-checked after injection, and covers five defect categories—missing branch, isolated node, abnormal loop, broken message interaction, and variable-constraint error—with five cases per category. Because the mutation type and location are recorded by the injection tool, the defective cases carry a deterministic ground truth. Collected templates on which the verifier reported candidate defects were kept separate from the clean benchmark set and are reported separately, as the most complex of them (containing iteration constructs) require manual confirmation.

### 3.3 Results 段落（配 Table 3）

**【英文正文】**
Table 3 reports the results over the 50-case benchmark. JSON Schema validation attains zero recall on the behavioral defects: every injected mutation remains syntactically valid, which empirically confirms that field- and schema-level validation is not behavioral verification. The graph-based static checker reaches 60% recall and 75% F1 with no false positives on the clean cases: it detects the three purely structural categories—missing branches, isolated nodes, and non-terminating loops—including the latter through strongly connected component analysis. It cannot, however, detect the two categories that depend on semantics not present in the graph abstraction: broken message interaction (a message that is sent but has no corresponding receive, even when it retains an outgoing edge) and variable-constraint errors (data-color mismatch between adjacent tasks). The proposed JCPN method reaches 100% precision and recall over the controlled benchmark, owing to its explicit message-pairing model and the Θ_data color-consistency check in addition to reachability-graph analysis.

These results should be interpreted within the scope of controlled mutation, in which each injected defect lies within the detection capability of the corresponding mechanism. They quantify the incremental value of the formal model: the graph checker already captures the structural defect classes, while JCPN's additional gain is concentrated on message and data semantics, which is precisely where the graph abstraction is blind. The data-color consistency check is currently lightweight, validating adjacent-edge colors only when nodes declare explicit input/output types; full data-domain propagation and variable-scope analysis remain future work.

### 3.4 Threats to validity / limitations 可增补的两句

**【英文正文】**
Two limitations should be acknowledged. First, the controlled-injection design favors defects that are expressible and detectable by construction; the reported 100% recall therefore indicates complete coverage of the five defined categories rather than open-world performance, and the candidate defects found on unmutated templates suggest that iteration-heavy workflows remain a source of modeling uncertainty. Second, the benchmark is weighted toward n8n and Dify; including Coze exports and richer data-domain annotations would be needed to validate the variable-constraint analysis beyond explicit type declarations.

---

## 四、数字与图表的一致性检查清单（请 DeepSeek 改完自查）

1. 表格里不能再出现旧稿的 89.7% 或合成数据的数字；以本文 2.5 节为准。
2. 基线数量与命名统一：B1 JSON Schema / B2 Graph-based static checker / B3 Manual inspection，
   外加 Proposed JCPN；execution testing 只作为"未纳入主对照的补充讨论"。
3. 五类缺陷命名全文统一（missing branch, isolated node, abnormal loop,
   broken message interaction, variable-constraint error）。
4. 强调 B2 是**强基线**（25 干净底版零误报），JCPN 增益落在消息配对与数据颜色两类。
5. 必须出现 controlled-mutation 限定与 iteration 人工复核、数据颜色轻量实现的局限说明。
6. 数据来源平台：n8n、Dify；36 个真实模板 → 25 干净底版 → 50 个评测样本；
   Coze 因付费导出缺失。
7. 不要再声称 JSON Schema 能检查分支/循环出口（行为规则已从该基线剥离，归到 B2）。
