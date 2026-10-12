# -*- coding: utf-8 -*-
"""
VeriFlow: JCPN 建模模块（对应论文 Definition 3-3 / Algorithm 1）
=================================================================
将规范化 JSON 工作流转换为 JCPN 模型，并显式维护 provenance 映射 μ。

JCPN = (P, T, A, Θ, C, G, X, M₀, P_f, U, μ)

相对 deepseek 初版的三个原则性修正：
  1. 子网连接采用「接口合并」（Union-Find），而非 place→place 非法弧
     （A ⊆ (P×T) ∪ (T×P)）；
  2. while 节点在 source 缺失 exit 时**不生成** t_exit（保留缺陷供验证）；
     消息节点按平台适配器：n8n 配对生成完整 send/receive 子网，
     Dify/Coze 或未配对消息只生成 t_send，不合成 t_recv；
  3. 决策语义：if.t_cond 为「变迁分裂」（输出弧带 c=true/c=false 标记），
     while.p_judge 为「库所分裂」（输出变迁守卫互斥），二者共同支撑
     可达图构建时的非确定性分支枚举（缺失分支 → 无后继 → 死锁）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


# ===========================================================================
# 0. 颜色集（Definition 3-4）
# ===========================================================================

THETA_COND = "Θ_cond"
THETA_DATA = "Θ_data"
THETA_MSG = "Θ_msg"

TRUE_GUARD = "[c = true]"
FALSE_GUARD = "[c = false]"


# ===========================================================================
# 1. JCPN 模型容器
# ===========================================================================

@dataclass
class JCPNModel:
    """JCPN 元组容器。结构元素存于集合/字典，注册幂等。"""
    # ---- 核心结构 ----
    P: Set[str] = field(default_factory=set)              # 库所
    T: Set[str] = field(default_factory=set)              # 变迁
    A: Set[Tuple[str, str]] = field(default_factory=set)  # 弧 ⊆ (P×T) ∪ (T×P)

    # ---- 颜色集（Θ = Θ_data ∪ Θ_msg ∪ Θ_cond）----
    Theta_data: Set[str] = field(default_factory=set)
    Theta_msg: Set[str] = field(default_factory=set)
    Theta_cond: str = THETA_COND

    # ---- 函数 ----
    C: Dict[str, str] = field(default_factory=dict)              # 库所 → 颜色
    G: Dict[str, str] = field(default_factory=dict)              # 变迁 → 守卫
    X: Dict[Tuple[str, str], str] = field(default_factory=dict)  # 弧 → 弧表达式
    U: Dict[str, str] = field(default_factory=dict)              # 变迁 → 数据更新函数

    # ---- 标识 ----
    M0: Dict[str, List[Any]] = field(default_factory=dict)       # 初始标识
    P_f: Set[str] = field(default_factory=set)                   # 完成库所集合

    # ---- provenance 映射 μ ----
    # source_id → {kind, places, transitions, arcs, source_node}
    mu: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # O(1) 反向索引：JCPN 元素 → 源节点 id
    _reverse: Dict[str, str] = field(default_factory=dict, repr=False)

    # ---- 决策标记（供可达图构建）----
    _split_transitions: Set[str] = field(default_factory=set, repr=False)  # if.t_cond
    _cond_places: Set[str] = field(default_factory=set, repr=False)        # while.p_judge

    # ------------------------------------------------------------------
    # μ 注册
    # ------------------------------------------------------------------
    def register(self,
                 source_id: str,
                 kind: str,
                 places: Optional[Set[str]] = None,
                 transitions: Optional[Set[str]] = None,
                 arcs: Optional[Set[Tuple[str, str]]] = None,
                 source_node: Optional[Dict[str, Any]] = None) -> None:
        """
        记录从源工作流节点生成的 JCPN 元素（Algorithm 1 line 11）。
        每个 Build*Subnet 都必须调用。
        """
        entry = self.mu.setdefault(
            source_id,
            {"places": set(), "transitions": set(), "arcs": set(),
             "kind": kind, "source_node": source_node or {}},
        )
        if places:
            entry["places"].update(places)
        if transitions:
            entry["transitions"].update(transitions)
        if arcs:
            entry["arcs"].update({f"{u}->{v}" for (u, v) in arcs})
        if source_node:
            entry["source_node"].update(source_node)

        for p in (places or ()):
            self._reverse[p] = source_id
        for t in (transitions or ()):
            self._reverse[t] = source_id
        for (u, v) in (arcs or ()):
            self._reverse[f"{u}->{v}"] = source_id

    def lookup(self, source_id: str) -> Optional[Dict[str, Any]]:
        """正向查找：源节点 → 生成的 JCPN 元素。"""
        return self.mu.get(source_id)

    def reverse_lookup(self, model_element: str) -> Optional[str]:
        """反向查找：JCPN 库所/变迁/弧 → 源工作流节点（用于缺陷定位）。"""
        return self._reverse.get(model_element)

    def __repr__(self) -> str:
        return (f"JCPNModel(|P|={len(self.P)}, |T|={len(self.T)}, "
                f"|A|={len(self.A)}, |μ|={len(self.mu)})")


# ===========================================================================
# 2. 子网构建器
# ===========================================================================

class JCPNBuilder:
    """由规范化工作流构建 JCPN 模型。"""

    def __init__(self, workflow: Optional[Dict[str, Any]] = None) -> None:
        self.model = JCPNModel()
        # 节点接口：node_id → (entry_place, [exit_places])
        self._interfaces: Dict[str, Tuple[str, List[str]]] = {}
        # 库所合并并查集：place 原始名 → 根名
        self._uf: Dict[str, str] = {}
        # 扁平分支（edges.branch）：if 节点 → {branch: 分裂库所}（平台适配器模式）
        self._if_branch_places: Dict[str, Dict[str, str]] = {}
        # 预索引：源节点 → 其出现的 branch 标记集合（edges.branch ∈ {true,false}）
        self.branch_by_node: Dict[str, Set[str]] = {}
        if workflow:
            for e in workflow.get("edges", []):
                b = e.get("branch")
                if b in ("true", "false"):
                    self.branch_by_node.setdefault(e.get("from"), set()).add(b)

    # ------------------------------------------------------------------
    # 接口合并（Union-Find）
    # ------------------------------------------------------------------
    def _merge(self, a: str, b: str) -> None:
        """将两个库所合并为同一个（论文 §3.3.1: 相邻子网输出/输入库所合并）。"""
        ra, rb = self._root(a), self._root(b)
        if ra != rb:
            self._uf[ra] = rb

    def _root(self, x: str) -> str:
        path = []
        while self._uf.get(x, x) != x:
            path.append(x)
            x = self._uf[x]
        for p in path:
            self._uf[p] = x
        return x

    def _resolve(self, name: str) -> str:
        """返回库所的规范化（根）名称。"""
        if name in self._uf:
            return self._root(name)
        return name

    def _add_place(self, name: str, color: str) -> None:
        self.model.P.add(name)
        self.model.C[name] = color

    def _add_transition(self, name: str, guard: str = "true",
                        update: Optional[str] = None) -> None:
        self.model.T.add(name)
        self.model.G[name] = guard
        if update:
            self.model.U[name] = update

    def _add_arc(self, u: str, v: str, expr: str = "") -> None:
        self.model.A.add((u, v))
        if expr:
            self.model.X[(u, v)] = expr

    # ------------------------------------------------------------------
    # 2.1 任务子网：p_in → t → p_out（§3.3.1）
    # ------------------------------------------------------------------
    def BuildTaskSubnet(self, node: Dict[str, Any]) -> None:
        nid = node["id"]
        p_in, t, p_out = f"p_in_{nid}", f"t_{nid}", f"p_out_{nid}"

        self._add_place(p_in, THETA_DATA)
        self._add_place(p_out, THETA_DATA)
        self._add_transition(t, guard="true", update=f"U_{nid}")
        self._add_arc(p_in, t, "consume(d)")
        self._add_arc(t, p_out, "produce(U_{nid}(d))")

        self.model.Theta_data.add(f"data_{nid}")
        self.model.register(nid, kind="task", places={p_in, p_out},
                            transitions={t}, arcs={(p_in, t), (t, p_out)},
                            source_node=node)
        self._interfaces[nid] = (p_in, [p_out])

    # ------------------------------------------------------------------
    # 2.2 消息子网（§3.3.2 + 平台适配器）
    # ------------------------------------------------------------------
    def BuildMessageSubnet(self, node: Dict[str, Any]) -> None:
        """
        n8n 配对（pairing=paired）：p_send → t_send → p_msg → t_recv → p_recv
        Dify/Coze 或未配对（send_only / unpaired）：
            只生成 p_send → t_send → p_msg —— 不合成 t_recv，
            该交互保留为 broken-message 候选（由验证模块按 μ 元数据判定）。
        p_msg 同时充当子网出口接口，流程可继续推进。
        """
        nid = node["id"]
        pairing = node.get("pairing", "send_only")
        p_send, t_send, p_msg = f"p_send_{nid}", f"t_send_{nid}", f"p_msg_{nid}"

        self._add_place(p_send, THETA_DATA)
        self._add_place(p_msg, THETA_MSG)
        self._add_transition(t_send, guard="true", update=f"U_{nid}")
        self._add_arc(p_send, t_send, "consume(d)")
        self._add_arc(t_send, p_msg, "produce(token(msg_{nid}))")
        self.model.Theta_msg.add(f"msg_{nid}")

        arcs = {(p_send, t_send), (t_send, p_msg)}
        transitions = {t_send}
        places = {p_send, p_msg}

        if pairing == "paired":
            t_recv, p_recv = f"t_recv_{nid}", f"p_recv_{nid}"
            self._add_place(p_recv, THETA_DATA)
            self._add_transition(t_recv, guard="true", update=f"U_{nid}")
            self._add_arc(p_msg, t_recv, "consume(token(msg_{nid}))")
            self._add_arc(t_recv, p_recv, "produce(d)")
            arcs |= {(p_msg, t_recv), (t_recv, p_recv)}
            transitions.add(t_recv)
            places.add(p_recv)
            exits = [p_recv]
        else:
            # send-only / unpaired：不合成 t_recv，p_msg 即出口
            exits = [p_msg]

        self.model.register(nid, kind="message", places=places,
                            transitions=transitions, arcs=arcs,
                            source_node=node)
        self._interfaces[nid] = (p_send, exits)

    # ------------------------------------------------------------------
    # 2.3 if-else 子网（§3.3.3）
    # ------------------------------------------------------------------
    def BuildIfElseSubnet(self, node: Dict[str, Any]) -> None:
        """
        p_in → t_cond → p_then →[then 子网]→ p_out
                    └→ p_else →[else 子网]→ p_out   （仅当 source 有 else）
        t_cond 为决策变迁：输出弧带 c=true / c=false 标记（可达图分裂枚举）。
        source 缺失 else 时**不生成** else 分支 —— 缺陷保留。
        """
        nid = node["id"]
        p_in, t_cond, p_then, p_out = (
            f"p_in_{nid}", f"t_cond_{nid}", f"p_then_{nid}", f"p_out_{nid}")

        self._add_place(p_in, THETA_DATA)
        self._add_place(p_then, THETA_COND)
        self._add_place(p_out, THETA_DATA)
        self._add_transition(t_cond, guard="true")
        self._add_arc(p_in, t_cond, "consume(d)")
        self._add_arc(t_cond, p_then, "c=true")

        places = {p_in, p_then, p_out}
        transitions = {t_cond}
        arcs = {(p_in, t_cond), (t_cond, p_then)}

        # 分支存在性：嵌套 then/else（合成用例）或扁平 branch 边（平台适配器）
        branches = self.branch_by_node.get(nid, set())
        has_nested_then = ("then" in node and node["then"] is not None)
        has_nested_else = ("else" in node and node["else"] is not None)
        need_then = has_nested_then or "true" in branches
        need_else = has_nested_else or "false" in branches

        if need_else:
            p_else = f"p_else_{nid}"
            self._add_place(p_else, THETA_COND)
            self._add_arc(t_cond, p_else, "c=false")
            places.add(p_else)
            arcs.add((t_cond, p_else))

        # 决策变迁标记
        self.model._split_transitions.add(t_cond)
        self._if_branch_places[nid] = {"true": p_then}
        if need_else:
            self._if_branch_places[nid]["false"] = p_else

        self.model.register(nid, kind="if", places=places,
                            transitions=transitions, arcs=arcs,
                            source_node=node)
        self._interfaces[nid] = (p_in, [p_out])

        # --- 递归构建 then / else 子网并合并接口（嵌套模式；扁平分支由 edges 在 Stage 2 合并）---
        if isinstance(node.get("then"), dict) and "id" in node["then"]:
            self._dispatch(node["then"])
            c_entry, c_exits = self._interfaces[node["then"]["id"]]
            self._merge(p_then, c_entry)
            for ce in c_exits:
                self._merge(ce, p_out)
        elif isinstance(node.get("then"), list):
            seq_then = node["then"]
            if seq_then:
                self._dispatch_sequence(seq_then, p_then, p_out)

        if has_nested_else:
            if isinstance(node["else"], dict) and "id" in node["else"]:
                self._dispatch(node["else"])
                c_entry, c_exits = self._interfaces[node["else"]["id"]]
                self._merge(p_else, c_entry)
                for ce in c_exits:
                    self._merge(ce, p_out)
            elif isinstance(node["else"], list):
                self._dispatch_sequence(node["else"], p_else, p_out)

    # ------------------------------------------------------------------
    # 2.4 while 子网（§3.3.4）
    # ------------------------------------------------------------------
    def BuildWhileSubnet(self, node: Dict[str, Any]) -> None:
        """
        entry=p_judge →[分裂]→ t_loop →[body 子网]→(回边合并)→ p_judge
                             └→ t_exit → p_out   （仅当 source 声明 exit）
        p_judge 为决策库所：输出变迁守卫 [c=true] / [c=false]。
        source 缺失 exit 时**不生成** t_exit —— 缺陷保留（非终止/死锁）。
        data_dependent=True 时退出依赖数据更新，验证阶段按抽象保守报告。
        """
        nid = node["id"]
        p_judge, t_loop, t_exit, p_out = (
            f"p_judge_{nid}", f"t_loop_{nid}", f"t_exit_{nid}", f"p_out_{nid}")

        self._add_place(p_judge, THETA_COND)
        self._add_place(p_out, THETA_DATA)
        self._add_transition(t_loop, guard=TRUE_GUARD, update=f"U_{nid}")
        self._add_arc(p_judge, t_loop, "consume(token(true))")

        places = {p_judge, p_out}
        transitions = {t_loop}
        arcs = {(p_judge, t_loop)}

        has_exit = node.get("exit") is True
        if has_exit:
            self._add_transition(t_exit, guard=FALSE_GUARD, update=f"U_{nid}")
            self._add_arc(p_judge, t_exit, "consume(token(false))")
            self._add_arc(t_exit, p_out, "produce(d)")
            arcs |= {(p_judge, t_exit), (t_exit, p_out)}
            transitions.add(t_exit)

        # 决策库所标记
        self.model._cond_places.add(p_judge)

        self.model.register(nid, kind="while", places=places,
                            transitions=transitions, arcs=arcs,
                            source_node=node)
        self._interfaces[nid] = (p_judge, [p_out])

        # --- 递归构建 body 子网：t_loop 输出 → body 入口；body 出口 → 回边到 p_judge ---
        p_body_tmp = f"p_body_{nid}"
        self._add_place(p_body_tmp, THETA_DATA)
        self._add_arc(t_loop, p_body_tmp, "produce(d)")

        body = node.get("body")
        if isinstance(body, dict) and "id" in body:
            self._dispatch(body)
            c_entry, c_exits = self._interfaces[body["id"]]
            self._merge(p_body_tmp, c_entry)
            for ce in c_exits:
                self._merge(ce, p_judge)          # 回边
        elif isinstance(body, list) and body:
            self._dispatch_sequence(body, p_body_tmp, p_judge)  # 序列出口回边
        else:
            # 空循环体（平台适配：Dify iteration / Coze loop 无内嵌 body）：
            # 每次迭代直接回到判定库所，仍可经 t_exit 正常退出。
            self._merge(p_body_tmp, p_judge)

    # ------------------------------------------------------------------
    # 2.5 嵌套序列组合
    # ------------------------------------------------------------------
    def _dispatch_sequence(self, seq: List[dict], entry: str, exit_: str) -> None:
        """将节点列表按顺序组合：entry → n0 → n1 → … → exit_"""
        for i, c in enumerate(seq):
            if not isinstance(c, dict) or "id" not in c:
                continue
            self._dispatch(c)
            c_entry, c_exits = self._interfaces[c["id"]]
            if i == 0:
                self._merge(entry, c_entry)
            else:
                prev = seq[i - 1]
                _, prev_exits = self._interfaces[prev["id"]]
                for pe in prev_exits:
                    self._merge(pe, c_entry)
            if i == len(seq) - 1:
                for ce in c_exits:
                    self._merge(ce, exit_)

    # ------------------------------------------------------------------
    # 2.6 递归调度（§3.3.5）
    # ------------------------------------------------------------------
    def _dispatch(self, node: Dict[str, Any]) -> None:
        ntype = node.get("type")
        if ntype == "task":
            self.BuildTaskSubnet(node)
        elif ntype == "message":
            self.BuildMessageSubnet(node)
        elif ntype == "if":
            self.BuildIfElseSubnet(node)
        elif ntype == "while":
            self.BuildWhileSubnet(node)
        else:
            raise ValueError(f"Unknown node type: {ntype}")

    # ------------------------------------------------------------------
    # 3. 接口解析：将全部库所替换为并查集根名
    # ------------------------------------------------------------------
    def _resolve_all(self) -> None:
        m = self.model
        old_P = m.P                       # 合并前的原始库所集合（判定用）

        # 库所集
        new_P = {self._resolve(p) for p in old_P}
        m.P = new_P

        # 颜色分配
        m.C = {self._resolve(p): col for p, col in m.C.items()}

        # 弧（端点含库所与变迁；变迁不变；库所判定基于旧集合）
        new_A = set()
        new_X = {}
        for (u, v) in m.A:
            ru = self._resolve(u) if u in old_P else u
            rv = self._resolve(v) if v in old_P else v
            new_A.add((ru, rv))
            if (u, v) in m.X:
                new_X[(ru, rv)] = m.X[(u, v)]
        m.A = new_A
        m.X = new_X

        # 初始标识与完成库所
        m.M0 = {self._resolve(p): toks for p, toks in m.M0.items()}
        m.P_f = {self._resolve(p) for p in m.P_f}

        # μ 与反向索引
        for src, entry in m.mu.items():
            entry["places"] = {self._resolve(p) for p in entry["places"]}
            entry["arcs"] = {
                f"{self._resolve(a.split('->')[0]) if a.split('->')[0] in old_P else a.split('->')[0]}"
                f"->{self._resolve(a.split('->')[1]) if a.split('->')[1] in old_P else a.split('->')[1]}"
                for a in entry["arcs"]}
        # 反向索引（冲突时保留先注册者 —— 合并库所归属其主体源节点）
        new_rev: Dict[str, str] = {}
        for el, src in m._reverse.items():
            key = self._resolve(el) if el in old_P else el
            if key not in new_rev:
                new_rev[key] = src
        m._reverse = new_rev

        # 决策标记
        m._split_transitions = {t for t in m._split_transitions}
        m._cond_places = {self._resolve(p) for p in m._cond_places}

        # 接口表
        self._interfaces = {
            nid: (self._resolve(entry), [self._resolve(e) for e in exits])
            for nid, (entry, exits) in self._interfaces.items()}


# ===========================================================================
# 4. 变换主入口（Algorithm 1）
# ===========================================================================

def transform(normalized_workflow: Dict[str, Any]) -> JCPNModel:
    """
    Algorithm 1：规范化工作流 → JCPN 模型。
    阶段：子网构建 → 接口合并连接 → 边界标识 → 解析规范化。
    """
    builder = JCPNBuilder(normalized_workflow)
    model = builder.model

    # Stage 1: 构建全部子网（Algorithm 1 lines 4-12）
    for node in normalized_workflow.get("nodes", []):
        builder._dispatch(node)

    # Stage 2: 按控制流连接子网（lines 13-15）——接口合并而非 place→place 弧
    #   扁平分支边（edges.branch）：合并到 if 决策库所的 true/false 分裂库所；
    #   普通边：合并源子网出口库所 → 目标子网入口库所。
    interfaces = builder._interfaces
    branch_places = builder._if_branch_places
    for edge in normalized_workflow.get("edges", []):
        u, v = edge.get("from"), edge.get("to")
        if u not in interfaces or v not in interfaces:
            continue    # 悬空边跳过，不修复
        v_entry, _ = interfaces[v]
        b = edge.get("branch")
        if b in ("true", "false") and u in branch_places and b in branch_places[u]:
            bp = branch_places[u][b]
            builder._merge(bp, v_entry)
            model.register(source_id=f"edge:{u}->{v}", kind="edge", arcs={(bp, v_entry)})
            continue
        _, u_exits = interfaces[u]
        for p_out in u_exits:
            builder._merge(p_out, v_entry)
            model.register(source_id=f"edge:{u}->{v}", kind="edge",
                           arcs={(p_out, v_entry)})

    # Stage 3: 边界标识（lines 16）——入口节点 M₀ 与完成库所 P_f
    _assign_boundary_markings(model, normalized_workflow, builder)

    # Stage 4: 库所合并规范化
    builder._resolve_all()

    return model


def _assign_boundary_markings(model: JCPNModel,
                              workflow: Dict[str, Any],
                              builder: JCPNBuilder) -> None:
    """
    入口/终端节点识别（论文 Appendix A 三层策略的 A.1/A.2 规则）：
      - 平台原生标注：type ∈ {start, Start} / {end, End}（A.1）
      - 结构规则：入口 = 无入边节点（多候选取最小 id）；
                 终端 = 无出边节点（A.2）
      孤立节点（无入边且无出边）不作为入口候选。
    """
    nodes = workflow.get("nodes", [])
    edges = workflow.get("edges", [])
    node_ids = {n["id"] for n in nodes}

    in_deg = {nid: 0 for nid in node_ids}
    out_deg = {nid: 0 for nid in node_ids}
    for e in edges:
        u, v = e.get("from"), e.get("to")
        if u in out_deg:
            out_deg[u] += 1
        if v in in_deg:
            in_deg[v] += 1

    # 结构出口（嵌套分支/循环的出边不显式出现在 edges 中）：
    #   - if 节点具备 then 分支即存在到合并出口 p_out 的路径；
    #   - while 节点声明 exit=True 即存在出口变迁。
    for n in nodes:
        nid = n.get("id")
        if n.get("type") == "if" and n.get("then") is not None:
            out_deg[nid] = max(out_deg[nid], 1)
        if n.get("type") == "while" and n.get("exit") is True:
            out_deg[nid] = max(out_deg[nid], 1)

    # Tier 1: 平台原生标注
    entry = None
    terminals = []
    for n in nodes:
        if n.get("type") in ("start", "Start"):
            entry = n["id"]
        if n.get("type") in ("end", "End"):
            terminals.append(n["id"])

    # Tier 2: 结构规则
    if entry is None:
        candidates = [nid for nid in node_ids
                      if in_deg[nid] == 0 and out_deg[nid] != 0]  # 排除孤立节点
        if candidates:
            entry = sorted(candidates)[0]

    if not terminals:
        terminals = [nid for nid in node_ids if out_deg[nid] == 0]

    # M₀：入口节点子网入口库所一个数据 token
    if entry and entry in builder._interfaces:
        entry_place, _ = builder._interfaces[entry]
        model.M0[entry_place] = ["<data-token>"]

    # P_f：全部终端节点子网出口库所
    for tn in terminals:
        if tn in builder._interfaces:
            _, exits = builder._interfaces[tn]
            model.P_f.update(exits)


# ===========================================================================
# 5. 缺陷定位（§3.5，经 μ 回溯）
# ===========================================================================

def localize_defect(model: JCPNModel,
                    abnormal_element: str) -> Optional[Dict[str, Any]]:
    """
    给定异常 JCPN 元素（死锁标识中的库所、未触发变迁或弧），
    经 provenance 映射 μ 回溯到源工作流节点。

    返回 dict：{source_id, kind, elements, source_node}；未找到返回 None。
    """
    source_id = model.reverse_lookup(abnormal_element)
    if source_id is None:
        return None
    entry = model.mu.get(source_id, {})
    return {
        "source_id": source_id,
        "kind": entry.get("kind"),
        "elements": {
            "places": sorted(entry.get("places", set())),
            "transitions": sorted(entry.get("transitions", set())),
            "arcs": sorted(entry.get("arcs", set())),
        },
        "source_node": entry.get("source_node", {}),
    }


# ===========================================================================
# 6. CLI 自检
# ===========================================================================

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            raw = json.load(f)
        from preprocess import preprocess
        norm = preprocess(raw)["workflow"]
        mdl = transform(norm)
        print(mdl)
        for src, entry in mdl.mu.items():
            print(f"μ[{src}] kind={entry['kind']} "
                  f"P={sorted(entry['places'])} T={sorted(entry['transitions'])}")
        print("M0 =", mdl.M0)
        print("P_f =", sorted(mdl.P_f))
    else:
        # 内置最小示例
        wf = {
            "nodes": [
                {"id": "t_submit", "type": "task", "name": "submit"},
                {"id": "t_audit", "type": "task", "name": "audit"},
            ],
            "edges": [{"from": "t_submit", "to": "t_audit"}],
        }
        mdl = transform(wf)
        print(mdl)
        print(localize_defect(mdl, "t_audit"))
