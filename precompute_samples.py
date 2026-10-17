# -*- coding: utf-8 -*-
"""预计算所有样本的检测结果，存成 samples_precomputed.json，供 /api/samples 直接读取。"""
import os, json, sys, io, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from adapters import parse_dify, parse_coze, parse_n8n
from preprocess import preprocess
from verification import verify_workflow

BASE = os.path.dirname(os.path.abspath(__file__))
REAL = os.path.join(BASE, "real_samples")
samples = []
t0 = time.perf_counter()
for fn in sorted(os.listdir(REAL)):
    if not fn.endswith((".json", ".yml")) or fn.startswith("save_"):
        continue
    path = os.path.join(REAL, fn)
    try:
        if fn.startswith("coze_"):
            std = parse_coze(json.load(open(path, encoding="utf-8")), fn)
        elif fn.endswith(".yml") or fn.startswith("dify"):
            std = parse_dify(open(path, encoding="utf-8").read(), fn)
        else:
            std = parse_n8n(json.load(open(path, encoding="utf-8")), fn)
        cleaned = preprocess(std)["workflow"]
        v = verify_workflow(cleaned)
        samples.append({
            "id": os.path.splitext(fn)[0],
            "platform": std.get("platform", "?"),
            "name": std.get("name", os.path.splitext(fn)[0]),
            "source": fn,
            "nodes": len(std["nodes"]),
            "edges": len(std["edges"]),
            "types": [n["type"] for n in std["nodes"]],
            "P": v["stats"].get("|P|", 0),
            "RG": v["stats"].get("|RG|", 0),
            "defective": v["defective"],
            "defects": [d["type"] for d in v["defects"]],
        })
    except Exception as e:
        samples.append({"id": os.path.splitext(fn)[0], "source": fn, "error": str(e)[:120]})

elapsed = round(time.perf_counter() - t0, 2)
out = {"samples": samples, "elapsed_s": elapsed}
with open(os.path.join(BASE, "samples_precomputed.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(f"[written] samples_precomputed.json: {len(samples)} samples, {elapsed}s")
# 按平台统计
from collections import Counter
plats = Counter(s.get("platform", "err") for s in samples)
print(f"平台分布: {dict(plats)}")
errs = [s for s in samples if "error" in s]
print(f"失败: {len(errs)}")
for s in errs[:5]:
    print(f"  {s['source']}: {s['error']}")
