# -*- coding: utf-8 -*-
"""
VeriFlow: JCPN 建模模块（对应论文 Definition 4-3 / Algorithm 1）
=================================================================
将规范化 JSON 工作流转换为 **颜色感知的** JCPN，并显式维护 provenance 映射 μ。

JCPN = (P, T, A, Θ, C, G, X, M₀, P_f, U, μ)

相对初版的原则性修正（判定依据见 docs/FORMAL_CORE.md）：
  1. token 携带颜色（数据域类型 / 消息 id / 条件取值），弧表达式与守卫可求值；
     使能判定按 CPN 绑定（binding）语义进行，不再是"库所里有 token 就能触发"。
  2. 弧按 (u, v) 保存**表达式列表**，合并后保留多重弧；颜色族按并集合并并记录冲突，
     不再静默覆写。
  3. 决策结构：if 用两个决策变迁（t_cond_then / t_cond_else）各产出一条带 cond
     颜色的 token，从结构上杜绝"两分支汇到同一节点 → 弧表达式互相覆盖"。
  4. while：p_judge 经 t_loop（body）与 t_exit（出口）分裂；body 入口/出口互不合并，
     `branch=loop` / `branch=exit` 边各自对接，出口不再被循环体入口吞并。
  5. 消息：t_send 产出消息 token；send_only 由 t_deliver 消费，paired 由 t_recv 消费，
     unpaired（声明需要接收但网中无接收侧）则消息 token 无人消费 → 终止标识中的残留，
     由可达图判定 broken message，而不是读适配器字段。
  6. fan-out（一个节点多个普通后继）按 AND-split 建模：fork 变迁一次产出多个 token，
     下游真并发；汇合是 OR-join，与 n8n / Dify 的实际执行方式一致。
"""

from __future__ import annotations

import os
import re

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple


# ===========================================================================
# 0. 颜色与弧表达式
# ===========================================================================

F_DATA = "Θ_data"
F_MSG = "Θ_msg"
F_COND = "Θ_cond"

# 悬空分支的终止语义：True = 按 n8n/Dify 引擎语义视为实例正常结束；
# False = 论文式严格读法（流程在非终点处提前终止即缺陷）。
IMPLICIT_BRANCH_TERMINATION = os.environ.get("VERIFLOW_STRICT_BRANCH", "") != "1"

ANY_TYPE = "any"      # 未声明类型：与任意数据域兼容（适配器未提供类型时的保守解释）
PASS = "pass"         # 弧表达式：沿用输入 token 的颜色


@dataclass(frozen=True)
class Color:
    """token 颜色。kind 决定用到哪个字段。"""
    kind: str                      # "data" | "msg"
    dtype: str = ANY_TYPE          # data 用
    cond: Optional[bool] = None    # data 携带的条件取值（if 分支用）
    mid: Optional[str] = None      # msg 用

    def key(self) -> Tuple[str, str, Optional[bool], Optional[str]]:
        return (self.kind, self.dtype, self.cond, self.mid)

    def text(self) -> str:
        if self.kind == "msg":
            return f"msg({self.mid})"
        if self.cond is None:
            return f"data({self.dtype})"
        return f"data({self.dtype},c={str(self.cond).lower()})"


def data_color(dtype: str = ANY_TYPE, cond: Optional[bool] = None) -> Color:
    return Color(kind="data", dtype=dtype, cond=cond)


def msg_color(mid: str) -> Color:
    return Color(kind="msg", mid=mid)


@dataclass(frozen=True)
class Expr:
    """弧表达式。op=consume/produce，kind=data/msg，arg=类型 / 消息 id / pass。"""
    op: str
    kind: str
    arg: str
    cond: Optional[bool] = None       # produce 时写入 token 的条件颜色

    def text(self) -> str:
        if self.kind == "data":
            if self.cond is None:
                return f"{self.op}(data:{self.arg})"
            return f"{self.op}(data:{self.arg},c={str(self.cond).lower()})"
        return f"{self.op}(msg:{self.arg})"


def consume_data(dtype: str = ANY_TYPE) -> Expr:
    return Expr("consume", "data", dtype)


