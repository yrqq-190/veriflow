# -*- coding: utf-8 -*-
"""
把 evaluation_strict_report.json 导出成网页后端消费的 full_experiment_report.json。

网页 /api/samples 只需要 `global.{schema,graph,jcpn}.{precision,recall,f1,accuracy}`
与 `n_bases / n_samples`；早期版本在这里写的是「任一缺陷即 TP」的松口径指标，
且底版数停留在 188。本脚本统一改成严格口径（类型 + 定位），并显式标注口径版本，
避免页面继续展示旧数字。
"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))


def main() -> None:
    strict_path = os.path.join(BASE, "evaluation_strict_report.json")
    if not os.path.exists(strict_path):
        raise SystemExit("先运行 evaluation_strict.py 生成 evaluation_strict_report.json")
    r = json.load(open(strict_path, encoding="utf-8"))

    ds = r["dataset"]
    report = {
        "metric_version": "strict_type_and_localization",
        "metric_note": ("TP 需同时满足：缺陷类型落在注入类别，且定位命中被注入节点；"
                        "松口径与消融结果见 loose / ablation_state_space；"
                        "截断底版上的状态空间结论按 analysis_incomplete 处理，不算命中"),
        "n_bases": ds["bases"],
        "n_samples": ds["clean"] + ds["injected"],
        "dataset": {
            "clean": ds["clean"],
            "injected": ds["injected"],
            "truncated_clean": ds["truncated_clean"],
            "max_states": ds["max_states"],
        },
        "global": {
            "jcpn": r["strict"],
            "graph": r["toolchains"]["graph"],
            "schema": r["toolchains"]["schema"],
        },
        "global_loose": {"jcpn": r["loose"]},
        "ablation_state_space": {"jcpn": r["ablation_state_space"]},
        "localization": {
            "top1_accuracy": r["strict"]["recall"],
            "correct": r["strict"]["tp"],
            "total": ds["injected"],
            "metric": "type-consistent finding must point at an injected node",
        },
        "by_type": {k: {"n": v["n"], "strict_hit_rate": v["strict_rate"],
                        "loose_hit_rate": v["loose_rate"],
                        "ablation_hit_rate": v["ablation_rate"]}
                    for k, v in r["by_class"].items()},
        "clean_false_positives": r["clean_fp"],
        "clean_fp_counts": r.get("clean_fp_counts", {}),
        "clean_inconclusive": r.get("clean_inconclusive", []),
        "by_platform": r.get("by_platform", {}),
        "strict_misses": r.get("strict_misses", []),
        "semantics": {
            "branch_termination": ("implicit_branch_termination: 条件分支未连边按平台引擎语义"
                                   "视为实例结束（并入 P_f）；VERIFLOW_STRICT_BRANCH=1 可切回"
                                   "WF-net 严格读法"),
            "truncation": ("bounded exploration: 状态数超 max_states 时，依赖可达图的性质"
                           "（死锁/非终止/残留/从未触发）一律降级为未证实，只报 analysis_incomplete"),
            "unreachable": ("不可达先做 P→T→P 结构不动点判定（与状态空间无关），"
                            "完整可达图时才补'结构可达却从未触发'"),
        },
        "runtime_s": r["runtime_s"],
    }
    out = os.path.join(BASE, "full_experiment_report.json")
    json.dump(report, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[written] {out}")
    print(f"底版 {report['n_bases']} / 样本 {report['n_samples']} / "
          f"JCPN P={report['global']['jcpn']['precision']} "
          f"R={report['global']['jcpn']['recall']} "
          f"F1={report['global']['jcpn']['f1']} "
          f"Acc={report['global']['jcpn']['accuracy']}")


if __name__ == "__main__":
    main()
