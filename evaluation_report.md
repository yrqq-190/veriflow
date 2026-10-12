# JCPN 工作流验证系统 —— 评估报告

> 对应论文《From JSON to Colored Petri Nets: Formal Verification and Defect Localization for LLM-Generated Workflows》§4.2 实验。

## 1. 数据集

- 测试用例总数：**50**（含缺陷 25 个，正常 25 个）
- 缺陷类型分布：Missing branch ×8、Isolated node ×6、Abnormal loop ×5、Broken message ×4、Variable-constraint ×2（与论文 Table 2 一致）
- 用例规模：5 ~ 12 个节点（含嵌套），来源平台 n8n / Dify / Coze 混合

## 2. 方法对比（对应论文 Table 3）

| Method | Precision | Recall | F1 score | Accuracy | Mean time |
| --- | --- | --- | --- | --- | --- |
| JSON Schema | 100.0% | 52.0% | 68.4% | 76.0% | 0.0 s |
| Graph static checker | 95.0% | 76.0% | 84.4% | 86.0% | 0.0 s |
| Proposed JCPN method | 95.8% | 92.0% | 93.9% | 94.0% | 0.0006 s |

## 3. JCPN 混淆矩阵（对应论文 Table 5）

| | Actually defective | Actually non-defective |
| --- | --- | --- |
| Detected as defective | 23 (TP) | 1 (FP) |
| Detected as non-defective | 2 (FN) | 24 (TN) |

- Accuracy = (23 + 24) / 50 = 94.0%
- Precision = 23 / (23 + 1) = 95.8%
- Recall = 23 / (23 + 2) = 92.0%
- F1 = 93.9%；False-positive rate = 1 / (1 + 24)；False-negative rate = 2 / (2 + 23)

## 4. 缺陷类型检出明细

| Defect type | Total | JCPN | Graph | Schema |
| --- | --- | --- | --- | --- |
| missing_branch | 8 | 8 | 8 | 8 |
| isolated_node | 6 | 6 | 6 | 0 |
| abnormal_loop | 5 | 5 | 5 | 5 |
| broken_message | 4 | 4 | 0 | 0 |
| variable_constraint | 2 | 0 | 0 | 0 |

## 5. 误报 / 漏报分析（对应论文 §4.3.2）

- **JCPN 误报（FP=1）**：wf_026。该用例的循环出口条件依赖数据更新（counter 上限），当前 Θ_cond 布尔抽象下 false 分支不可达，验证器按论文 §3.3.4 保守报告 non-termination 风险。
- **JCPN 漏报（FN=2）**：wf_024, wf_025。两例为相邻任务数据依赖不一致（integer → string），JCPN 当前不建模数据域约束，与论文报告的局限一致。
- **图静态检查器误报（FP=1）**：wf_034。Dify/Coze 出站消息作为流程终点，图检查器按“消息无出边”误判 broken message，而 JCPN 经消息适配器语义正确放行。

## 6. 可扩展性（对应论文 Table 4）

| Nodes | Places | Transitions | State-space size | Verification time |
| --- | --- | --- | --- | --- |
| 5 | 8 | 7 | 8 | 0.0 s |
| 10 | 17 | 16 | 17 | 0.001 s |
| 20 | 33 | 32 | 33 | 0.001 s |
| 30 | 51 | 50 | 51 | 0.003 s |
| 50 | 83 | 82 | 83 | 0.005 s |
| 80 | 133 | 132 | 133 | 0.011 s |

## 7. 结论

- 形式化状态空间分析（JCPN）显著优于纯图结构与 Schema 基线，命中率达到论文报告的 F1 = 93.9%。
- 消息适配器（n8n 配对 / Dify·Coze send-only）消除了结构检查器的系统性误报。
- 数据依赖类缺陷（variable-constraint）仍是当前抽象的已知边界，需引入类型/约束建模扩展（论文 future work）。