def produce_data(dtype: str = ANY_TYPE, cond: Optional[bool] = None) -> Expr:
    return Expr("produce", "data", dtype, cond)


def consume_msg(mid: str) -> Expr:
    return Expr("consume", "msg", mid)


def produce_msg(mid: str) -> Expr:
    return Expr("produce", "msg", mid)


# 守卫种类：真 / 假 / 按条件颜色判定 / 不可判定（开放）
G_TRUE = "true"
G_FALSE = "false"
G_COND = "cond"
G_OPEN = "open"


def guard_spec(guard: str) -> Tuple[str, Any]:
    """解析守卫。只解释本项目生成器产出的可判定形式；适配器给出的自然语言条件
    标记为 open —— 表示条件取值未知、两种结果都可能，绝不假装判定过。"""
    g = (guard or "").strip()
    low = g.lower()
    if low in ("true", "1", ""):
        return (G_TRUE, None)
    if low in ("false", "0"):
        return (G_FALSE, None)
    compact = low.replace(" ", "")
    if compact in ("[c=true]", "c=true"):
        return (G_COND, True)
    if compact in ("[c=false]", "c=false"):
        return (G_COND, False)
    return (G_OPEN, g)


# ===========================================================================
# 1. JCPN 模型容器
# ===========================================================================

