/* VeriFlow front-end controller: bilingual chat + verification pipeline + repair flow */
(function () {
  "use strict";

  var lang = "zh";                     // 中文为主语言（默认）；英文版保留可切换
  var current = null;                  // 最近一次 pipeline 结果（含 steps/workflow/verify/repairs/model_digest）
  var awaitingRepair = false;
  var awaitingClarify = false;
  var lastText = "";

  var I18N = {
    en: {
      connected: "Local engine online",
      conversation: "CONVERSATION",
      title: "Describe a workflow in plain language",
      newChat: "+ New conversation",
      samples: "Samples & pipeline",
      samplesTitle: "Real samples & detection pipeline",
      assistant: "VERIFLOW ASSISTANT",
      intro: "Tell me the business process you want to automate. I will plan it, build a JCPN model, run formal verification, fix any defects with your confirmation, and deliver a correct workflow.",
      placeholder: "Describe a workflow to verify…  e.g. 学生请假审批流程，三天内辅导员审批，超过三天学院审批，通过后通知学生并登记",
      hint: "Enter to send · Shift+Enter for a new line",
      send: "Generate & verify ↗",
      execution: "Verification pipeline",
      details: "Inspect JSON & JCPN model",
      transparent: "Verification evidence",
      jsonTab: "JSON intermediate representation",
      cpnTab: "JCPN model",
      reportTab: "Verification report",
      graphTab: "Workflow graph",
      normalized: "Workflow JSON",
      graphEmpty: "Run a generation to see the workflow graph.",
      cpnEmpty: "Run a generation to see the JCPN model.",
      genStatus: "Verification summary",
      clean: "No defects detected — workflow is safe to deliver.",
      defective: "Defects detected — see repair suggestions below.",
      clarifyTitle: "Before generating, I need a few clarifications:",
      repairTitle: "Repair suggestions — please confirm which to apply:",
      applyRepair: "Apply selected repairs",
      repairing: "Applying repairs and re-verifying…",
      exportWorkflow: "Export workflow JSON",
      downloading: "Exported — check your browser downloads.",
      samplesLoading: "Loading samples…",
      loadError: "Failed to load samples.",
      stages: {
        requirements_capture: "Requirements capture",
        requirements_analysis: "Requirements analysis",
        requirements_clarification: "Requirements clarification",
        requirements_confirmation: "Requirements confirmation",
        workflow_planning: "Workflow planning",
        json_intermediate_representation: "JSON intermediate representation",
        jcpn_model_construction: "JCPN model construction",
        formal_verification: "Formal verification",
        defect_repair: "Defect repair",
        workflow_output: "Workflow output"
      },
      defectNames: {
        unreachable_node: "Unreachable node",
        unexpected_deadlock: "Unexpected deadlock",
        non_termination_risk: "Non-termination risk",
        broken_message: "Broken message interaction",
        missing_branch: "Missing branch",
        isolated_node: "Isolated node",
        variable_constraint: "Variable-constraint error"
      }
    },
    zh: {
      connected: "本地引擎在线",
      conversation: "对话",
      title: "描述你想要的工作流",
      newChat: "+ 新对话",
      samples: "样本与检测过程",
      samplesTitle: "真实样本与检测过程",
      assistant: "VERIFLOW 助手",
      intro: "把你想自动化的业务流程告诉我。我会规划步骤、构建 JCPN 模型并做形式化验证；发现缺陷时先和你确认再修复，最终交付一个验证通过的工作流。",
      placeholder: "描述要验证的工作流…  例如：学生请假审批流程，三天内辅导员审批，超过三天学院审批，通过后通知学生并登记",
      hint: "回车发送 · Shift+Enter 换行",
      send: "生成并验证 ↗",
      execution: "验证流程",
      details: "查看建模细节",
      transparent: "验证依据",
      jsonTab: "JSON 中间表示",
      cpnTab: "JCPN 模型",
      reportTab: "验证报告",
      graphTab: "工作流图",
      normalized: "工作流 JSON",
      graphEmpty: "先运行一次生成，查看工作流图。",
      cpnEmpty: "先运行一次生成，查看 JCPN 模型。",
      genStatus: "验证结果",
      clean: "未发现缺陷，工作流可交付。",
      defective: "发现缺陷，下面是修复建议。",
      clarifyTitle: "生成之前，有几件事需要和你确认：",
      repairTitle: "修复建议 — 请勾选要应用的项目：",
      applyRepair: "应用所选修复",
      repairing: "正在应用修复并重新验证…",
      exportWorkflow: "导出工作流 JSON",
      downloading: "已导出 — 请查看浏览器下载。",
      samplesLoading: "正在加载样本…",
      loadError: "样本加载失败。",
      stages: {
        requirements_capture: "需求录入",
        requirements_analysis: "需求解析",
        requirements_clarification: "需求澄清",
        requirements_confirmation: "需求确认",
        workflow_planning: "流程规划",
        json_intermediate_representation: "JSON 中间表示",
        jcpn_model_construction: "JCPN 建模",
        formal_verification: "形式化验证",
        defect_repair: "缺陷修复",
        workflow_output: "输出工作流"
      },
      defectNames: {
        unreachable_node: "不可达节点",
        unexpected_deadlock: "意外死锁",
        non_termination_risk: "非终止风险",
        broken_message: "消息交互断裂",
        missing_branch: "缺失分支",
        isolated_node: "孤立节点",
        variable_constraint: "变量约束错误"
      }
    }
  };

  var STAGES = [
    "requirements_capture", "requirements_analysis", "requirements_clarification",
    "requirements_confirmation", "workflow_planning", "json_intermediate_representation",
    "jcpn_model_construction", "formal_verification", "defect_repair", "workflow_output"
  ];

  function t(key) { return I18N[lang][key] || key; }
  function stageTitle(id) {
    var s = I18N[lang].stages[id];
    return s || id;
  }
  function defectName(tp) {
    return (I18N[lang].defectNames[tp] || tp);
  }

  // ---------------------------------------------------------------------
  // DOM helpers
  // ---------------------------------------------------------------------
  var chatEl = document.getElementById("chat");
  var stepsEl = document.getElementById("steps");
  var promptEl = document.getElementById("prompt");
  var sendBtn = document.getElementById("sendButton");
  var progressCount = document.getElementById("progressCount");
  var drawer = document.getElementById("drawer");
  var jsonCode = document.getElementById("jsonCode");
  var graphSvg = document.getElementById("graphSvg");
  var cpnGraph = document.getElementById("cpnGraph");
  var muList = document.getElementById("muList");
  var cpnStats = document.getElementById("cpnStats");
  var reportBody = document.getElementById("reportBody");
  var samplesModal = document.getElementById("samplesModal");
  var samplesBody = document.getElementById("samplesBody");

  function addMessage(role, html) {
    var m = document.createElement("div");
    m.className = "message " + role;
    var avatar = role === "user" ? "" : '<div class="avatar">AI</div>';
    m.innerHTML = avatar + '<div class="bubble">' + html + "</div>";
    chatEl.appendChild(m);
    chatEl.scrollTop = chatEl.scrollHeight;
    return m;
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function briefJSON(wf) {
    var nodes = (wf && wf.nodes) || [];
    return nodes.map(function (n) {
      var extra = "";
      if (n.type === "if") extra = " · " + (n.condition || "");
      if (n.type === "message") extra = " → " + (n.sender || "") + " (" + (n.platform || "") + ")";
      if (n.type === "while") extra = " · exit=" + (n.exit !== false ? "true" : "false");
      return "[" + n.type + "] " + n.name + extra;
    }).join("\n");
  }

  // ---------------------------------------------------------------------
  // Pipeline steps rendering
  // ---------------------------------------------------------------------
  function renderSteps(steps) {
    stepsEl.innerHTML = "";
    var doneCount = 0;
    STAGES.forEach(function (id, i) {
      var step = null;
      if (steps) step = steps.filter(function (s) { return s.stage === id; })[0];
      var li = document.createElement("li");
      var status = step ? step.status : "pending";
      if (status === "done") doneCount++;
      li.className = "step " + (status === "done" ? "complete" : (status === "blocked" ? "error" : (status === "active" ? "active" : "")));
      li.innerHTML = '<span class="step-number">' + (i + 1) + "</span>" +
        '<span class="step-title">' + esc(stageTitle(id)) + "</span>" +
        (step && step.note ? '<span class="step-sub">' + esc(step.note) + "</span>" : "");
      stepsEl.appendChild(li);
    });
    progressCount.textContent = doneCount + " / 10";
  }

  // ---------------------------------------------------------------------
  // Mermaid renderers（工作流图 / CPN 图）
  // ---------------------------------------------------------------------
  var mermaidReady = (typeof mermaid !== "undefined");
  var mermaidQueue = Promise.resolve();

  function safeMermaidId(id) {
    // mermaid 节点 id 仅允许 [A-Za-z0-9_]，uuid 连字符需转换
    return String(id).replace(/[^A-Za-z0-9_]/g, "_");
  }

  function mermaidSafe(t) {
    // mermaid 边标签 / 节点 label 中的特殊字符：{}| 会破坏解析，替换为可读字符
    return String(t).replace(/\{/g, "(").replace(/\}/g, ")").replace(/\|/g, "/");
  }

  function renderWithMermaid(container, definition, emptyMsg) {
    if (!mermaidReady || !definition) {
      container.innerHTML = "<p class='empty'>" + esc(emptyMsg) + "</p>";
      return;
    }
    // 串行队列：避免 mermaid.render 并发冲突（工作流图 + CPN 图同时渲染）
    mermaidQueue = mermaidQueue.then(function () {
      return new Promise(function (resolve) {
        var tmp = document.createElement("div");
        tmp.style.display = "none";
        document.body.appendChild(tmp);
        var uid = "vf" + Math.random().toString(36).slice(2, 8);
        mermaid.render(uid, definition).then(function (res) {
          container.innerHTML = '<div class="mermaid-box">' + res.svg + "</div>";
          tmp.remove();
          resolve();
        }).catch(function () {
          container.innerHTML = "<p class='empty'>" + esc(emptyMsg) + "</p>";
          tmp.remove();
          resolve();
        });
      });
    });
  }

  function workflowMermaid(wf) {
    if (!wf || !wf.nodes || !wf.nodes.length) return null;
    var lines = ["flowchart LR"];
    lines.push("  classDef task fill:#0d1420,stroke:#7898ff,color:#e6edf6");
    lines.push("  classDef cond fill:#0d1420,stroke:#ffba4b,color:#e6edf6");
    lines.push("  classDef msg  fill:#0d1420,stroke:#d5ff43,color:#e6edf6");
    lines.push("  classDef loop fill:#0d1420,stroke:#ff5d68,color:#e6edf6");
    var nid = {}, i;
    wf.nodes.forEach(function (n) {
      var mid = safeMermaidId(n.id);
      nid[n.id] = mid;
      var label = esc((n.name || n.id).replace(/"/g, "'"));
      if (n.type === "if") {
        lines.push("  " + mid + "{\"" + label + (n.condition ? "<br/>" + esc(n.condition) : "") + "\"}:::cond");
      } else if (n.type === "message") {
        lines.push("  " + mid + "(\"" + label + "\"):::msg");
      } else if (n.type === "while") {
        lines.push("  " + mid + "{{\"" + label + "\"}}:::loop");
      } else {
        lines.push("  " + mid + "[\"" + label + "\"]:::task");
      }
    });
    (wf.edges || []).forEach(function (e) {
      var a = nid[e.from], b = nid[e.to];
      if (!a || !b) return;
      var lab = "";
      if (e.branch === "true") lab = "|true|";
      else if (e.branch === "false") lab = "|false|";
      else if (e.branch === "exit") lab = "|exit|";
      lines.push("  " + a + " -->" + lab + " " + b);
    });
    return lines.join("\n");
  }

  function cpnMermaid(digest) {
    if (!digest || !digest.places || !digest.places.length) return null;
    var lines = ["flowchart LR"];
    lines.push("  classDef place fill:#0d1420,stroke:#8de28c,color:#e6edf6");
    lines.push("  classDef trans fill:#0d1420,stroke:#ffba4b,color:#e6edf6");
    var mid = {};
    digest.places.forEach(function (p) {
      var m = safeMermaidId(p.id);
      mid[p.id] = m;
      lines.push("  " + m + "((\"" + esc(p.id) + (p.final ? "·final" : "") + "\")):::place");
    });
    digest.transitions.forEach(function (tr) {
      var m = safeMermaidId(tr.id);
      mid[tr.id] = m;
      var g = tr.guard && tr.guard !== "true" ? "<br/>" + esc(mermaidSafe(tr.guard)) : "";
      lines.push("  " + m + "[\"" + esc(tr.id) + g + "\"]:::trans");
    });
    digest.arcs.forEach(function (a) {
      var x = mid[a.from], y = mid[a.to];
      if (!x || !y) return;
      var lab = a.expr && a.expr !== "1`x" ? '|"' + esc(mermaidSafe(a.expr)) + '"|' : "";
      lines.push("  " + x + " -->" + lab + " " + y);
    });
    return lines.join("\n");
  }

  function renderGraph(wf) {
    renderWithMermaid(graphSvg, workflowMermaid(wf), t("graphEmpty"));
  }

  function renderCpn(digest) {
    if (!digest || !digest.places || !digest.places.length) {
      cpnGraph.innerHTML = "<p class='empty'>" + esc(t("cpnEmpty")) + "</p>";
      muList.innerHTML = "";
      cpnStats.textContent = "—";
      return;
    }
    cpnStats.textContent = "|P|=" + digest["|P|"] + "  |T|=" + digest["|T|"] + "  |A|=" + digest["|A|"] + "  μ=" + digest.mu.length;
    renderWithMermaid(cpnGraph, cpnMermaid(digest), t("cpnEmpty"));
    // provenance μ 列表（源节点 → JCPN 元素）
    var html = "<div class='mu-head'>Provenance μ · 源节点 → JCPN 元素</div>";
    digest.mu.forEach(function (m) {
      html += "<div class='mu-row'><b>" + esc(m.source) + "</b><span>" + esc(m.kind) +
        " · P[" + m.places.length + "] T[" + m.transitions.length + "]</span></div>";
    });
    muList.innerHTML = html;
  }

  // ---------------------------------------------------------------------
  // Verification report / repair suggestions
  // ---------------------------------------------------------------------
  function renderReport(verify, repairs) {
    var html = "";
    var stats = verify.stats || {};
    // 证据卡片：无论是否有缺陷都显示可达图统计
    html += '<div class="report-card" style="margin-bottom:12px"><div>' +
      '<h3 style="margin:0 0 8px 0">' + esc(lang === "en" ? "Verification evidence" : "验证证据") + '</h3>' +
      '<table style="width:100%;font-size:13px;border-collapse:collapse">' +
      '<tr><td style="padding:3px 16px 3px 0;color:#888">' + esc(lang === "en" ? "Reachability states" : "可达图状态数") + '</td><td><b>' + (stats["|RG|"] || "-") + '</b></td>' +
      '<td style="padding:3px 16px 3px 0;color:#888">' + esc(lang === "en" ? "Places/Transitions/Arcs" : "库所/变迁/弧") + '</td><td><b>' + (stats["|P|"] || "-") + ' / ' + (stats["|T|"] || "-") + ' / ' + (stats["|A|"] || "-") + '</b></td></tr>' +
      '<tr><td style="padding:3px 16px 3px 0;color:#888">' + esc(lang === "en" ? "Fired transitions" : "已触发变迁") + '</td><td><b>' + (stats.fired_transitions || "-") + '</b></td>' +
      '<td style="padding:3px 16px 3px 0;color:#888">' + esc(lang === "en" ? "Preprocess errors" : "预处理错误") + '</td><td><b>' + (stats.preprocess_errors || 0) + '</b></td></tr>' +
      '</table></div></div>';
    if (verify && verify.defects && verify.defects.length) {
      verify.defects.forEach(function (d) {
        var srcs = (d.sources || []).join(", ");
        var src = d.source_id || (d.sources && d.sources.length ? srcs : "workflow");
        html += '<div class="report-card danger"><span>!</span><div>' +
          "<h3>" + esc(defectName(d.type)) + "</h3>" +
          "<p>" + esc(d.detail || "") + "</p>" +
          "<p><b>" + esc(lang === "en" ? "Source node" : "源节点") + ":</b> " + esc(src) + "</p></div></div>";
      });
    } else {
      html += '<div class="report-card"><span>✓</span><div><h3>' +
        esc(lang === "en" ? "Verification passed" : "验证通过") +
        "</h3><p>" + esc(lang === "en" ? "All reachable states terminate or reach a completion marking. 5 defect classes checked: unreachable node, unexpected deadlock, non-termination cycle, broken message, variable constraint." : "所有可达状态均终止或到达完成标识。已检查 5 类缺陷：不可达节点、意外死锁、非终止循环、断裂消息、变量约束。") + "</p></div></div>";
    }
    reportBody.innerHTML = html;
  }

  function renderRepairs(repairs) {
    var html = '<div class="repair-options">';
    var auto = repairs.filter(function (r) { return r.auto; });
    var manual = repairs.filter(function (r) { return !r.auto; });
    [auto, manual].forEach(function (group) {
      group.forEach(function (r) {
        html += '<label class="repair-option"><input type="checkbox" value="' + esc(r.repair_id) +
          '"' + (r.auto ? "" : " disabled") + "> <span><b>" + esc(defectName(r.defect_type)) +
          (r.auto ? '<span class="conf">auto ' + esc(r.confidence) + "</span>" : '<span class="conf">manual</span>') +
          "</b><small>" + esc(r.description) + "</small></span></label>";
      });
    });
    html += "</div>";
    html += '<div class="repair"><div><p class="eyebrow">' + esc(lang === "en" ? "ACTION" : "操作") +
      '</p><h3>' + esc(t("applyRepair")) + "</h3><p>" +
      esc(lang === "en" ? "Repairs are applied to the JSON workflow, then the model is re-verified." : "修复会应用到 JSON 工作流，然后重新验证模型。") +
      "</p></div><button id=\"applyRepairBtn\">" + esc(t("applyRepair")) + "</button></div>";
    return html;
  }

  function addClarifyBlock(questions) {
    var html = "<p><b>" + esc(t("clarifyTitle")) + "</b></p>";
    questions.forEach(function (q) {
      html += '<div class="report-card"><span>?</span><div><h3>' + esc(q.id) + "</h3><p>" +
        esc(q.question) + "</p></div></div>";
    });
    html += '<div class="repair"><div><p class="eyebrow">ANSWER</p><h3>' +
      esc(lang === "en" ? "Provide your answers" : "请回答") +
      '</h3><p>' + esc(lang === "en" ? "Answers will be merged into the request and re-generated." : "你的回答会合并进需求，重新生成工作流。") +
      "</p></div></div>";
    return html;
  }

  // ---------------------------------------------------------------------
  // API
  // ---------------------------------------------------------------------
  function post(path, body) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    }).then(function (r) { return r.json(); });
  }

  function handlePipelineResult(res, typing) {
    typing.remove();
    renderSteps(res.steps || null);
    if (res.status === "awaiting_clarification") {
      awaitingClarify = true;
      current = res;
      addMessage("assistant", addClarifyBlock(res.questions));
      addMessage("assistant", "<p>" + esc(lang === "en" ? "Type your answers above (e.g. 平台：n8n), then press Send." : "在输入框回答上面的问题（例如：平台：n8n），然后回车发送。") + "</p>");
      return;
    }
    current = res;
    awaitingRepair = res.status === "awaiting_repair";
    var summary = res.verify.defective
      ? esc(t("defective")) + "<br><span class='badge'>" + res.verify.defects.map(function (d) { return esc(defectName(d.type)); }).join("</span> <span class='badge'>") + "</span>"
      : "<span class='badge ok'>" + esc(t("clean")) + "</span>";
    addMessage("assistant", "<p><b>" + esc(t("genStatus")) + "</b></p>" +
      "<p>" + summary + "</p>" +
      "<pre style='max-height:220px;overflow:auto'>" + esc(briefJSON(res.workflow)) + "</pre>");
    if (res.repairs && res.repairs.length) {
      addMessage("assistant", renderRepairs(res.repairs));
    }
    renderReport(res.verify, res.repairs);
    renderGraph(res.workflow);
    renderCpn(res.model_digest);
    jsonCode.textContent = JSON.stringify(res.workflow, null, 2);
    document.getElementById("jsonStatus").textContent =
      (res.verify.defective ? (lang === "en" ? "defects detected" : "检测到缺陷") : (lang === "en" ? "verified clean" : "验证通过"));
  }

  function runGenerate(text) {
    lastText = text;
    awaitingRepair = false;
    awaitingClarify = false;
    current = null;
    renderSteps([{ stage: "requirements_capture", status: "active", note: esc(lang === "en" ? "Reading your description…" : "正在读取你的描述…") }]);
    var typing = addMessage("assistant", '<div class="msg-typing">' + esc(lang === "en" ? "Analyzing and verifying…" : "正在分析与验证…") + "</div>");
    post("/api/generate", { text: text }).then(function (res) {
      handlePipelineResult(res, typing);
    }).catch(function (e) {
      typing.remove();
      addMessage("assistant", "<p class='badge'>" + esc("Error: " + e) + "</p>");
    });
  }

  function runClarify(text) {
    var answers = {};
    var qs = (current && current.questions) || [];
    if (qs.length) answers[qs[0].id] = text;
    awaitingClarify = false;
    renderSteps([{ stage: "requirements_clarification", status: "active", note: esc(lang === "en" ? "Merging your answers…" : "正在合并你的回答…") }]);
    var typing = addMessage("assistant", '<div class="msg-typing">' + esc(lang === "en" ? "Re-generating…" : "正在重新生成…") + "</div>");
    post("/api/clarify", { text: lastText, answers: answers }).then(function (res) {
      handlePipelineResult(res, typing);
    }).catch(function (e) {
      typing.remove();
      addMessage("assistant", "<p class='badge'>" + esc("Error: " + e) + "</p>");
    });
  }

  function applyRepairs(accepted) {
    awaitingRepair = false;
    renderSteps([{ stage: "defect_repair", status: "active", note: esc(t("repairing")) }]);
    var typing = addMessage("assistant", '<div class="msg-typing">' + esc(t("repairing")) + "</div>");
    post("/api/confirm", { accepted: accepted }).then(function (res) {
      typing.remove();
      renderSteps(res.steps || null);
      current = res;
      if (res.status === "clean") {
        addMessage("assistant", "<span class='badge ok'>" + esc(t("clean")) + "</span><p>" +
          esc(lang === "en" ? "Repairs applied: " : "已应用修复：") + (res.applied || []).map(function (r) { return esc(r.repair_id); }).join(", ") +
          "</p><pre style='max-height:220px;overflow:auto'>" + esc(briefJSON(res.workflow)) + "</pre>" +
          "<p><button class='mini-button export-btn' id='exportBtn'>" + esc(t("exportWorkflow")) + "</button></p>");
        document.getElementById("exportBtn").onclick = function () { exportWorkflow(); };
        renderReport(res.verify, []);
        renderGraph(res.workflow);
        renderCpn(res.model_digest);
        jsonCode.textContent = JSON.stringify(res.workflow, null, 2);
        document.getElementById("jsonStatus").textContent = lang === "en" ? "verified clean" : "验证通过";
      } else if (res.status === "still_defective") {
        addMessage("assistant", "<p class='badge'>" + esc(lang === "en" ? "Some defects remain (manual review needed): " : "仍有缺陷，需人工复核：") +
          res.verify.defects.map(function (d) { return esc(defectName(d.type)); }).join(", ") + "</p>");
        renderReport(res.verify, []);
        renderGraph(res.workflow);
        renderCpn(res.model_digest);
        jsonCode.textContent = JSON.stringify(res.workflow, null, 2);
      }
    }).catch(function (e) {
      typing.remove();
      addMessage("assistant", "<p class='badge'>" + esc("Error: " + e) + "</p>");
    });
  }

  function exportWorkflow() {
    if (!current || !current.workflow) return;
    post("/api/export", { workflow: current.workflow }).then(function (res) {
      if (res.status !== "ok") return;
      var blob = new Blob([res.json], { type: "application/json" });
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "veriflow_workflow.json";
      a.click();
      addMessage("assistant", "<span class='badge ok'>" + esc(t("downloading")) + "</span>");
    });
  }

  // ---------------------------------------------------------------------
  // Samples & detection pipeline（演示按钮）
  // ---------------------------------------------------------------------
  function pct(x) {
    return (Math.round(x * 1000) / 10).toFixed(1) + "%";
  }

  function loadSamples() {
    samplesBody.innerHTML = "<p class='empty'>" + esc(t("samplesLoading")) + "</p>";
    fetch("/api/samples").then(function (r) { return r.json(); }).then(function (d) {
      var html = "";
      // 1) 样本清单
      html += "<h3>真实平台样本 · 逐样本检测（" + d.samples.length + " 个，" + d.elapsed_s + " s）</h3>";
      html += "<table class='samples-table'><thead><tr><th>样本</th><th>平台</th><th>节点</th><th>|P|</th><th>|RG|</th><th>验证结果</th><th>检测到的缺陷</th></tr></thead><tbody>";
      d.samples.forEach(function (s) {
        var verdict = s.error ? "<span class='badge'>err</span>" :
          (s.defective ? "<span class='badge'>缺陷</span>" : "<span class='badge ok'>通过</span>");
        var defects = s.defects ? s.defects.map(function (x) { return esc(defectName(x)); }).join(", ") : "";
        html += "<tr><td>" + esc(s.id) + "</td><td>" + esc(s.platform || "?") + "</td><td>" + (s.nodes || 0) +
          "</td><td>" + (s["|P|"] || 0) + "</td><td>" + (s["|RG|"] || 0) + "</td><td>" + verdict +
          "</td><td>" + (defects || "—") + "</td></tr>";
      });
      html += "</tbody></table>";

      // 2) 三方法评估对比
      var ev = d.evaluation || {};
      var names = { jcpn: "JCPN", graph: "Graph static checker", schema: "JSON Schema" };
      var order = ["schema", "graph", "jcpn"];
      html += "<h3>评估对比（真实平台数据 · 实测，不参照论文）</h3>";
      html += "<table class='samples-table'><thead><tr><th>Method</th><th>Precision</th><th>Recall</th><th>F1</th><th>Accuracy</th></tr></thead><tbody>";
      order.forEach(function (k) {
        var r = ev[k];
        if (!r) return;
        html += "<tr><td><b>" + esc(names[k]) + "</b></td><td>" + pct(r.precision) + "</td><td>" + pct(r.recall) +
          "</td><td>" + pct(r.f1) + "</td><td>" + pct(r.accuracy) + "</td></tr>";
      });
      html += "</tbody></table>";

      // 3) 混淆矩阵（JCPN）
      var j = ev.jcpn;
      if (j) {
        html += "<h3>JCPN 混淆矩阵</h3>";
        html += "<table class='samples-table'><thead><tr><th></th><th>实际有缺陷</th><th>实际无缺陷</th></tr></thead><tbody>" +
          "<tr><td>检测为有缺陷</td><td>" + j.tp + " (TP)</td><td>" + j.fp + " (FP)</td></tr>" +
          "<tr><td>检测为无缺陷</td><td>" + j.fn + " (FN)</td><td>" + j.tn + " (TN)</td></tr></tbody></table>";
      }

      // 4) 数据来源说明
      html += "<p class='sample-note'>数据来源：n8n 官方 starter-kit 与 E2E 模板、Langfuse Studio 分组 demo、loomcycle 社区示例、Dify 官方示例 DSL（GitHub 公开仓库导出）；" +
        "负样本为在其上受控注入的 5+1 类缺陷。Coze 导出为付费功能，暂无公开样例。详细报告见 evaluation_report_real.md。</p>";
      samplesBody.innerHTML = html;
    }).catch(function () {
      samplesBody.innerHTML = "<p class='empty'>" + esc(t("loadError")) + "</p>";
    });
  }

  function openSamples() {
    samplesModal.classList.add("open");
    samplesModal.setAttribute("aria-hidden", "false");
    loadSamples();
  }
  function closeSamples() {
    samplesModal.classList.remove("open");
    samplesModal.setAttribute("aria-hidden", "true");
  }

  // ---------------------------------------------------------------------
  // Events
  // ---------------------------------------------------------------------
  function handleSend() {
    var text = promptEl.value.trim();
    if (!text) return;
    addMessage("user", "<p>" + esc(text) + "</p>");
    promptEl.value = "";
    if (awaitingClarify) { runClarify(text); }
    else { runGenerate(text); }
  }

  sendBtn.addEventListener("click", handleSend);
  promptEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
  });

  // Apply repair button (event delegation)
  document.addEventListener("click", function (e) {
    if (e.target && e.target.id === "applyRepairBtn") {
      var checked = document.querySelectorAll(".repair-option input:checked");
      var accepted = Array.prototype.map.call(checked, function (c) { return c.value; });
      if (!accepted.length) return;
      applyRepairs(accepted);
    }
  });

  function setDrawer(open) {
    var d = drawer;
    d.classList.toggle("open", open);
    d.setAttribute("aria-hidden", open ? "false" : "true");
  }

  document.getElementById("detailsButton").addEventListener("click", function () {
    setDrawer(!drawer.classList.contains("open"));
  });
  document.getElementById("closeDrawer").addEventListener("click", function () {
    setDrawer(false);
  });
  document.getElementById("samplesButton").addEventListener("click", openSamples);
  document.getElementById("closeSamples").addEventListener("click", closeSamples);
  samplesModal.addEventListener("click", function (e) {
    if (e.target === samplesModal) closeSamples();
  });
  document.querySelectorAll(".tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".tab").forEach(function (b) { b.classList.remove("active"); });
      document.querySelectorAll(".tab-content").forEach(function (c) { c.classList.remove("active"); });
      btn.classList.add("active");
      document.getElementById(btn.getAttribute("data-tab")).classList.add("active");
    });
  });

  document.getElementById("newChat").addEventListener("click", function () {
    current = null;
    awaitingRepair = awaitingClarify = false;
    chatEl.innerHTML = '<div class="message assistant"><div class="avatar">AI</div><div class="bubble"><small>' +
      esc(lang === "en" ? "VERIFLOW ASSISTANT" : "VERIFLOW 助手") +
      "</small><p>" + esc(t("intro")) + "</p></div></div>";
    renderSteps(null);
    renderReport(null, []);
    renderGraph(null);
    renderCpn(null);
    jsonCode.textContent = "—";
    document.getElementById("jsonStatus").textContent = "—";
  });

  // ---------------------------------------------------------------------
  // i18n
  // ---------------------------------------------------------------------
  function applyLang() {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      var k = el.getAttribute("data-i18n");
      if (t(k)) el.textContent = t(k);
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach(function (el) {
      var k = el.getAttribute("data-i18n-placeholder");
      if (t(k)) el.placeholder = t(k);
    });
    renderSteps(current ? current.steps : null);
    document.getElementById("languageButton").textContent = lang === "en" ? "中文 / EN" : "EN / 中文";
  }

  document.getElementById("languageButton").addEventListener("click", function () {
    lang = lang === "en" ? "zh" : "en";
    applyLang();
  });

  // init（mermaid 主题与默认中文）
  if (mermaidReady) {
    mermaid.initialize({
      startOnLoad: false,
      theme: "dark",
      securityLevel: "loose",
      flowchart: { curve: "basis", nodeSpacing: 42, rankSpacing: 56, useMaxWidth: true, htmlLabels: true }
    });
  }
  applyLang();
  renderSteps(null);
})();
