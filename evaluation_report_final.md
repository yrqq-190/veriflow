# VeriFlow 缺陷检测端到端评测报告

- 生成时间：2026-10-15 15:32:10
- 测试样本数：23（干净 3 + 注入 18 + 刁难 2）
- JCPN 形式化验证：TP=13  FP=0  FN=7  TN=3
- Precision=100.0%  Recall=65.0%  F1=78.8%

## 逐案例结果

| 案例 | 注入缺陷 | 预期 | JCPN 结果 | 图结构 baseline | |RG| |
|---|---|---|---|---|---|
| [干净] 请假审批 | 无 | 无缺陷 | PASS | 误报:[('broken_message', 'n6')] | 7 |
| [干净] 订单处理 | 无 | 无缺陷 | PASS | 误报:[('broken_message', 'n6')] | 7 |
| [干净] 报销流程 | 无 | 无缺陷 | PASS | PASS | 5 |
| [注入] 请假审批 | missing_branch (missing_branch) | missing_branch | ✓ 检出 | ✓ | 7 |
| [注入] 请假审批 | isolated_node (isolated_node) | isolated_node | ✗ 漏检:['unreachable_node', 'unreachable_node', 'unexpected_deadlock'] | ✓ | 5 |
| [注入] 请假审批 | unreachable_node (unreachable_node) | unreachable_node | ✓ 检出 | ✓ | 5 |
| [注入] 请假审批 | abnormal_loop (abnormal_loop) | abnormal_loop | ✓ 检出 | ✓ | 2 |
| [注入] 请假审批 | broken_message (broken_message) | broken_message | ✓ 检出 | ✓ | 8 |
| [注入] 请假审批 | variable_constraint (variable_constraint) | variable_constraint | ✗ 漏检:[] | ✓ | 7 |
| [注入] 订单处理 | missing_branch (missing_branch) | missing_branch | ✓ 检出 | ✓ | 7 |
| [注入] 订单处理 | isolated_node (isolated_node) | isolated_node | ✗ 漏检:['unreachable_node', 'unreachable_node'] | ✓ | 5 |
| [注入] 订单处理 | unreachable_node (unreachable_node) | unreachable_node | ✓ 检出 | ✓ | 6 |
| [注入] 订单处理 | abnormal_loop (abnormal_loop) | abnormal_loop | ✓ 检出 | ✓ | 2 |
| [注入] 订单处理 | broken_message (broken_message) | broken_message | ✓ 检出 | ✓ | 8 |
| [注入] 订单处理 | variable_constraint (variable_constraint) | variable_constraint | ✓ 检出 | ✓ | 7 |
| [注入] 报销流程 | missing_branch (跳过:no if node with a false branch edge to remove) | missing_branch | — | — | 0 |
| [注入] 报销流程 | isolated_node (isolated_node) | isolated_node | ✗ 漏检:['unreachable_node', 'unreachable_node', 'unreachable_node', 'unreachable_node', 'unreachable_node', 'unexpected_deadlock'] | ✓ | 1 |
| [注入] 报销流程 | unreachable_node (unreachable_node) | unreachable_node | ✓ 检出 | ✓ | 4 |
| [注入] 报销流程 | abnormal_loop (abnormal_loop) | abnormal_loop | ✓ 检出 | ✓ | 2 |
| [注入] 报销流程 | broken_message (broken_message) | broken_message | ✓ 检出 | ✗ | 6 |
| [注入] 报销流程 | variable_constraint (variable_constraint) | variable_constraint | ✓ 检出 | ✗ | 5 |
| [刁难] 嵌套if缺else | 手动构造 | 见说明 | defects=[] | defects=[] | 8 |
| [刁难] 循环里发消息无接收 | 手动构造 | 见说明 | defects=[] | defects=[] | 5 |

## 缺陷类型覆盖

| 缺陷类型 | 说明 | 注入位置 |
|---|---|---|
| missing_branch | 条件节点缺 else 分支 | 删除 if 的 false 边 |
| isolated_node | 节点无入边无出边 | 新增一个孤立 task |
| unreachable_node | 节点不在主链上 | 新增节点但不连入 |
| abnormal_loop | while 无出口 | 去掉 exit=true 和 exit 边 |
| broken_message | 消息发送无接收 | 设 pairing=paired 但无 recv |
| variable_constraint | 数据依赖不一致 | 改字段名制造不一致 |

## 刁难案例说明

- **嵌套 if 缺 else**：外层 if 的 false 分支节点 n6 没有出边，形成死节点
- **循环里发消息无接收**：while body 里发 paired 消息但无对应 recv，死锁在循环内