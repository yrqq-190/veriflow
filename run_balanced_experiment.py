# -*- coding: utf-8 -*-
"""全量真实数据实验：从 real_samples 读底版 -> 注入缺陷 -> 三方法对比。"""
import os, sys, io, json, time, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from adapters import parse_dify, parse_coze, parse_n8n
from preprocess import preprocess
from verification import verify_workflow
from graph_static_checker import graph_based_static_checker, json_schema_checker
from defect_injector import INJECTORS

random.seed(42)
BASE = os.path.dirname(os.path.abspath(__file__))
REAL = os.path.join(BASE, "real_samples")

# ---- 1. 读取并解析所有底版（与 precompute 相同的平衡逻辑）----
all_files = sorted(os.listdir(REAL))
coze_files = [f for f in all_files if f.startswith("coze_") and f.endswith(".json")]
other_files = [f for f in all_files if f.endswith((".json", ".yml")) and not f.startswith(("save_", "coze_"))]
random.shuffle(coze_files)
coze_files = coze_files[:30]
selected_files = other_files + coze_files

bases = []  # [(platform, name, cleaned_wf, raw_wf)]
parse_fail = 0
for fn in selected_files:
    path = os.path.join(REAL, fn)
    try:
        if fn.startswith("coze_"):
            std = parse_coze(json.load(open(path, encoding="utf-8")), fn)
        elif fn.endswith(".yml") or fn.startswith("dify"):
            std = parse_dify(open(path, encoding="utf-8").read(), fn)
        else:
            std = parse_n8n(json.load(open(path, encoding="utf-8")), fn)
        pp = preprocess(std)
        bases.append((std.get("platform", "?"), fn, pp["workflow"], std))
    except Exception as e:
        parse_fail += 1

print(f"底版解析成功: {len(bases)}, 失败: {parse_fail}")

# 按平台统计
from collections import Counter
plat_counts = Counter(b[0] for b in bases)
print(f"平台分布: {dict(plat_counts)}")

# ---- 2. 对每个底版跑三种方法（干净样本）----
def jcpn_check(wf):
    return verify_workflow(wf)["defective"]

def graph_check(wf):
    return graph_based_static_checker(wf)

def schema_check(wf):
    return json_schema_checker(wf)

# ---- 3. 注入缺陷并评测 ----
# 每个底版对每种注入器尝试一次（如果失败则跳过）
results = {
    "jcpn": {"tp": 0, "fp": 0, "tn": 0, "fn": 0},
    "graph": {"tp": 0, "fp": 0, "tn": 0, "fn": 0},
    "schema": {"tp": 0, "fp": 0, "tn": 0, "fn": 0},
}
by_defect = {}  # defect_type -> {method: {tp, fp, tn, fn}}
by_platform = {}  # platform -> {method: {tp, fp, tn, fn}}

def update(metric, method, actual_defective, predicted_defective):
    m = results[method]
    if actual_defective and predicted_defective:
        m["tp"] += 1
    elif actual_defective and not predicted_defective:
        m["fn"] += 1
    elif not actual_defective and predicted_defective:
        m["fp"] += 1
    else:
        m["tn"] += 1

def update_dict(d, method, actual_defective, predicted_defective):
    if method not in d:
        d[method] = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    dd = d[method]
    if actual_defective and predicted_defective:
        dd["tp"] += 1
    elif actual_defective and not predicted_defective:
        dd["fn"] += 1
    elif not actual_defective and predicted_defective:
        dd["fp"] += 1
    else:
        dd["tn"] += 1

# 干净样本
for plat, fn, wf, raw in bases:
    j = jcpn_check(wf)
    g = graph_check(wf)
    s = schema_check(wf)
    update("all", "jcpn", False, j)
    update("all", "graph", False, g)
    update("all", "schema", False, s)
    if plat not in by_platform:
        by_platform[plat] = {}
    update_dict(by_platform[plat], "jcpn", False, j)
    update_dict(by_platform[plat], "graph", False, g)
    update_dict(by_platform[plat], "schema", False, s)

# 注入缺陷
inject_skip = 0
for plat, fn, wf, raw in bases:
    for defect_name, inj_fn in INJECTORS.items():
        try:
            wf2, injected_id = inj_fn(json.loads(json.dumps(wf)))
        except Exception:
            inject_skip += 1
            continue
        if wf2 is None:
            inject_skip += 1
            continue
        # 注入后的工作流直接传给检测器，不再 preprocess（会丢失注入标记）
        wf2_cleaned = wf2
        j = jcpn_check(wf2_cleaned)
        g = graph_check(wf2_cleaned)
        s = schema_check(wf2_cleaned)
        update("all", "jcpn", True, j)
        update("all", "graph", True, g)
        update("all", "schema", True, s)
        if defect_name not in by_defect:
            by_defect[defect_name] = {}
        update_dict(by_defect[defect_name], "jcpn", True, j)
        update_dict(by_defect[defect_name], "graph", True, g)
        update_dict(by_defect[defect_name], "schema", True, s)
        if plat not in by_platform:
            by_platform[plat] = {}
        update_dict(by_platform[plat], "jcpn", True, j)
        update_dict(by_platform[plat], "graph", True, g)
        update_dict(by_platform[plat], "schema", True, s)

# ---- 4. 计算指标 ----
def metrics(r):
    tp, fp, tn, fn = r["tp"], r["fp"], r["tn"], r["fn"]
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0
    acc = (tp + tn) / (tp + fp + tn + fn) if (tp + fp + tn + fn) > 0 else 0
    return {"precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4), "accuracy": round(acc, 4),
            "tp": tp, "fp": fp, "tn": tn, "fn": fn}

print("\n=== 全局结果 ===")
for method in ["schema", "graph", "jcpn"]:
    m = metrics(results[method])
    print(f"  {method:8s}: P={m['precision']:.3f} R={m['recall']:.3f} F1={m['f1']:.3f} Acc={m['accuracy']:.3f} (TP={m['tp']} FP={m['fp']} TN={m['tn']} FN={m['fn']})")

print(f"\n注入跳过: {inject_skip}")
print(f"\n=== 按缺陷类型 ===")
for defect in sorted(by_defect.keys()):
    print(f"\n  [{defect}]")
    for method in ["schema", "graph", "jcpn"]:
        if method in by_defect[defect]:
            m = metrics(by_defect[defect][method])
            print(f"    {method:8s}: R={m['recall']:.3f} (TP={m['tp']} FN={m['fn']})")

print(f"\n=== 按平台 ===")
for plat in sorted(by_platform.keys()):
    print(f"\n  [{plat}]")
    for method in ["schema", "graph", "jcpn"]:
        if method in by_platform[plat]:
            m = metrics(by_platform[plat][method])
            print(f"    {method:8s}: P={m['precision']:.3f} R={m['recall']:.3f} F1={m['f1']:.3f} (TP={m['tp']} FP={m['fp']} TN={m['tn']} FN={m['fn']})")

# ---- 5. 保存结果 ----
out = {
    "n_bases": len(bases),
    "platform_distribution": dict(plat_counts),
    "inject_skip": inject_skip,
    "global": {m: metrics(results[m]) for m in ["schema", "graph", "jcpn"]},
    "by_defect": {d: {m: metrics(by_defect[d][m]) for m in by_defect[d]} for d in by_defect},
    "by_platform": {p: {m: metrics(by_platform[p][m]) for m in by_platform[p]} for p in by_platform},
}
with open(os.path.join(BASE, "experiment_results.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(f"\n[written] experiment_results.json")
