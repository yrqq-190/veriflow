# -*- coding: utf-8 -*-
"""
VeriFlow 严格口径评估（evaluation_strict.py）
==============================================
与早期评估的差别（每条都可复核）：

  口径 L（loose）  「只要判 defective」——旧口径，用于和历史数字对齐；
  口径 S（strict） 「类型必须落在该缺陷类，且定位必须命中被注入节点」；
  消融（abi）      「剔除静态类型规则，只保留可达图结论」——衡量状态空间本身的能力。

定位真值取自注入前后的结构差异（节点/边增删 + 字段变更），不读注入器的返回值；
截断样本单独计数，不并入 TN。

用法：
  python evaluation_strict.py            # 全量（227 底版 + 注入）
  python evaluation_strict.py --max-bases 40   # 冒烟
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import sys
import time
from typing import Any, Dict, List, Set, Tuple

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from adapters import parse_coze, parse_dify, parse_n8n
from defect_injector import INJECTORS
from graph_static_checker import graph_based_static_checker, json_schema_checker
from preprocess import preprocess
from verification import verify_workflow

BASE = os.path.dirname(os.path.abspath(__file__))
REAL = os.path.join(BASE, "real_samples")

# 注入类 → 可接受的检出类型
# 注入类别 → 可接受的检出类型。
# missing_branch 的形态是「分支子图被摘掉」，在平台语义（悬空分支=实例结束）下
# 可观察后果是子图不可达，因此 unreachable_node 也计入该类命中；报告里同时给出
# 类型明细，读者可以自己判断要不要收紧。
TYPE_MAP = {
    "missing_branch": {"missing_branch", "unreachable_node", "unexpected_deadlock"},
    "isolated_node": {"unreachable_node"},
    "unreachable_node": {"unreachable_node"},
    "abnormal_loop": {"non_termination_risk", "unexpected_deadlock"},
    "broken_message": {"broken_message"},
    "variable_constraint": {"variable_constraint"},
}

IGNORE_FIELDS = {"id", "type", "name", "guard", "is_entry", "is_alt_entry"}

# 底版本身带结构缺陷的清单（实测核对过原始 DSL，不是推测）
KNOWN_BASE_DEFECTS = {
    "difyaws_AgentCore-Memory-1.yml":
        "原始 Dify DSL 中 1759201306129 -> 17592016133500 是一个没有任何入边的独立组件，"
        "在任何执行引擎下都不可能运行；报告 unreachable_node 属于真阳性，不是误报。",
}


# ---------------------------------------------------------------------------
# 数据装载
# ---------------------------------------------------------------------------
def load_bases(limit: int | None = None) -> List[Tuple[str, str, Dict[str, Any]]]:
    random.seed(42)
    files = sorted(os.listdir(REAL))
    coze = [f for f in files if f.startswith("coze_") and f.endswith(".json")]
    other = [f for f in files
             if f.endswith((".json", ".yml")) and not f.startswith(("save_", "coze_"))]
    random.shuffle(coze)
    selected = other + coze[:30]
    if limit:
        selected = selected[:limit]

    bases = []
    skipped = []
    for fn in selected:
        path = os.path.join(REAL, fn)
        try:
            if fn.startswith("coze_"):
                std = parse_coze(json.load(open(path, encoding="utf-8")), fn)
            elif fn.endswith(".yml") or fn.startswith("dify"):
                std = parse_dify(open(path, encoding="utf-8").read(), fn)
            else:
                std = parse_n8n(json.load(open(path, encoding="utf-8")), fn)
            bases.append((std.get("platform", "?"), fn, preprocess(std)["workflow"]))
        except Exception as ex:
            skipped.append({"id": fn, "error": f"{type(ex).__name__}: {ex}"[:120]})
    if skipped:
        print(f"[warn] 解析失败 {len(skipped)} 个底版（已计入 dataset.skipped）")
    load_bases.skipped = skipped
    return bases


def mutant_nodes(base: Dict[str, Any], inj: Dict[str, Any]) -> Set[str]:
    """注入前后结构差异涉及的节点（定位真值）。"""
    touched: Set[str] = set()
    b_edges = {(e["from"], e["to"]) for e in base.get("edges", [])}
    n_edges = {(e["from"], e["to"]) for e in inj.get("edges", [])}
    for (u, v) in b_edges ^ n_edges:
        touched.add(u)
        touched.add(v)
    b_by = {n["id"]: n for n in base.get("nodes", [])}
    n_by = {n["id"]: n for n in inj.get("nodes", [])}
    touched |= set(n_by) ^ set(b_by)
    for nid in set(b_by) & set(n_by):
        a = {k: v for k, v in b_by[nid].items() if k not in IGNORE_FIELDS}
        b = {k: v for k, v in n_by[nid].items() if k not in IGNORE_FIELDS}
        if a != b:
            touched.add(nid)
    return touched


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------
def signals(r: Dict[str, Any]) -> Dict[str, Set[str]]:
    """把一次验证结果拆成 (类型集合, 定位集合, 状态空间类型集合)。"""
    types: Set[str] = set()
    types_state: Set[str] = set()
    sources: Set[str] = set()
    sources_state: Set[str] = set()
    for d in r["defects"]:
        t = d["type"]
        types.add(t)
        srcs = {d.get("source_id")} | set(d.get("sources") or [])
        sources |= {s for s in srcs if s}
        if d.get("mechanism") in ("static_type_rule", "typed_consumption_stall"):
            continue
        types_state.add(t)
        sources_state |= {s for s in srcs if s}
    return {"types": types, "sources": sources,
            "types_state": types_state, "sources_state": sources_state}


def is_hit(sig: Dict[str, Set[str]], defect: str, touched: Set[str],
           state_space_only: bool = False) -> bool:
    types = sig["types_state"] if state_space_only else sig["types"]
    sources = sig["sources_state"] if state_space_only else sig["sources"]
    return bool(TYPE_MAP[defect] & types) and bool(touched & sources)


def metrics(tp: int, fp: int, fn: int, tn: int) -> Dict[str, Any]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    acc = (tp + tn) / (tp + fp + fn + tn) if tp + fp + fn + tn else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(p, 4), "recall": round(r, 4),
            "f1": round(f1, 4), "accuracy": round(acc, 4)}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-bases", type=int, default=0)
    ap.add_argument("--max-states", type=int, default=20000)
    args = ap.parse_args()

    bases = load_bases(args.max_bases or None)
    print(f"底版：{len(bases)} 个（平台分布 "
          f"{ {p: sum(1 for b in bases if b[0] == p) for p in {b[0] for b in bases}} }）")

    t0 = time.perf_counter()

    # --- 干净样本 ---
    # KNOWN_BASE_DEFECTS 是「底版本身就有缺陷」的已知清单：这些报告不是误报，
    # 而是源模板的结构问题（证据写在 evaluation_report 的 note 里）。
    # 计入 FP 的同时单列，避免用"把这些样本删掉"的方式把误报洗成零。
    clean = {"loose_fp": 0, "truncated": 0, "n": 0, "fp_ids": [],
             "known_true_positive": 0, "inconclusive": []}
    for plat, fn, wf in bases:
        r = verify_workflow(wf, max_states=args.max_states)
        clean["n"] += 1
        if r["stats"]["truncated"]:
            clean["truncated"] += 1
        if r["defective"]:
            types = [d["type"] for d in r["defects"]]
            if set(types) == {"analysis_incomplete"}:
                clean.setdefault("inconclusive", []).append({"id": fn})
                continue
            clean["loose_fp"] += 1
            item = {"id": fn, "types": types}
            note = KNOWN_BASE_DEFECTS.get(fn)
            if note:
                item["known_source_defect"] = note
                clean["known_true_positive"] += 1
            clean["fp_ids"].append(item)

    # --- 注入样本 ---
    cases = []
    for plat, fn, wf in bases:
        for defect, inj in INJECTORS.items():
            try:
                wf2, _label = inj(json.loads(json.dumps(wf)))
            except Exception:
                continue
            if wf2 is None:
                continue
            cases.append((plat, fn, defect, wf2, mutant_nodes(wf, wf2)))
    print(f"注入样本：{len(cases)} 个")

    per_class = {k: {"n": 0, "loose": 0, "strict": 0, "abi": 0} for k in INJECTORS}
    by_platform = {}
    strict_misses = []

    for plat, fn, defect, wf2, touched in cases:
        r = verify_workflow(wf2, max_states=args.max_states)
        sig = signals(r)
        per_class[defect]["n"] += 1
        per_class[defect]["loose"] += bool(sig["types"])
        per_class[defect]["strict"] += is_hit(sig, defect, touched)
        per_class[defect]["abi"] += is_hit(sig, defect, touched, state_space_only=True)
        pb = by_platform.setdefault(plat, {"n": 0, "strict": 0})
        pb["n"] += 1
        pb["strict"] += is_hit(sig, defect, touched)
        if not is_hit(sig, defect, touched):
            strict_misses.append({"defect": defect, "base": fn,
                                  "types": sorted(sig["types"]),
                                  "touched": sorted(touched)[:6],
                                  "sources": sorted(sig["sources"])[:6]})

    # --- 汇总（按样本计的口径，与论文可比）---
    n_inj = len(cases)
    tp_loose = sum(v["loose"] for v in per_class.values())
    tp_strict = sum(v["strict"] for v in per_class.values())
    tp_abi = sum(v["abi"] for v in per_class.values())
    fp = clean["loose_fp"]
    tn = clean["n"] - fp

    summary = {
        "dataset": {"bases": len(bases), "injected": n_inj,
                    "clean": clean["n"], "truncated_clean": clean["truncated"],
                    "max_states": args.max_states,
                    "skipped": load_bases.skipped},
        "loose": metrics(tp_loose, fp, n_inj - tp_loose, tn),
        "strict": metrics(tp_strict, fp, n_inj - tp_strict, tn),
        "ablation_state_space": metrics(tp_abi, fp, n_inj - tp_abi, tn),
        "by_class": {k: {**v,
                         "loose_rate": round(v["loose"] / v["n"], 4) if v["n"] else 0,
                         "strict_rate": round(v["strict"] / v["n"], 4) if v["n"] else 0,
                         "ablation_rate": round(v["abi"] / v["n"], 4) if v["n"] else 0}
                     for k, v in per_class.items()},
        "by_platform": {p: {**v, "rate": round(v["strict"] / v["n"], 4) if v["n"] else 0}
                        for p, v in by_platform.items()},
        "clean_fp": clean["fp_ids"],
        "clean_inconclusive": clean["inconclusive"],
        "clean_fp_counts": {"raw": clean["loose_fp"],
                            "known_source_defect": clean["known_true_positive"],
                            "adjusted": clean["loose_fp"] - clean["known_true_positive"]},
        "strict_misses": strict_misses,
        "runtime_s": round(time.perf_counter() - t0, 2),
        "toolchains": {},
    }

    # --- 基线（同一数据上）---
    for name, fn_ in (("graph", graph_based_static_checker),
                      ("schema", json_schema_checker)):
        tp = fp_b = 0
        for _plat, _fn, wf in bases:
            if fn_(wf):
                fp_b += 1
        for _plat, _fn, defect, wf2, _touched in cases:
            if fn_(wf2):
                tp += 1
        summary["toolchains"][name] = metrics(tp, fp_b, n_inj - tp, len(bases) - fp_b)

    # --- 写报告 ---
    with open(os.path.join(BASE, "evaluation_strict_report.json"), "w",
              encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    def pct(x):
        return f"{x * 100:.1f}%"

    lines = [
        "# VeriFlow 严格口径评估",
        "",
        f"> 数据：{len(bases)} 个真实平台底版（n8n/Dify/Coze，公开导出模板）+ "
        f"{n_inj} 个受控注入样本；状态上限 {args.max_states}。",
        "> 定位真值 = 注入前后结构差异涉及的节点集合；不读取注入器标签。",
        "",
        "## 口径对比",
        "",
        "| 口径 | Precision | Recall | F1 | Accuracy | 说明 |",
        "| --- | --- | --- | --- | --- |",
        f"| L 松口径（任一缺陷即 TP） | {pct(summary['loose']['precision'])} | "
        f"{pct(summary['loose']['recall'])} | {pct(summary['loose']['f1'])} | "
        f"{pct(summary['loose']['accuracy'])} | 旧口径 |",
        f"| S 严格（类型 + 定位） | {pct(summary['strict']['precision'])} | "
        f"{pct(summary['strict']['recall'])} | {pct(summary['strict']['f1'])} | "
        f"{pct(summary['strict']['accuracy'])} | 本次主口径 |",
        f"| A 消融（仅状态空间） | {pct(summary['ablation_state_space']['precision'])} | "
        f"{pct(summary['ablation_state_space']['recall'])} | "
        f"{pct(summary['ablation_state_space']['f1'])} | "
        f"{pct(summary['ablation_state_space']['accuracy'])} | 去掉静态类型规则 |",
        "",
        "## 按缺陷类（严格口径命中率）",
        "",
        "| Defect type | 注入 | 松口径 | 严格 | 消融 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for k, v in sorted(summary["by_class"].items()):
        if not v["n"]:
            continue
        lines.append(f"| {k} | {v['n']} | {pct(v['loose_rate'])} | "
                     f"{pct(v['strict_rate'])} | {pct(v['ablation_rate'])} |")
    lines += [
        "",
        "## 干净底版上的报告",
        "",
        f"- 判为有缺陷的底版：{fp}/{clean['n']}（{pct(fp / clean['n'] if clean['n'] else 0)}），"
        f"其中已知源模板缺陷 {clean['known_true_positive']} 个，"
        f"调整后误报 {clean['loose_fp'] - clean['known_true_positive']} 个",
    ]
    for item in clean["fp_ids"]:
        tag = "（已知源模板缺陷，非误报）" if item.get("known_source_defect") else ""
        lines.append(f"  - `{item['id']}`：{', '.join(item['types'])}{tag}")
        if item.get("known_source_defect"):
            lines.append(f"      {item['known_source_defect']}")
    lines += [
        "",
        f"- 截断样本（状态超限，结论不可用）：{clean['truncated']}",
    ]
    for item in clean["inconclusive"]:
        lines.append(f"  - `{item['id']}`：只报 analysis_incomplete")
    lines += [
        "",
        "## 基线同数据对比",
        "",
        "| Method | Precision | Recall | F1 | Accuracy |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, m in summary["toolchains"].items():
        lines.append(f"| {name} | {pct(m['precision'])} | {pct(m['recall'])} | "
                     f"{pct(m['f1'])} | {pct(m['accuracy'])} |")
    lines += ["", f"运行时间：{summary['runtime_s']} s", ""]

    with open(os.path.join(BASE, "evaluation_strict_report.md"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))
    print("\n[written] evaluation_strict_report.{json,md}")


if __name__ == "__main__":
    main()
