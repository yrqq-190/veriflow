# VeriFlow — 自然语言 → 形式化验证 → 修复的工作流原型

从用户自然语言描述出发，自动生成标准化 JSON 工作流，构建 JCPN（JSON-based Colored Petri Net）模型，
运行可达图形式化验证，生成缺陷修复建议并在用户确认后应用，最后交付正确的工作流。

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
- 我自己也没想好，帮我生成一个海关一体化通关流程（命中内置场景模板，无大模型）

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
├── evaluation_real.py      真实平台数据评估（结果见 evaluation_report_real.md）
├── defect_injector.py      缺陷注入器（受控负样本）
├── real_samples/           12 个真实平台工作流（n8n×11、Dify×1，含官方/社区样例）
├── webui/                  双语前端（index.html / app.js / styles.css）
├── report_real.html        评估可视化页（ECharts）
└── evaluation_report_real.md  实测评估报告
```

## 真实数据评估结果（实测，不参照论文）

数据集：12 个真实平台样本（n8n×11、Dify×1，来源含 n8n 官方 demo、langfuse demo、
loomcycle 社区样例、beansmile Dify DSL）+ 48 个受控注入缺陷 = 60 用例。

| Method | Precision | Recall | F1 | Accuracy |
|---|---|---|---|---|
| JSON Schema | 91.3% | 43.8% | 59.2% | 51.7% |
| Graph static checker | 93.3% | 58.3% | 71.8% | 63.3% |
| **Proposed JCPN** | **100%** | **81.2%** | **89.7%** | **85.0%** |

- JCPN：TP=39 / FP=0 / FN=9 / TN=12，正常样本零误报；FN 全部为 variable_constraint
  （Θ 不建模数据域，已知局限，且该类缺陷按论文边界本就不自动修复）。
- Graph 弱于 Schema 的原因是循环出口（abnormal_loop）与消息配对（broken_message）需语义判断，
  纯结构检查系统性失效——这正是 JCPN 方法的价值点。
- 样本逐条检测见网页"样本与检测过程"按钮（/api/samples，12 个样本全通过，JCPN 零误报）。
- Coze 工作流导出为付费功能，公开渠道无可验证样例（适配器已实现，标 experimental，待真实数据）。

## 已知局限

- variable_constraint（数据域不一致）不自动修复，需人工复核（对应论文"不修复语义缺陷"边界）。
- 模板库内置 8 个高频场景（含海关一体化通关）；未命中时走通用步骤解析，复杂嵌套结构建议提供更完整的描述。
- 会话状态存内存（单用户演示），生产需换持久化。
