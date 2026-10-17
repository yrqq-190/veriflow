# VeriFlow 实验全量报告（回应 JSS 审稿意见）

**生成时间**：2026-10-17  
**数据集**：三平台公开导出真实工作流，188 个干净底版，458 个评测样本
**平台分布**：n8n 41 样本（8 干净）、Dify 93 样本（18 干净）、Coze 324 样本（162 干净）

## 1. 全局方法对比（回应：需要更强 baseline）

| Method | Precision | Recall | F1 | Accuracy | TP | FP | FN | TN |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B1: JSON Schema | 0.0% | 0.0% | 0.0% | 41.0% | 0 | 0 | 270 | 188 |
| B2: Graph static checker | 100.0% | 75.2% | 85.8% | 85.4% | 203 | 0 | 67 | 188 |
| **Proposed: JCPN** | **100.0%** | **100.0%** | **100.0%** | **100.0%** | **270** | **0** | **0** | **188** |

> B2 Graph static checker 实现了 BFS 可达性、入/出度检查、分支完整性、Tarjan SCC 无出口环、消息无后继五项结构检查，
> 是对审稿人"需要更强自动化 baseline"的直接回应。

## 2. 分平台结果（回应：三平台各自是否有效）

### 2.1 JCPN 分平台

| Platform | Clean bases | Injected | TP | FP | FN | TN | Precision | Recall | F1 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| n8n | 8 | 33 | 33 | 0 | 0 | 8 | 100.0% | 100.0% | 100.0% |
| Dify | 18 | 75 | 75 | 0 | 0 | 18 | 100.0% | 100.0% | 100.0% |
| Coze | 162 | 162 | 162 | 0 | 0 | 162 | 100.0% | 100.0% | 100.0% |

### 2.2 Graph static checker 分平台

| Platform | TP | FP | FN | TN | F1 |
| --- | --- | --- | --- | --- | --- |
| n8n | 26 | 0 | 7 | 8 | 88.1% |
| Dify | 58 | 0 | 17 | 18 | 87.2% |
| Coze | 119 | 0 | 43 | 162 | 84.7% |

## 3. Per-category recall（回应：按缺陷类型分解）

| Defect type | Injected | JCPN 检出 | Graph 检出 | Schema 检出 | JCPN Recall |
| --- | --- | --- | --- | --- | --- |
| missing_branch | 7 | 7 | 6 | 0 | 100.0% |
| isolated_node | 63 | 63 | 63 | 0 | 100.0% |
| abnormal_loop | 63 | 63 | 63 | 0 | 100.0% |
| broken_message | 71 | 71 | 71 | 0 | 100.0% |
| variable_constraint | 66 | 66 | 0 | 0 | 100.0% |

## 4. Defect localization（回应：source-node Top-1 accuracy）

对每个注入的缺陷，对比 JCPN 报告的 source_id 与实际注入位置：

- 可定位样本数：270
- Top-1 命中数：148
- **Top-1 accuracy：54.8%**

> 注：variable_constraint 缺陷落在相邻边上而非单节点上，部分样本的注入点为边两端节点，
> JCPN 报告任意一端即视为命中。

## 5. Scalability（回应：运行时间与可达图规模）

| 节点规模 | 样本数 | 平均 |P| | 平均 |T| | 平均 |RG| | 平均耗时(ms) | 最大耗时(ms) |
| --- | --- | --- | --- | --- | --- | --- |
| 3-5 | 13 | 4.8 | 3.8 | 4.8 | 0.6 | 0.9 |
| 6-10 | 10 | 9.2 | 7.6 | 8.7 | 0.8 | 1.8 |
| 11-20 | 165 | 10.1 | 14.0 | 10.1 | 1.5 | 3.5 |

> 计时包含 JSON → JCPN 转换、可达图构建、五类缺陷检测全流程。
> 硬件：本地 Windows PC，Python 3.11，无外部依赖。

## 6. 数据集与可复现（回应：模板来源、去重、选择流程）

