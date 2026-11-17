# VeriFlow 形式化内核说明（FORMAL CORE）

本文件描述 `jcpn_builder.py` / `verification.py` / `repair.py` 里**实际实现**的
语义，以及它与设计记号（JCPN = (P, T, A, Θ, C, G, X, M₀, P_f, U, μ)）的对应关系。
凡是早期设计表述与实现不一致的地方，这里都以实现为准并注明差异，避免"文档说一套、代码做一套"。

---

## 1. 颜色与弧表达式

token 颜色是一个冻结数据类：

```python
Color(kind="data"|"msg", dtype="string"|"integer"|"any", cond="true"|"false"|"<case id>"|None, mid="msg_x")
```

- `kind="data"`：业务数据 token，`dtype` 是数据域，`cond` 记录分支标签（只在分支库所上非空）。
  标签是字符串而非布尔值：Dify 的 if-else 有 n 个 case，用 `true`/`false`/case id 统一表示，
  不会把多个互斥 case 压成同一个分支。
- `kind="msg"`：消息 token，`mid` 是消息标识（`msg_<node_id>`）。
- `dtype="any"`：适配器未声明类型时的保守取值，与任何数据域兼容（不代表"类型正确"，只代表"未知"）。

弧表达式是结构化对象 `Expr(op="consume"|"produce", kind="data"|"msg", arg=..., cond=...)`，
**不做字符串求值**，因此不存在注入风险，也不存在"表达式写了但从不执行"的装饰性字段。

颜色集：

| 记号 | 实现 | 含义 |
| --- | --- | --- |
| Θ_data | `model.Theta_data` | 出现过的数据域集合（`any` 始终在） |
| Θ_msg | `model.Theta_msg` | 出现过的消息 id 集合 |
| Θ_cond | `model.Theta_cond` | 分支标签族（取值为 `true`/`false`/平台 case id） |
| C(p) | `model.C[p]` | 库所的颜色族，多个族用 ` ∪ ` 连接 |

`C(p)` 出现 `Θ_data ∪ Θ_cond` 是**正常**的：一个库所可以同时接收数据 token 与分支 token。
只有消息 token 与数据 token 合进同一库所才记为 `model.warnings`（语义混淆）。

## 2. 弧与多重性

`model.arcs[(u,v)]` 是 `Expr` 列表；同一对端点上的多条弧全部保留（弧多重性），
`model.X[(u,v)]` 是它的人类可读形式（` ⊗ ` 连接），仅用于展示与 `app.py` 的模型摘要。

合并库所时，弧列表 `extend` 而不是覆写——旧实现里 `X[(t_cond,p_then)]` 与
`X[(t_cond,p_else)]` 塌成同一键、后写覆盖先写、导致 `c=true` 弧消失的问题不会再出现。

## 3. 使能：CPN 绑定语义

一个变迁 `t` 在标识 `M` 下使能，当且仅当存在绑定 `b`：

1. 对每条输入弧 `(p,t,e)`，选一个 token `c ∈ M(p)`，满足 `e` 与 `c` 的颜色匹配；
   同一库所的多条输入弧必须选**不同** token（弧多重性）；
2. 守卫 `G(t)` 在绑定 `b` 上求值：

| 守卫 | 解释 |
| --- | --- |
| `true` / 空 | 恒真 |
| `false` | 恒假（该变迁不可触发） |
| `[c = true]` / `[c = false]` | 绑定中存在带条件颜色的 token 时按值判定；不存在则记为 **open**（两种结果都可能，不假装判定过） |
| 其他自然语言条件 | 记为 open，计入 `stats.open_guard_firings` |

open 不是"猜"：它把"条件未知"显式留在统计里，读者能看出哪些触发是抽象所致。
`MAX_BINDINGS=64` 限制单变迁的绑定枚举，超出计入 `stats.binding_capped`。

## 4. 决策结构

**if**：分支集合由 `_branch_plan(node)` 决定，顺序固定 `true → false → 其余（按标签字典序）`：

| 标签 | 决策变迁 | 分支库所 | 生成的 token |
| --- | --- | --- | --- |
| `true` | `t_cond_then_<id>` | `p_then_<id>` | `data(_, c=true)` |
| `false` | `t_cond_else_<id>` | `p_else_<id>` | `data(_, c=false)` |
| case *k* | `t_cond_case{k}_<id>` | `p_case{k}_<id>` | `data(_, c=<case id>)` |

每条分支都是独立变迁 + 独立库所 + 独立颜色，因此：

- Dify `if-else` 的多 case 不会被降维成"true / false 两路"（旧适配器把额外 case 归到 false，
  导致 3 case 的样本漏检）；
- 两个分支即使汇到同一节点，弧表达式也不会互相覆盖（键不同、颜色不同）。

**分支标签的来源**：适配器在边上写 `branch`（n8n 的 `idx=0/1` → `true/false`；Dify 的
`sourceHandle` 原样保留，含 case UUID）；结构化写法（`then`/`else` 嵌套子树）也登记标签。

