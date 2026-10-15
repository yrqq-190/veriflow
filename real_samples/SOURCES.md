# Real workflow samples — provenance

本目录是 VeriFlow 评估所用的**真实平台工作流样本**（非合成），用于论文 Table 3 受控注入评测。

## 规模

- 共 **36 个**真实导出的工作流：n8n × 11、Dify × 25（含 DSL `.yml` / `.yaml`）。
- 评测选取其中 **25 个**通过 JCPN 验证的干净底版（3–30 节点），每版保留 1 个干净版本并受控注入 1 个缺陷，构成 **50 个评测样本**。
- 数据集构成与实跑指标见 `../table3_report.md`（脚本 `../eval_table3.py`）。

## 来源

### n8n（11 个，`n8n_*.json`）
- n8n 官方 starter-kit / E2E 模板、官方 langfuse 并行分组 demo、loomcycle 社区示例。
- 覆盖：AI Agent、条件分支、消息通知、循环、并行 fan-out。

### Dify（25 个，`dify_*.yml` / `dify_*.yaml`）
- **`difyaws_*.yml`（21 个）**：来自 GitHub 仓库
  [`aws-samples/dify-aws-tool`](https://github.com/aws-samples/dify-aws-tool) 的 `workflow/` 目录，
  许可证 **MIT-0（MIT No Attribution）**。覆盖 RAG、LLM Agent、翻译、代码解释、
  图像/视频生成、MCP、SageMaker rerank、营销文案等。
- 其余 4 个来自公开社区仓库 / 官方示例（webrag、diarization、sentiment-analysis、小红书运营流水线）。

### Coze
- 工作流导出为付费套餐功能，公开渠道无 DSL 样例，本轮未纳入；适配器 `parse_coze` 已按平台规范实现，待真实数据验证。

## 缺陷注入（负样本）

在标准化 JSON 层注入论文 5 类缺陷，**保持 JSON 语法有效**（仅破坏控制流 / 消息 / 数据语义）：

| Defect | 注入方式 |
| --- | --- |
| missing_branch | 删除 if 的 false 分支边与 else 声明 |
| isolated_node | 断开中间任务的入边与出边 |
| abnormal_loop | 插入 `while{exit:false}`；SCC 无出口环 |
| broken_message | 插入/改写发送后无配对接收的 n8n 消息节点 |
| variable_constraint | 在相邻任务上注入冲突的数据颜色（integer→string） |

注入器见 `../defect_injector.py`。

> 采集时间：2026-10。本目录的 4 个 `save_*.py` 为早期样本采集脚本，保留以备复现。