@dataclass
class JCPNModel:
    """JCPN 元组容器。"""
    P: Set[str] = field(default_factory=set)
    T: Set[str] = field(default_factory=set)
    A: Set[Tuple[str, str]] = field(default_factory=set)

    Theta_data: Set[str] = field(default_factory=set)
    Theta_msg: Set[str] = field(default_factory=set)
    Theta_cond: str = F_COND

    C: Dict[str, str] = field(default_factory=dict)
    G: Dict[str, str] = field(default_factory=dict)
    X: Dict[Tuple[str, str], str] = field(default_factory=dict)
    U: Dict[str, str] = field(default_factory=dict)
    arcs: Dict[Tuple[str, str], List[Expr]] = field(default_factory=dict)
    guard_of: Dict[str, Tuple[str, Any]] = field(default_factory=dict)

    M0: Dict[str, List[Color]] = field(default_factory=dict)
    P_f: Set[str] = field(default_factory=set)

    mu: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    _reverse: Dict[str, str] = field(default_factory=dict, repr=False)
    _reg_order: Dict[str, int] = field(default_factory=dict, repr=False)
    _seq: int = field(default=0, repr=False, compare=False)

    _split_transitions: Set[str] = field(default_factory=set, repr=False)
    _cond_places: Set[str] = field(default_factory=set, repr=False)
    _branch_places: Dict[str, Set[str]] = field(default_factory=dict, repr=False)

    warnings: List[str] = field(default_factory=list, repr=False)
    notes: List[str] = field(default_factory=list, repr=False)

    # ------------------------------------------------------------------
    def register(self,
                 source_id: str,
                 kind: str,
                 places: Optional[Set[str]] = None,
                 transitions: Optional[Set[str]] = None,
                 arcs: Optional[Sequence[Tuple[str, str]]] = None,
                 source_node: Optional[Dict[str, Any]] = None) -> None:
        """记录源节点生成的 JCPN 元素（Algorithm 1 line 36）。"""
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

        self._seq += 1
        seq = self._seq
        for el in list(places or ()) + list(transitions or ()):
            if el not in self._reg_order:
                self._reg_order[el] = seq
                self._reverse[el] = source_id
        for (u, v) in (arcs or ()):
            key = f"{u}->{v}"
            if key not in self._reg_order:
                self._reg_order[key] = seq
                self._reverse[key] = source_id

    def lookup(self, source_id: str) -> Optional[Dict[str, Any]]:
        return self.mu.get(source_id)

    def reverse_lookup(self, model_element: str) -> Optional[str]:
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
        self._interfaces: Dict[str, Tuple[str, List[str]]] = {}
        self._uf: Dict[str, str] = {}
        self._if_branch_places: Dict[str, Dict[str, str]] = {}
        self.branch_by_node: Dict[str, Set[str]] = {}
        self._workflow = workflow or {}
        if workflow:
            for e in workflow.get("edges", []):
                b = e.get("branch")
                if b:      # "true" / "false" / 平台 case id 都算分支标签
                    self.branch_by_node.setdefault(e.get("from"), set()).add(str(b))

    # ------------------------------------------------------------------
    def _merge(self, a: str, b: str) -> None:
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
        if name in self._uf:
            return self._root(name)
        return name

    def _add_place(self, name: str, family: str) -> None:
        m = self.model
        m.P.add(name)
        fams = set(filter(None, m.C.get(name, "").split(" ∪ "))) | {family}
        m.C[name] = " ∪ ".join(sorted(fams))

    def _add_transition(self, name: str, guard: str = "true",
                        update: Optional[str] = None) -> None:
        m = self.model
        m.T.add(name)
        m.G[name] = guard
        m.guard_of[name] = guard_spec(guard)
        if update:
            m.U[name] = update

    def _add_arc(self, u: str, v: str, expr: Expr) -> None:
        m = self.model
        m.A.add((u, v))
        m.arcs.setdefault((u, v), []).append(expr)
        m.X[(u, v)] = " ⊗ ".join(e.text() for e in m.arcs[(u, v)])

    # ------------------------------------------------------------------
    # 2.1 任务子网
    # ------------------------------------------------------------------
    def BuildTaskSubnet(self, node: Dict[str, Any]) -> None:
        nid = node["id"]
        p_in, t, p_out = f"p_in_{nid}", f"t_{nid}", f"p_out_{nid}"
        in_t = (node.get("input_type") or ANY_TYPE)
        out_t = (node.get("output_type") or PASS)

        self._add_place(p_in, F_DATA)
        self._add_place(p_out, F_DATA)
        self._add_transition(t, guard="true", update=f"U_{nid}")
        self._add_arc(p_in, t, consume_data(in_t))
        self._add_arc(t, p_out, produce_data(out_t))

        self.model.register(nid, kind="task", places={p_in, p_out},
                            transitions={t}, arcs={(p_in, t), (t, p_out)},
                            source_node=node)
        self._interfaces[nid] = (p_in, [p_out])

    # ------------------------------------------------------------------
    # 2.2 消息子网（§4.3.2）
    # ------------------------------------------------------------------
    def BuildMessageSubnet(self, node: Dict[str, Any]) -> None:
        """三种接收语义，全部落在网结构上：

        send_only ：p_in → t_send → p_msg → t_deliver → p_out   （单向投递，无残留）
        paired    ：p_in → t_send → p_msg → t_recv    → p_recv  （合成接收侧）
        unpaired  ：p_in → t_send → {p_msg, p_out}              （消息 token 无人消费）
        """
        nid = node["id"]
        mode = node.get("pairing", "send_only")
        req = bool(node.get("requires_receive", mode in ("paired", "unpaired")))
        mid = f"msg_{nid}"

        p_in, t_send, p_msg, p_out = (f"p_in_{nid}", f"t_send_{nid}",
                                      f"p_msg_{nid}", f"p_out_{nid}")
        self._add_place(p_in, F_DATA)
        self._add_place(p_msg, F_MSG)
        self._add_place(p_out, F_DATA)
        self._add_transition(t_send, guard="true", update=f"U_{nid}")
        self._add_arc(p_in, t_send, consume_data(ANY_TYPE))
        self._add_arc(t_send, p_msg, produce_msg(mid))
        self.model.Theta_msg.add(mid)

        arcs = {(p_in, t_send), (t_send, p_msg)}
        transitions = {t_send}
        places = {p_in, p_msg, p_out}

        if req and mode == "paired":
            t_recv, p_recv = f"t_recv_{nid}", f"p_recv_{nid}"
            self._add_place(p_recv, F_DATA)
            self._add_transition(t_recv, guard="true", update=f"U_{nid}")
            self._add_arc(p_msg, t_recv, consume_msg(mid))
            self._add_arc(t_recv, p_recv, produce_data(PASS))
            arcs |= {(p_msg, t_recv), (t_recv, p_recv)}
            transitions.add(t_recv)
            places.add(p_recv)
            exits = [p_recv]
        elif not req:
            t_del = f"t_deliver_{nid}"
            self._add_transition(t_del, guard="true", update=f"U_{nid}")
            self._add_arc(p_msg, t_del, consume_msg(mid))
            self._add_arc(t_del, p_out, produce_data(PASS))
            arcs |= {(p_msg, t_del), (t_del, p_out)}
            transitions.add(t_del)
            exits = [p_out]
        else:
            # 声明需要接收、网中却没有接收侧：主流程继续走，消息 token 永久残留
            self._add_arc(t_send, p_out, produce_data(PASS))
            arcs.add((t_send, p_out))
            exits = [p_out]

        self.model.register(nid, kind="message", places=places,
                            transitions=transitions, arcs=arcs, source_node=node)
        self._interfaces[nid] = (p_in, exits)

    # ------------------------------------------------------------------
    # 2.3 if-else 子网（§4.3.3）
    # ------------------------------------------------------------------
    def _branch_plan(self, node: Dict[str, Any]) -> List[Tuple[str, str, str]]:
        """确定该 if 的分支集合及其（标签, 变迁名, 库所名）。

        顺序固定：true → false → 其余（按标签字典序）。任何 if 都保留 false 分支：
        平台语义里「条件为假且未连边」等于实例在此结束；是否算缺陷由
        IMPLICIT_BRANCH_TERMINATION 决定，而不是在建模阶段抹掉。
        """
        nid = node["id"]
        labels = set(self.branch_by_node.get(nid, set())) | {"true", "false"}
        if node.get("then") is not None:
            labels.add("true")
        if node.get("else") is not None:
            labels.add("false")
        ordered = [l for l in ("true", "false") if l in labels]
        ordered += sorted(l for l in labels if l not in ("true", "false"))
        plan = []
        case_idx = 0
        for label in ordered:
            if label == "true":
                tname, pname = f"t_cond_then_{nid}", f"p_then_{nid}"
            elif label == "false":
                tname, pname = f"t_cond_else_{nid}", f"p_else_{nid}"
            else:
                case_idx += 1
                tname, pname = f"t_cond_case{case_idx}_{nid}", f"p_case{case_idx}_{nid}"
            plan.append((label, tname, pname))
        return plan

    def BuildIfElseSubnet(self, node: Dict[str, Any]) -> None:
        nid = node["id"]
        p_in, p_out = f"p_in_{nid}", f"p_out_{nid}"
        self._add_place(p_in, F_DATA)
        self._add_place(p_out, F_DATA)

        plan = self._branch_plan(node)
        places = {p_in, p_out}
        transitions: Set[str] = set()
        arcs: Set[Tuple[str, str]] = set()
        branch_places: Dict[str, str] = {}

        for label, tname, pname in plan:
            self._add_place(pname, F_COND)
            self._add_transition(tname, guard="true", update=f"U_{nid}")
            self._add_arc(p_in, tname, consume_data(ANY_TYPE))
            self._add_arc(tname, pname, produce_data(PASS, label))
            places.add(pname)
            transitions.add(tname)
            arcs |= {(p_in, tname), (tname, pname)}
            branch_places[label] = pname

        self.model._split_transitions.update(transitions)
        self.model._cond_places.update(branch_places.values())
        self.model._branch_places[nid] = set(branch_places.values())
        self._if_branch_places[nid] = branch_places

        self.model.register(nid, kind="if", places=places,
                            transitions=transitions, arcs=arcs, source_node=node)
        self._interfaces[nid] = (p_in, [p_out])

        # 结构化写法（then / else 嵌套子树）仍按原方式接线
        for label in ("true", "false"):
            branch_node = node.get("then" if label == "true" else "else")
            if branch_node is None or label not in branch_places:
                continue
            p_branch = branch_places[label]
            if isinstance(branch_node, dict) and "id" in branch_node:
                self._dispatch(branch_node)
                c_entry, c_exits = self._interfaces[branch_node["id"]]
                self._merge(p_branch, c_entry)
                for ce in c_exits:
                    self._merge(ce, p_out)
            elif isinstance(branch_node, list) and branch_node:
                self._dispatch_sequence(branch_node, p_branch, p_out)

    # ------------------------------------------------------------------
    # 2.4 while 子网（§4.3.4）
    # ------------------------------------------------------------------
    def BuildWhileSubnet(self, node: Dict[str, Any]) -> None:
        nid = node["id"]
        p_judge, t_loop, t_exit, p_out = (f"p_judge_{nid}", f"t_loop_{nid}",
                                          f"t_exit_{nid}", f"p_out_{nid}")
        p_body = f"p_body_{nid}"

        has_exit = node.get("exit") is True
        flat_loop = any(e.get("from") == nid and e.get("branch") == "loop"
                        for e in self._workflow.get("edges", []))

        self._add_place(p_judge, F_DATA)
        self._add_place(p_out, F_DATA)
        self._add_place(p_body, F_DATA)

        self._add_transition(t_loop, guard="[c = true]", update=f"U_{nid}")
        self._add_arc(p_judge, t_loop, consume_data(ANY_TYPE))
        self._add_arc(t_loop, p_body, produce_data(PASS))

        places = {p_judge, p_out, p_body}
        transitions = {t_loop}
        arcs = {(p_judge, t_loop), (t_loop, p_body)}

        if has_exit:
            self._add_transition(t_exit, guard="[c = false]", update=f"U_{nid}")
            self._add_arc(p_judge, t_exit, consume_data(ANY_TYPE))
            self._add_arc(t_exit, p_out, produce_data(PASS))
            arcs |= {(p_judge, t_exit), (t_exit, p_out)}
            transitions.add(t_exit)

        self.model._cond_places.add(p_judge)
        self.model.register(nid, kind="while", places=places,
                            transitions=transitions, arcs=arcs, source_node=node)
        self.model.register(f"{nid}::body", kind="while_body", places={p_body},
                            source_node=node)
        self._interfaces[nid] = (p_judge, [p_out])

        body = node.get("body")
        if isinstance(body, dict) and "id" in body:
            self._dispatch(body)
            c_entry, c_exits = self._interfaces[body["id"]]
            self._merge(p_body, c_entry)
            for ce in c_exits:
                self._merge(ce, p_judge)          # 回边
        elif isinstance(body, list) and body:
            self._dispatch_sequence(body, p_body, p_judge)
        elif flat_loop:
            pass                                   # 平面 loop 边在 Stage 2 对接
        else:
            self._merge(p_body, p_judge)           # 空循环体

    # ------------------------------------------------------------------
    def _dispatch_sequence(self, seq: List[dict], entry: str, exit_: str) -> None:
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
    # 3. 接口解析
    # ------------------------------------------------------------------
    def _resolve_all(self) -> None:
        m = self.model
        old_P = set(m.P)

        m.P = {self._resolve(p) for p in old_P}

        new_C: Dict[str, str] = {}
        for p, fam in m.C.items():
            rp = self._resolve(p)
            if rp in new_C and new_C[rp] != fam:
                fams = set(new_C[rp].split(" ∪ ")) | set(fam.split(" ∪ "))
                # 颜色族并集是 CPN 的正常情形（一个库所可容纳多种颜色的 token）；
                # 只有把消息 token 与数据 token 合进同一库所才是语义混淆。
                if F_MSG in fams and F_DATA in fams:
                    m.warnings.append(
                        f"message token and data token share place {rp}")
                new_C[rp] = " ∪ ".join(sorted(fams))
            else:
                new_C.setdefault(rp, fam)
        m.C = new_C

        new_A: Set[Tuple[str, str]] = set()
        new_arcs: Dict[Tuple[str, str], List[Expr]] = {}
        for (u, v), exprs in m.arcs.items():
            ru = self._resolve(u) if u in old_P else u
            rv = self._resolve(v) if v in old_P else v
            new_A.add((ru, rv))
            new_arcs.setdefault((ru, rv), []).extend(exprs)
        m.A = new_A
        m.arcs = new_arcs

        # 悬空分支（分支库所没有任何后继弧）：n8n / Dify 引擎的语义是「实例在此结束」。
        # 默认把该库所并入完成集 P_f；设 VERIFLOW_STRICT_BRANCH=1 可切回论文式严格读法
        # （流程在非终点处提前终止 = missing_branch）。
        consumers = {u for (u, _v) in new_arcs if u in m.P}
        for nid, labels in self._if_branch_places.items():
            for label, pname in labels.items():
                rp = self._resolve(pname)
                if rp in consumers:
                    continue
                if IMPLICIT_BRANCH_TERMINATION:
                    m.P_f.add(rp)
                    m.notes.append(
                        f"implicit_termination: if '{nid}' branch '{label}' has no target; "
                        f"treated as run termination (added to P_f)")
                else:
                    m.notes.append(
                        f"dangling_branch: if '{nid}' branch '{label}' has no target "
                        f"(strict reading: missing_branch)")
        m.X = {(u, v): " ⊗ ".join(e.text() for e in exprs)
               for (u, v), exprs in new_arcs.items()}

        new_M0: Dict[str, List[Color]] = {}
        for p, toks in m.M0.items():
            new_M0.setdefault(self._resolve(p), []).extend(toks)
        m.M0 = new_M0
        m.P_f = {self._resolve(p) for p in m.P_f}

        for _src, entry in m.mu.items():
            entry["places"] = {self._resolve(p) for p in entry["places"]}
            entry["arcs"] = {
                f"{self._resolve(a.split('->')[0]) if a.split('->')[0] in old_P else a.split('->')[0]}"
                f"->{self._resolve(a.split('->')[1]) if a.split('->')[1] in old_P else a.split('->')[1]}"
                for a in entry["arcs"]}

        best: Dict[str, Tuple[int, str]] = {}
        for el, seq in m._reg_order.items():
            if el in old_P:
                key = self._resolve(el)
            elif "->" in el:
                left, right = el.split("->", 1)
                left = self._resolve(left) if left in old_P else left
                right = self._resolve(right) if right in old_P else right
                key = f"{left}->{right}"
            else:
                key = el
            cur = best.get(key)
            if cur is None or seq < cur[0]:
                best[key] = (seq, m._reverse.get(el, ""))
        m._reverse = {k: src for k, (_seq, src) in best.items() if src}

        m._cond_places = {self._resolve(p) for p in m._cond_places}
        m._branch_places = {src: {self._resolve(p) for p in ps}
                            for src, ps in m._branch_places.items()}

        # Θ_data / Θ_msg 是「颜色取值」的全集（数据类型与消息 id），不是库所集合
        m.Theta_data = {ANY_TYPE}
        m.Theta_msg = set()
        for (_u, _v), exprs in m.arcs.items():
            for e in exprs:
                if e.op != "produce":
                    continue
                if e.kind == "msg":
                    m.Theta_msg.add(e.arg)
                elif e.arg != PASS:
                    m.Theta_data.add(e.arg)

        self._interfaces = {
            nid: (self._resolve(entry), [self._resolve(e) for e in exits])
            for nid, (entry, exits) in self._interfaces.items()}