### 4.1 悬空分支的终止语义

平台引擎（n8n 的 `If`、Dify 的 `if-else`）允许"条件为假且该分支未连边"，语义是**实例在此结束**。
建模阶段因此把**没有任何后继弧**的分支库所并入完成集 `P_f`，并在 `model.notes` 写
`implicit_termination: if '<id>' branch '<label>' has no target ...`。

设 `VERIFLOW_STRICT_BRANCH=1` 可切回 WF-net 的严格读法：悬空分支不再进 `P_f`，
其残留 token 由 `analyze_terminals` 判为 `missing_branch`（`model.notes` 写 `dangling_branch`）。

两种读法都是**显式**的：默认按平台语义（不产生"官方样例被判缺陷"的误报），
严格读法留给需要 WF-net "proper completion" 口径的场合；`tests/test_formal_core.py`
对两种读法各有一组断言。

缺 `exit` 的 while 不生成 `t_exit`：缺陷保留给验证器，而不是在建模阶段被抹平。

## 5. 消息语义

| `pairing` | 网结构 | 终止行为 |
| --- | --- | --- |
| `send_only`（平台通知） | `p_in → t_send → p_msg → t_deliver → p_out` | 消息被消费，正常完成 |
| `paired` | `p_in → t_send → p_msg → t_recv → p_recv` | 合成接收侧，正常完成 |
| `unpaired`（声明需要接收但网中无接收侧） | `p_in → t_send → {p_msg, p_out}` | 消息 token 无人消费，成为终止标识残留 |

`broken_message` 的判定是**状态空间判定**（消息 token 是否在终止标识里残留），
不再读适配器字段。需要接收这一业务意图仍来自平台适配层（`pairing` 字段），
若适配层把"应答型"消息标成通知型，该缺陷不会被发现——这是已知边界。

## 6. 并发与汇合

一个节点有多个普通后继时，生成**一个** fork 变迁 `t_fork_<id>`：消费一次 token，
对每个后继各写一个 token（AND-split），下游真并发。
汇合处是 **OR-join**：任一到齐即可继续，与 n8n / Dify 的实际执行一致。
这不是 WF-net 的严格语义（严格 AND-join 需要同步），在此显式声明。

## 7. 完成与死锁（WF-net 口径）

- **终止标识**：可达图中没有后继的标识。
- **完成（proper completion）**：终止标识中**所有** token 都在 `P_f`。
- **意外死锁**：终止标识中仍有 `P_f` 之外的残留 token。

残留 token 按颜色族分类：

| 残留 | 缺陷类型 |
| --- | --- |
| 消息 token | `broken_message` |
| 带条件颜色的数据 token 落在**悬空分支库所**（仅严格读法） | `missing_branch` |
| 带条件颜色的数据 token 落在已连边但无法消费的入口库所 | `unexpected_deadlock` |
| 其他数据 token | `unexpected_deadlock` |

同一个源节点的同一类缺陷只报一条，附 `witness_states`（重现次数）与最多 3 条
`witness_paths`（触发路径样本），避免"一个缺陷报上万条"。

## 8. 截断：不完整状态空间下的结论纪律

状态数达到 `max_states`（默认 `20000`）时置 `stats.truncated=True`。此时**只有下近似**：

- 依赖可达图的结论一律**降级为未证实**、不再作为缺陷上报：`unexpected_deadlock`、
  `broken_message`（残留判定）、`missing_branch`（残留判定）、`non_termination_risk`；
- 只报一条 `analysis_incomplete`，其 `suppressed` 字段列出被抑制的结论条数（`uncertain=True`）；
- 静态可判的性质照常上报：结构不可达（见 §9）、`variable_constraint`（静态类型规则）、
  `isolated_node` 等结构问题；
- 页面与报告都标明"结论不可用"，而不是显示"通过"。

这条纪律的代价是真实漏检（实测 1 例注入缺陷落在截断底版上，按未证实处理），
收益是不再把"没探索到"当成"不存在"——审计里"截断即假阳性"的问题由此关闭。

## 9. 静态规则与状态空间结论分开

**结构不可达**（`unreachable_node`，`mechanism="no_structural_path"`）是纯静态判定：
在 P→T→P 结构弧上从 `M₀` 做不动点，若某节点子网的所有变迁都不在可达变迁集里，它永远拿不到
令牌。这是真实可达性的**上近似**——判为不可达一定可靠，且与 `max_states` 无关。
只有在可达图完整时，才补充 `mechanism="never_fired_in_complete_rg"`（结构可达却从未触发）。

`variable_constraint` 来源有两类，通过 `mechanism` 区分：

- `static_type_rule`：沿边比较 `output_type` 与 `input_type`（设计文档 §4.4 的静态类型规则）；
- `typed_consumption_stall`：某变迁声明消费类型 `T`，但该库所的生产侧只产出别的类型。

