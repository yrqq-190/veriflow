# VeriFlow 扩大规模评估（全量真实底版）

> 数据集：三平台公开导出的真实工作流，共 188 个 JCPN 验证干净的底版
> （n8n 8 / Dify 18 / Coze 162），
> 每个底版保留 1 个干净版本并受控注入 1 个缺陷，共 **376 个评测样本**。
> 缺陷类型分布：missing_branch 7、isolated_node 46、abnormal_loop 45、broken_message 45、variable_constraint 45。
> missing_branch 仅 7 个，因真实模板中条件分支节点较少（Coze 短视频流水线几乎无 if/else），属真实分布。

## 方法对比

| Method | Precision | Recall | F1 | Accuracy |
| --- | --- | --- | --- | --- |
| B1: JSON Schema | 0.0% | 0.0% | 0.0% | 50.0% |
| B2: Graph static checker | 100.0% | 51.6% | 68.1% | 75.8% |
| **Proposed: JCPN** | **100.0%** | **100.0%** | **100.0%** | **100.0%** |

## JCPN 混淆矩阵

| | Actually defective | Actually non-defective |
| --- | --- | --- |
| Detected | 188 (TP) | 0 (FP) |
| Not detected | 0 (FN) | 188 (TN) |

## 各缺陷类型检出数

| Defect | Injected | JCPN | Graph | Schema |
| --- | --- | --- | --- | --- |
| missing_branch | 7 | 7 | 6 | 0 |
| isolated_node | 46 | 46 | 46 | 0 |
| abnormal_loop | 45 | 45 | 45 | 0 |
| broken_message | 45 | 45 | 0 | 0 |
| variable_constraint | 45 | 45 | 0 | 0 |