# ===========================================================================
# 4. 变换主入口（Algorithm 1）
# ===========================================================================

def transform(normalized_workflow: Dict[str, Any]) -> JCPNModel:
    builder = JCPNBuilder(normalized_workflow)
    model = builder.model

    for node in normalized_workflow.get("nodes", []):
        builder._dispatch(node)

    interfaces = builder._interfaces
    branch_places = builder._if_branch_places

    # 普通边按源节点分组：多后继走一次 AND-split，单后继直接合并接口
    normal_groups: Dict[str, List[str]] = {}
    for e in normalized_workflow.get("edges", []):
        if e.get("branch") is None and e.get("from") in interfaces:
            normal_groups.setdefault(e["from"], []).append(e.get("to"))

    for edge in normalized_workflow.get("edges", []):
        u, v = edge.get("from"), edge.get("to")
        b = edge.get("branch")
        if u not in interfaces:
            continue

        # (a) if 分支边：分支库所 → 目标子网入口（标签可为 true/false/平台 case id）
        if b is not None and u in branch_places and b in branch_places[u]:
            if v not in interfaces:
                continue
            bp = branch_places[u][b]
            builder._merge(bp, interfaces[v][0])
            model.register(source_id=f"edge:{u}->{v}", kind="edge",
                           arcs={(bp, interfaces[v][0])})
            continue

        # (b) while 的 loop 边 → body 入口
        if b == "loop":
            p_body = f"p_body_{u}"
            if v in interfaces and p_body in model.P:
                builder._merge(p_body, interfaces[v][0])
                model.register(source_id=f"edge:{u}->{v}", kind="edge",
                               arcs={(p_body, interfaces[v][0])})
            continue

        # (c) while 的 exit 边 → 出口
        if b == "exit":
            if v not in interfaces:
                continue
            for p_out in interfaces[u][1]:
                builder._merge(p_out, interfaces[v][0])
                model.register(source_id=f"edge:{u}->{v}", kind="edge",
                               arcs={(p_out, interfaces[v][0])})
            continue

    # (d) 普通边
    for u, targets in normal_groups.items():
        if not targets:
            continue
        exits = interfaces[u][1]

        if len(targets) == 1:
            v = targets[0]
            if v not in interfaces:
                continue
            for p_out in exits:
                builder._merge(p_out, interfaces[v][0])
                model.register(source_id=f"edge:{u}->{v}", kind="edge",
                               arcs={(p_out, interfaces[v][0])})
            continue

        # AND-split：一个 fork 变迁，每个后继各得一个 token（真并发）
        t_fork = f"t_fork_{u}"
        builder._add_transition(t_fork, guard="true")
        fork_arcs: List[Tuple[str, str]] = []
        for p_out in exits:
            builder._add_arc(p_out, t_fork, consume_data(ANY_TYPE))
            fork_arcs.append((p_out, t_fork))
        for v in targets:
            if v not in interfaces:
                continue
            builder._add_arc(t_fork, interfaces[v][0], produce_data(PASS))
            fork_arcs.append((t_fork, interfaces[v][0]))
        model.register(source_id=f"fork:{u}", kind="fork",
                       transitions={t_fork}, arcs=fork_arcs)

    _assign_boundary_markings(model, normalized_workflow, builder)
    builder._resolve_all()

    return model


