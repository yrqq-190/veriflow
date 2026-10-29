# Real workflow samples — provenance

本目录是 VeriFlow 评估所用的**真实平台工作流样本**（非合成），对应论文
Table 3 / Table 6 的受控注入评测（2026-10 平衡版，95 底版 / 552 用例）。

## 评测数据集（论文口径）

- **95 个干净底版**：n8n 41 / Dify 24 / Coze 30（seed=42 抽样；Coze 从 162 个采集池中抽 30）。
- **457 个受控注入缺陷样本**：每底版最多注入 6 类缺陷，注入失败跳过（共跳过 113 次）。
- **合计 552 个评测用例**：95 干净 + 457 注入。
- 权威结果见 `../experiment_results.json`，报告见 `../balanced_experiment_report.md`。

## 目录构成

- `n8n_*.json`（41）：n8n 平台导出，论文 n8n 底版。
- `difyaws_*.yml`（21）+ `dify_*.yml`（3）= **24 个 Dify 底版**（`.yml` 入选）；
  目录另含 `dify_diarization.yaml`（`.yaml` 扩展名，未纳入平衡实验，仅作采集留存）。
- `coze_*.json`（162）：Coze 平台**完整采集池**（3–30 节点、JCPN 验证干净的底版）；评测按 seed=42
  抽取其中 30 个，其余保留供复现抽样与审计。

## 来源

### n8n（41 个）
- n8n 官方 starter-kit / E2E 模板、官方 langfuse 并行分组 demo、loomcycle 社区示例；
  覆盖 AI Agent、条件分支、消息通知、循环、并行 fan-out。

### Dify（24 个，`dify_*.yml` / `difyaws_*.yml`）
- `difyaws_*.yml`（21 个）：来自 GitHub 仓库
  [`aws-samples/dify-aws-tool`](https://github.com/aws-samples/dify-aws-tool) 的 `workflow/` 目录，
  许可证 **MIT-0（MIT No Attribution）**。覆盖 RAG、LLM Agent、翻译、代码解释、
  图像/视频生成、MCP、SageMaker rerank、营销文案等。
- 其余 3 个来自公开社区仓库 / 官方示例（webrag、sentiment-analysis、小红书运营流水线等）。

### Coze（162 个采集池，`coze_*.json`）
- 来自 GitHub 公开仓库 [`Hammer1/cozeworkflows`](https://github.com/Hammer1/cozeworkflows)
  的「工作流200+合集分享」，共 191 个 Coze 官方导出 zip（外层 zip 内嵌二进制容器，
  容器内为明文工作流 JSON，由 `coze_probe/extract_coze.py` 提取）。
- 节点类型为字符串数字编码：`1`开始 `2`结束 `3`LLM `4`插件 `5`代码 `8`选择器(if)
  `13`输出(send_only) `15`文本 `16`图像 `21`循环 `23`画板 `28`批处理 `31`便签(跳过)
  `32`变量聚合 `45`HTTP；分支由边 `sourcePortID` 的 `true`/`false` 表达，循环出口端口为 `loop-output`。
- 从 191 个中筛出 162 个 3–30 节点且 JCPN 验证干净的底版入库；其中 30 个（seed=42）入选评测基准。
- 许可：社区分享集合（个人整理），样本仅用于学术评测，工作流版权归原作者所有。

## 缺陷注入（负样本）

在标准化 JSON 层注入论文 6 类缺陷，**保持 JSON 语法有效**（仅破坏控制流 / 消息 / 数据语义）：

| Defect | 注入方式 |
| --- | --- |
| abnormal_loop | 引入无条件回边，形成非终止风险（potential non-termination） |
| unreachable_node | 删除某节点全部入边，使其不可达 |
| broken_message | 删除 send→receive 配对边之一 |
| variable_constraint | 改写相邻任务的 output_type / input_type 声明，制造数据颜色冲突 |
| isolated_node | 删除某节点全部边，使其孤立 |
| missing_branch | 删除 if 的一条 false 分支边 |

注入器见 `../defect_injector.py`；检测规则见 `../verification.py` 与 `../graph_static_checker.py`。
样本文件中的第三方凭据（如有）已作脱敏处理，仅保留结构与配置形态。
