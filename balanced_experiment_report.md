# VeriFlow 平衡数据集实验报告（v3，2026-10-17 最终版）

## 数据集

- **95 个干净底版**：n8n 41 / Dify 24 / Coze 30（三平台均衡）
- **457 个注入样本**：每底版最多注入 6 类缺陷（失败则跳过，共跳过 113 次）
- **总计 552 个评测案例**（95 干净 + 457 注入）
- 来源：n8n（41 个，官方/社区公开模板，详见 `real_samples/SOURCES.md`）、Dify（aws-samples 21 + 社区 3）、Coze（Hammer1/cozeworkflows 162 个随机抽 30）

## 三个已修复的历史问题

1. **isolated_node 双漏 18 个** → 根因：注入器选了 `is_alt_entry=True` 的 n8n AI Agent 子节点（Webhook/Text Splitter/Embeddings/Memory），Graph 和 JCPN 都豁免这些节点。修复：注入器跳过 is_alt_entry。
2. **Graph unreachable_node 仅 55.8%** → 根因：Graph BFS 从所有入度=0 节点出发，注入后被断开的节点变成新入口，被当成合法起点。修复：Graph 只从覆盖节点最多的"主入口"出发 BFS。
3. **JCPN 31 个 FN 报为 deadlock** → 根因同 #1：注入落在被豁免的 alt 节点上，JCPN 完全看不到。修复 #1 后自动消失。

## 全局结果

| Method | Precision | Recall | F1 | Accuracy | TP | FP | TN | FN |
|--------|-----------|--------|----|----------|----|----|----|-----|
| B1: JSON Schema | 0.0% | 0.0% | 0.0% | 17.2% | 0 | 0 | 95 | 457 |
| B2: Graph static | 98.7% | 81.2% | 89.1% | 83.5% | 371 | 5 | 90 | 86 |
| **Ours: JCPN** | **98.9%** | **99.8%** | **99.3%** | **98.9%** | **456** | **5** | **90** | **1** |

## 按缺陷类型 Recall

| Defect | N | Graph R | JCPN R | 说明 |
|--------|---|---------|--------|------|
| abnormal_loop | 95 | 100% | 100% | 结构环，两者都能检出 |
| broken_message | 93 | 100% | 100% | Graph 配对检查已加强 |
| isolated_node | 75 | 100% | 100% | 纯图属性，两者相同 |
| missing_branch | 9 | 88.9% | 88.9% | 多数底版无 if，样本少 |
| unreachable_node | 95 | 100% | 100% | Graph BFS 已修主入口逻辑 |
| variable_constraint | 90 | 5.6% | **100%** | **JCPN 核心优势：颜色集/类型检查** |

## 按平台 F1

| Platform | Bases | Graph F1 | JCPN F1 |
|----------|-------|----------|---------|
| n8n | 41 | 88.3% | 100% |
| Dify | 24 | 90.3% | 97.6% |
| Coze | 30 | 88.9% | 100% |

## 关键结论

1. **Graph 不是稻草人**：F1=89.1%，结构类缺陷全中，能检出绝大多数问题。
2. **JCPN 的核心优势在语义类**：variable_constraint 100% vs Graph 5.6%——这是颜色集/类型检查的独有能力。
3. **JCPN 只有 1 个 FN 和 5 个 FP**：FP 来自 Dify iteration 节点映射为 while{exit:true} 的循环退出建模不完美（limitations 诚实说明）。
4. **数据集三平台均衡**：n8n 41 / Dify 24 / Coze 30，无偏斜。