评估可以剔除静态规则做**消融**（`evaluation_strict.py` 的 ablation 口径），
这样"状态空间本身能查出多少"与"靠字段规则查出多少"不会混在一起。

## 10. 修复闭环

| 缺陷 | 动作 | 语义效果 | 自动 |
| --- | --- | --- | --- |
| `missing_branch`（严格读法） | `connect_false_branch` | false 分支接上汇合点，分支 token 有落点 | 是 |
| `non_termination_risk` / `while` 死锁 | `enable_exit` | 生成 `t_exit`，循环有终止路径 | 是 |
| `unreachable_node` / `isolated_node` | `reconnect_to_tail` | 节点进入可达路径，其变迁开始触发 | 是 |
| `broken_message` | `manual_review` | 需要补接收节点或确认单向发送 | 否 |
| `variable_constraint` | `manual_review` | 需要核对字段类型/依赖 | 否 |

应用时的硬约束：端点必须存在、禁止自环、禁止重复边、禁止把末尾节点接回自身形成环；
任何一条改动只要破坏结构合法性就整条回滚，并在 `applied[i].reason` 里写明原因。
每条成功改动附 `delta`（节点/边增删与字段变更），重验证后附 `_verify_delta`
（缺陷数、类型、可达图规模变化）——"改完就干净了"这种说法不再出现。

旧实现的 `downgrade_send_only`（只改 `pairing` 字段、拓扑一字未动）已删除。

## 11. 与早期设计表述的差异

| 早期设计表述 | 实现 |
| --- | --- |
| ¶113 "分支由守卫选择" | 分支值来自 `cond` 颜色，守卫是 `true`；`while` 的循环/退出口才是守卫 `[c=true]/[c=false]`。条件未知时按 open 处理 |
| Def 4-5 可达图 `→ ⊆ M×T×M` | 已按带标签发生关系实现：同一对状态经不同变迁到达不会被合并 |
| ¶109 颜色使能 | 已按绑定语义实现；`dtype=any` 表示未知而非"匹配任意类型即为正确" |
| 二分支 if（早期设计只给 true/false 两路） | 实现为 n 路分支（`true`/`false`/case *k*），早期设计的两路是其 n=2 特例 |
| ¶174 误报归因 | 以实测为准：干净底版上 1 个真阳性（`difyaws_AgentCore-Memory-1.yml` 的源 DSL 自带悬空组件）+ 1 个结论不可用（状态超限）；原先把 iteration 拍平、单分支 if 当缺陷造成的 4 个误报已消除 |
| 指标口径 | 早期表格为松口径；本仓库主口径为严格口径（类型 + 定位），见 `evaluation_strict_report.md` |

## 11.1 平台容器的建模（Dify iteration / Coze 循环）

Dify 的 `iteration` 容器把循环体放在**子画布**里：子节点带 `iteration_id`，容器到子图入口没有显式边。
适配器（`adapters._nest_dify_iterations`）按子图内部边还原顺序，收进 `while.body`：

- 仅当子图是**线性链**（唯一入度 0 起点、每个节点入度 ≤ 1、无分支边、无跨边界边）才嵌套；
- 否则如实告警 `iteration '<id>' body is not a linear chain ... kept flat` 并保持拍平——
  宁可少建，也不假装建对；
- 迭代次数由上游集合决定，静态模型不知道集合大小，条件写成开放条件
  `iteration over upstream collection`，即"循环体可能执行 0..n 次"，不假造成固定次数。

拍平的后果此前是整段子图被判 `unreachable_node`（3 个 Dify 误报的来源），
嵌套后这两个样本（`dify_webrag.yml`、`difyaws_claude3_code_translation.yml`）验证通过。

## 12. 复现

```bash
python -m unittest discover -s tests -v          # 形式化内核回归（24 例）
python evaluation_strict.py                      # 松 / 严格 / 消融三口径（95 底版 + 460 注入）
VERIFLOW_STRICT_BRANCH=1 python evaluation_strict.py   # 严格读法下的 missing_branch 口径
python precompute_samples.py                     # 重算网页样本面板（samples_precomputed.json）
python export_report.py                          # 导出网页消费的 full_experiment_report.json
python repair.py                                 # 修复闭环自测
python verification.py wf_001                    # 单样本验证（test_cases/）
```

断言清单（与本文一一对应）：

| 测试类 | 对应性质 |
| --- | --- |
| `WhileSemantics` | while 的循环体/出口分离（§4） |
| `FanOutSemantics` | AND-split 与 OR-join（§6） |
| `BranchColorSemantics` | 分支颜色与弧多重性（§1、§4） |
| `MissingBranchDetection` | 悬空分支两种读法（§4.1） |
| `MultiCaseBranches` | n 路分支（§4） |
| `BrokenMessageSemantics` | 消息三态与残留（§5） |
| `TruncationHonesty` | 截断下不下结论（§8） |
| `RepairGuardrails` | 修复的结构硬约束（§10） |
| `MarkingWellFormed` | 标识良构性（§3） |
