# VeriFlow 真实平台数据评估报告

> 测试数据来源：n8n / Dify 公开导出的**真实生产模板**（GitHub 官方与社区仓库），
> 负样本在其上受控注入论文 5 类缺陷。**本报告数值为实测结果，不参照论文数据。**

## 1. 数据集构成

| 来源平台 | 正常样本 | 说明 |
| --- | --- | --- |
| n8n | 11 | 官方 starter-kit Demo、官方 E2E 模板、langfuse 并行分组 demo、loomcycle 社区示例（AI Agent / 条件分支 / 消息通知 / 循环 / 并行 fan-out） |
| Dify | 1 | 小红书运营流水线（start→llm→http→code→end，DSL YAML） |
| Coze | 0 | 工作流导出为付费 Zip 功能，公开渠道无可验证样例（适配器已就绪，待数据） |

负样本：48 个（在真实样本上注入，含 missing_branch / isolated_node /
unreachable_node / abnormal_loop / broken_message / variable_constraint 六类）。

## 2. 方法对比（实测）

| Method | Precision | Recall | F1 score | Accuracy |
| --- | --- | --- | --- | --- |
| JSON Schema | 91.3% | 43.8% | 59.2% | 51.7% |
| Graph static checker | 93.3% | 58.3% | 71.8% | 63.3% |
| Proposed JCPN method | 100.0% | 81.2% | 89.7% | 85.0% |

## 3. JCPN 混淆矩阵（实测）

| | Actually defective | Actually non-defective |
| --- | --- | --- |
| Detected as defective | 39 (TP) | 0 (FP) |
| Detected as non-defective | 9 (FN) | 12 (TN) |

## 4. 缺陷类型检出明细（JCPN / Graph / Schema 检出数）

| Defect type | 注入数 | JCPN | Graph | Schema |
| --- | --- | --- | --- | --- |
| abnormal_loop | 12 | 12 | 2 | 12 |
| broken_message | 3 | 3 | 2 | 1 |
| isolated_node | 10 | 10 | 10 | 2 |
| missing_branch | 2 | 2 | 2 | 2 |
| unreachable_node | 12 | 12 | 11 | 2 |
| variable_constraint | 9 | 0 | 1 | 2 |

## 5. 误报 / 漏报分析（实测）

- **JCPN 误报（FP=0）**：无
- **JCPN 漏报（FN=9）**：dify_xiaohongshu_full#variable_constraint、n8n_ai_agent_tool#variable_constraint、n8n_clone_build_download#variable_constraint、n8n_daily_report#variable_constraint、n8n_langfuse_demo#variable_constraint、n8n_lead_followup#variable_constraint、n8n_loomcycle_tool#variable_constraint、n8n_multi_agent_research#variable_constraint、n8n_web_app_preview#variable_constraint
- **图检查器误报（FP=2）**：n8n_daily_report、n8n_slack_loop

## 6. 适配器可信度与局限

- n8n：11 个真实模板全部适配并通过 JCPN 验证（无缺陷误报）；独立触发分支标记为备用入口，豁免不可达误报；非 main 端口的子模型/配置节点（如 ai_languageModel）自动排除，不误报孤立节点。
- Dify：DSL YAML 适配已验证；iteration 节点映射为 while{exit:true}（体内节点不嵌套，循环体语义未深建模）。
- Coze：导出受付费套餐限制，本轮无真实数据；适配器按平台规范实现（experimental）。
- variable_constraint：当前 Θ 抽象不建模数据域，真实注入样本预期无法检出（FN），与论文已知局限一致。

## 7. 结论（实测口径）

- JCPN 在真实平台数据上 F1 = 89.7%，优于图检查器 71.8% 与 Schema 59.2%。
- 消息适配器语义（send-only 放行、n8n unpaired 判 broken）在真实 n8n 样例上验证成立。
- 数据规模有限（真实模板公开可得性约束），如需更大规模可扩展抓取或补充 Coze 付费导出样本。

评估耗时（JCPN 全量）：0.046 s