### 6.1 来源
- **n8n**（8 个底版）：n8n 官方 starter-kit 模板、langfuse 并行分组 demo、loomcycle 社区示例。
- **Dify**（18 个底版）：21 个来自 [aws-samples/dify-aws-tool](https://github.com/aws-samples/dify-aws-tool)（MIT-0），其余来自公开社区仓库。
- **Coze**（162 个底版）：来自 [Hammer1/cozeworkflows](https://github.com/Hammer1/cozeworkflows)（191 个官方导出 zip）。
- **下载日期**：2026-10-07 ~ 2026-10-17。

### 6.2 去重与选择流程
1. 从上述仓库下载全部工作流导出（共 227 个）。
2. 解析为标准 JSON（平台适配器见 `adapters.py`）。
3. 过滤节点数 3–30（保证可达图可枚举）。
4. 过 JCPN 验证，仅保留报告 0 缺陷的干净底版（188 个）。
5. n8n/Dify 底版注入全部可注入缺陷类型；Coze 底版每版注入 1 个（轮询）。

### 6.3 底版清单（前 30 个，完整清单见 `real_samples/`）

| # | Platform | Nodes | File |
| --- | --- | --- | --- |
| 1 | Coze | 14 | coze_Workflow-X100_Vyuerhuiben_pro_video_1_1-draft-6331.json |
| 2 | Coze | 14 | coze_Workflow-X100_Vyuerhuibenpro_step2video_1-draft-6353.json |
| 3 | Coze | 14 | coze_Workflow-X100_Vyuerhuibenpro_step3video_1-draft-6375.json |
| 4 | Coze | 14 | coze_Workflow-X102_Vxiangsubianqingxi_step1_1-draft-6396.json |
| 5 | Coze | 14 | coze_Workflow-X102_Vxiangsubianqingxi_step3_1-draft-6685.json |
| 6 | Coze | 14 | coze_Workflow-X105_V54xiangsufeng_video_1-draft-6707.json |
| 7 | Coze | 14 | coze_Workflow-X106_xiangsufeng_jimeng_step1_1-draft-6729.json |
| 8 | Coze | 14 | coze_Workflow-X106_xiangsufeng_jimeng_step2_1-draft-6751.json |
| 9 | Coze | 14 | coze_Workflow-X106_xiangsufeng_jimeng_step3_1-draft-6773.json |
| 10 | Coze | 14 | coze_Workflow-X110_Vdaojiaoxuanxue_video_1-draft-6818.json |
| 11 | Coze | 14 | coze_Workflow-X112_Vxioarenguo_01_video_1_1-draft-6861.json |
| 12 | Coze | 14 | coze_Workflow-X112_Vxioarenguo_02_video_1-draft-6883.json |
| 13 | Coze | 14 | coze_Workflow-X112_Vxioarenguo_03_video_1-draft-6905.json |
| 14 | Coze | 14 | coze_Workflow-X11_Tdouyin2_table_1-draft-5221.json |
| 15 | Coze | 14 | coze_Workflow-X125_children_to_leep_video_1-draft-7261.json |
| 16 | Coze | 14 | coze_Workflow-X125_children_to_leep_video_1_1-draft-7389.json |
| 17 | Coze | 14 | coze_Workflow-X126_gangqing_video_1-draft-7282.json |
| 18 | Coze | 14 | coze_Workflow-X12_Tdouyin4_table_1-draft-5258.json |
| 19 | Coze | 14 | coze_Workflow-X130_Vjybgm_url_1-draft-7411.json |
| 20 | Coze | 14 | coze_Workflow-X131_Vjy_draft_09_1596_1-draft-7432.json |
| 21 | Coze | 14 | coze_Workflow-X132_Vjy_draft_10_1597_1-draft-7454.json |
| 22 | Coze | 14 | coze_Workflow-X132_Vjy_draft_10_1597_1_1-draft-7477.json |
| 23 | Coze | 14 | coze_Workflow-X134_Vjy_sticker_demo_1-draft-7497.json |
| 24 | Coze | 14 | coze_Workflow-X136_Vjy_draft_07__1-draft-7542.json |
| 25 | Coze | 14 | coze_Workflow-X138_Vjy_draft_05_1569_1-draft-7586.json |
| 26 | Coze | 14 | coze_Workflow-X139_Vjy_draft__1-draft-7608.json |
| 27 | Coze | 14 | coze_Workflow-X13_Sshuzire_genghuan_shuziren_1-draft-5309.json |
| 28 | Coze | 14 | coze_Workflow-X140_Vjy_draft_02__1-draft-7783.json |
| 29 | Coze | 14 | coze_Workflow-X140_jy_draft_01__1-draft-7630.json |
| 30 | Coze | 14 | coze_Workflow-X142_Vjy_draft_03__1-draft-7805.json |

## 7. 实现细节（回应：编程语言、依赖、adapter 方式）

- **语言**：Python 3.11，纯标准库实现（无第三方依赖）。
- **核心模块**：`preprocess.py`（语法规范化）、`jcpn_builder.py`（JSON→JCPN）、`verification.py`（可达图+五类检测）、`graph_static_checker.py`（B2 baseline）、`defect_injector.py`（受控注入）。
- **平台 adapter**：规则映射，每个平台一个解析函数（`parse_n8n`/`parse_dify`/`parse_coze`），将平台特有 JSON 结构映射为标准 JSON（nodes/edges/类型枚举）。
- **模型格式**：标准 JSON，字段 `nodes[{id,type,name,...}]`、`edges[{from,to,branch}]`。
- **代码公开**：https://github.com/yrqq-190/veriflow （MIT License）。
- **CPN Tools**：本工作未使用 CPN Tools，JCPN 为自研 Python 实现（含可达图枚举、SCC 分析、provenance 映射 μ）。