def _assign_boundary_markings(model: JCPNModel,
                              workflow: Dict[str, Any],
                              builder: JCPNBuilder) -> None:
    """入口/终端识别（Appendix A.1/A.2）+ M₀ / P_f。"""
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

    for n in nodes:
        nid = n.get("id")
        if n.get("type") == "if" and n.get("then") is not None:
            out_deg[nid] = max(out_deg[nid], 1)
        if n.get("type") == "while" and n.get("exit") is True:
            out_deg[nid] = max(out_deg[nid], 1)

    entry = None
    terminals = []
    for n in nodes:
        if n.get("type") in ("start", "Start"):
            entry = n["id"]
        if n.get("type") in ("end", "End"):
            terminals.append(n["id"])

    if entry is None:
        candidates = [nid for nid in node_ids
                      if in_deg[nid] == 0 and out_deg[nid] != 0]
        if candidates:
            entry = sorted(candidates)[0]

    if not terminals:
        terminals = [nid for nid in node_ids if out_deg[nid] == 0]

    if entry and entry in builder._interfaces:
        entry_place, _ = builder._interfaces[entry]
        model.M0[entry_place] = [data_color()]

    for tn in terminals:
        if tn in builder._interfaces:
            _, exits = builder._interfaces[tn]
            model.P_f.update(exits)


# ===========================================================================
# 5. 缺陷定位
# ===========================================================================

def localize_defect(model: JCPNModel,
                    abnormal_element: str) -> Optional[Dict[str, Any]]:
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
        if mdl.warnings:
            print("warnings:", mdl.warnings)
    else:
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
