# VeriFlow 真实平台数据评估报告（论文 Table 3 复现）

> 数据集：n8n / Dify 公开导出的**真实生产模板**。选取 25 个 JCPN 验证干净的底版，
> 每个底版保留 1 个干净版本并受控注入 1 个缺陷，共 **50 个评测样本**。
> 底版节点数 3–30，平台分布 n8n×8、Dify×17。
> 所有数值为本次实跑结果，不沿用论文原报告数据。

## 1. 方法对比（Table 3）

| Method | Precision | Recall | F1 score | Accuracy |
| --- | --- | --- | --- | --- |
| B1: JSON Schema validation | 0.0% | 0.0% | 0.0% | 50.0% |
| B2: Graph-based static checker | 100.0% | 60.0% | 75.0% | 80.0% |
| **Proposed: JCPN verification** | **100.0%** | **100.0%** | **100.0%** | **100.0%** |

## 2. JCPN 混淆矩阵

| | Actually defective | Actually non-defective |
| --- | --- | --- |
| Detected as defective | 25 (TP) | 0 (FP) |
| Detected as non-defective | 0 (FN) | 25 (TN) |

## 3. 各缺陷类型检出数（每类注入 5 个）

| Defect type | Injected | JCPN | Graph | Schema |
| --- | --- | --- | --- | --- |
| missing_branch | 5 | 5 | 5 | 0 |
| isolated_node | 5 | 5 | 5 | 0 |
| abnormal_loop | 5 | 5 | 5 | 0 |
| broken_message | 5 | 5 | 0 | 0 |
| variable_constraint | 5 | 5 | 0 | 0 |

## 4. 误报 / 漏报明细

- JCPN 误报 FP=0：无
- JCPN 漏报 FN=0：无
- Graph 漏报 FN=10：difyaws_andrew_translation_agent#variable_constraint；n8n_daily_report#variable_constraint；difyaws_term_based_translation_workflow#variable_constraint；n8n_multi_agent_research#variable_constraint；n8n_web_app_preview#variable_constraint；dify_diarization#broken_message；difyaws_ASR_Transcribe#broken_message；difyaws_Sagemaker-Bge-Rerank#broken_message；difyaws_mcp_server_integration#broken_message；difyaws_svg_designer#broken_message

## 5. 底版清单（25 个）

| # | Platform | Nodes | File | Injected defect |
| --- | --- | --- | --- | --- |
| 1 | Dify | 3 | dify_diarization.yaml | broken_message |
| 2 | Dify | 3 | difyaws_ASR_Transcribe.yml | broken_message |
| 3 | Dify | 3 | difyaws_Sagemaker-Bge-Rerank.yml | broken_message |
| 4 | Dify | 3 | difyaws_mcp_server_integration.yml | broken_message |
| 5 | Dify | 3 | difyaws_svg_designer.yml | broken_message |
| 6 | Dify | 5 | difyaws_andrew_translation_agent.yml | variable_constraint |
| 7 | Dify | 5 | difyaws_term_based_translation_workflow.yml | variable_constraint |
| 8 | Dify | 6 | dify_sentiment.yml | missing_branch |
| 9 | Dify | 6 | difyaws_sagemaker_rerank_workflow.yml | isolated_node |
| 10 | Dify | 7 | difyaws_s3_rag.yml | isolated_node |
| 11 | Dify | 8 | dify_xiaohongshu_full.yml | isolated_node |
| 12 | Dify | 8 | difyaws_AgentCore-Memory-2.yml | isolated_node |
| 13 | Dify | 8 | difyaws_rag_based_bot_with_tts.yml | abnormal_loop |
| 14 | Dify | 9 | difyaws_edu_question_gen.yml | missing_branch |
| 15 | Dify | 9 | difyaws_rag_based_chatbot_for_nextcloud.yml | missing_branch |
| 16 | Dify | 13 | difyaws_generate_image_video.yml | abnormal_loop |
| 17 | Dify | 15 | difyaws_chat-with-browser.yml | abnormal_loop |
| 18 | n8n | 3 | n8n_loomcycle_tool.json | abnormal_loop |
| 19 | n8n | 3 | n8n_slack_loop.json | abnormal_loop |
| 20 | n8n | 5 | n8n_daily_report.json | variable_constraint |
| 21 | n8n | 5 | n8n_multi_agent_research.json | variable_constraint |
| 22 | n8n | 5 | n8n_web_app_preview.json | variable_constraint |
| 23 | n8n | 6 | n8n_clone_build_download.json | isolated_node |
| 24 | n8n | 9 | n8n_lead_followup.json | missing_branch |
| 25 | n8n | 12 | n8n_ai_agent_tool.json | missing_branch |

## 6. 真实模板上的候选缺陷（未经注入）

对全部真实样本（含未选入基准集的模板）直接运行 JCPN，下列公开模板被报告
存在候选缺陷，未注入、未人工修复，可作为真实（非受控）证据；个别复杂模板
（含 iteration 迭代节点）的报告需人工核验是否为建模误报。

| Template | Nodes | 报告缺陷（类型×数量） |
| --- | --- | --- |
| dify_webrag.yml | 10 | unreachable_node×3 |
| difyaws_AgentCore-Memory-1.yml | 13 | unreachable_node×2 |
| difyaws_apply_guardrails.yml | 10 | unexpected_deadlock×1 |
| difyaws_claude3_code_translation.yml | 8 | unreachable_node×1 |
| difyaws_eks_upgrade_planning.yml | 38 | unexpected_deadlock×7 |

## 7. 方法说明与边界

- **B1 JSON Schema**：仅校验必填字段、类型枚举、ID 唯一、边引用完整；受控注入保持 JSON 语法有效，故对五类行为缺陷 Recall 为 0，证明语法/Schema 校验不是行为验证。
- **B2 Graph static checker**：实现 BFS 可达性、入/出度、分支完整性、Tarjan SCC 无出口环、消息无后继五项结构检查；可检出孤立节点、缺分支、无出口循环三类纯结构缺陷，但无法识别消息配对语义（broken_message）与数据颜色约束（variable_constraint）。
- **JCPN**：在可达图与 provenance 回溯基础上，额外建模消息配对（n8n unpaired）与 Θ_data 数据颜色一致性，因此五类缺陷均可检出。
- variable_constraint 当前为轻量类型检查：仅在节点显式声明 input_type/output_type 时校验相邻边颜色一致，不建模完整数据域传播与变量作用域，属后续工作。
- 表中 100% 为受控注入（每类缺陷均在检测能力内）下的结果；真实模板上的复杂缺陷仍需人工复核，见 §6。
- Coze：工作流导出受付费套餐限制，公开渠道无 DSL 样例，本轮未纳入；适配器 parse_coze 已就绪。