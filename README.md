# VeriFlow — 自然语言 → 形式化验证 → 修复的工作流原型

VeriFlow 从自然语言描述出发，自动生成标准化 JSON 工作流，构建 JCPN（JSON-based Colored Petri Net）模型，
运行可达图形式化验证与缺陷定位，生成修复建议并在用户确认后应用，最终交付可验证的正确工作流。

- 在线演示：https://veriflow-jqel.onrender.com

## 快速启动

```powershell
cd veriflow
python -m pip install flask   # 首次
python app.py
```

浏览器打开 http://127.0.0.1:5000 （默认中文界面，顶部可切 EN）。

试用输入示例：
- 学生请假审批流程，三天以内辅导员审批，超过三天学院审批，通过后通知学生并登记
- 订单来了先校验库存，够就发货，不够通知补货，最后都通知客户
- 每天早上拉取业务数据，生成报表，推送日报

## 闭环流程（右侧 10 阶段管道）

需求录入 → 需求解析 → 需求澄清（必要时询问）→ 需求确认 →
流程规划 → JSON 中间表示 → JCPN 建模 → 形式化验证 →
缺陷修复（用户确认后应用）→ 输出工作流

## API

| 端点 | 说明 |
|---|---|
| `GET /` | 前端页面（webui/） |
| `POST /api/generate` | `{text}` → 管道执行；歧义时返回 `awaiting_clarification` + 澄清问题 |
| `POST /api/clarify` | `{text, answers}` → 合并澄清后重新生成 |
| `POST /api/confirm` | `{accepted: [repair_id]}` → 应用修复并重验证 |
| `POST /api/export` | 导出最终 JSON |
| `GET /api/health` | 健康检查 |
| `GET /api/samples` | 真实平台样本逐样本检测（顶栏"样本与检测过程"按钮加载） |

## 目录结构

```
veriflow/
├── app.py                  Flask 后端（阶段状态机 + REST）
├── nl2json.py              自然语言 → 标准化 JSON（模板库 + 规则引擎，可选 LLM）
├── preprocess.py           语法规范化（只报错不修复语义缺陷）
├── jcpn_builder.py         JCPN 建模（显式 provenance 映射 μ）
├── verification.py         可达图验证（不可达 / 死锁 / SCC 非终止 / 消息断裂）
├── repair.py               修复建议 + 应用 + 重验证闭环
├── adapters.py             平台适配器（n8n / Dify / Coze）
├── graph_static_checker.py 图结构基线 + JSON Schema 基线
├── defect_injector.py      缺陷注入器（受控负样本）
├── run_balanced_experiment.py / run_final_eval.py   实验入口
├── real_samples/           真实平台工作流样本（n8n / Dify / Coze 三平台公开导出）
├── webui/                  双语前端（index.html / app.js / styles.css）
└── experiment_results.json 主实验输出（95 底版 × 552 评测用例）
```

## 实验数据（2026-10 平衡版）

- **数据集**：95 个干净底版（n8n 41 / Dify 24 / Coze 30）+ 457 个受控注入缺陷样本 = **552 个评测用例**
  （每底版最多注入 6 类缺陷，注入失败的跳过，共跳过 113 次）
- **缺陷分布**：abnormal_loop 95 / unreachable_node 95 / broken_message 93 / variable_constraint 90 / isolated_node 75 / missing_branch 9
- **方法对比（552 用例）**

| Method | Precision | Recall | F1 | Accuracy | TP | FP | TN | FN |
|---|---|---|---|---|---|---|---|---|
| JSON Schema | — | — | — | 17.2% | 0 | 0 | 95 | 457 |
| Graph static checker | 98.7% | 81.2% | 89.1% | 83.5% | 371 | 5 | 90 | 86 |
| **Proposed JCPN** | **98.9%** | **99.8%** | **99.3%** | **98.9%** | **456** | **5** | **90** | **1** |

- 可达图验证：98 节点规模平均 **小于 8 ms**（localization 与 scalability 详见实验报告）

- **样本目录 `real_samples/`**：包含全部真实样本——n8n 41、Dify 24、Coze 162（完整采集池；评测按 seed=42 抽取其中 30 个为底版）。来源与许可见 `real_samples/SOURCES.md`，注入方式见 `defect_injector.py`。
- 样本逐条检测见网页"样本与检测过程"按钮（/api/samples）

## 已知局限

- variable_constraint（数据域不一致）不自动修复，需人工复核（对应"不修复语义缺陷"边界）。
- 模板库内置 8 个高频场景；未命中时走通用步骤解析，复杂嵌套结构建议提供更完整的描述。
- 会话状态存内存（单用户演示），生产需换持久化。
