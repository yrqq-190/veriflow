import glob, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from adapters import parse_dify
from preprocess import preprocess
from verification import verify_workflow

for f in sorted(glob.glob("real_samples/dify_*.yml") + glob.glob("real_samples/dify_*.yaml")):
    try:
        std = parse_dify(open(f, encoding="utf-8").read(), os.path.basename(f))
        pp = preprocess(std)
        v = verify_workflow(pp["workflow"])
        name = os.path.basename(f)
        n = len(std["nodes"])
        e = len(std["edges"])
        defs = [d["type"] for d in v["defects"]]
        print(f"{name:40s} nodes={n:3d} edges={e:3d} defective={v['defective']} defects={defs}")
    except Exception as ex:
        print(f"{os.path.basename(f):40s} ERROR: {ex}")
