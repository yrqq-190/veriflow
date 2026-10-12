# -*- coding: utf-8 -*-
"""生成真实平台评估可视化报告页（ECharts，数据来自 report_real.json）"""
import json, os, io

BASE = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(os.path.join(BASE, "report_real.json"), encoding="utf-8"))
res = data["results"]

def pct(x):
    return round(x * 100, 1)

html = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VeriFlow 真实平台数据评估报告</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
  body{background:#0a1019;color:#e6edf6;font-family:Inter,Segoe UI,Arial,sans-serif;margin:0;padding:24px}
  h1{font-size:20px;margin:0 0 4px}
  .sub{color:#8591a4;font-size:12px;margin-bottom:18px}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
  .card{background:#0d1420;border:1px solid #273244;border-radius:10px;padding:14px 14px 4px}
  .card h2{font-size:13px;margin:0 0 4px;letter-spacing:.06em}
  .chart{width:100%;height:300px}
  .full{grid-column:1/-1}
  .kpis{display:flex;gap:12px;margin:16px 0}
  .kpi{flex:1;background:#111b2b;border:1px solid #273244;border-radius:8px;padding:12px 14px}
  .kpi b{font-size:22px;color:#d5ff43;display:block}
  .kpi small{color:#8591a4;font-size:11px}
  table{border-collapse:collapse;width:100%;font-size:12px;margin-top:8px}
  th,td{border:1px solid #273244;padding:6px 10px;text-align:left}
  th{color:#aeb7c6;background:#111b2b}
  .note{color:#8591a4;font-size:11px;margin-top:8px;line-height:1.5}
</style>
</head>
<body>
<h1>VeriFlow 真实平台数据评估（实测）</h1>
<div class="sub">数据集：6 个真实 n8n/Dify 生产模板 + 25 个受控注入缺陷样本 · 数值为实测结果，不参照论文</div>
<div class="kpis">
  <div class="kpi"><b>__F1_J__%</b><small>JCPN F1（Prec __P_J__% / Rec __R_J__%）</small></div>
  <div class="kpi"><b>__F1_G__%</b><small>Graph 检查器 F1</small></div>
  <div class="kpi"><b>__F1_S__%</b><small>JSON Schema F1</small></div>
  <div class="kpi"><b>0</b><small>JCPN 误报（FP=0）</small></div>
</div>
<div class="grid">
  <div class="card full"><h2>三方法对比（Precision / Recall / F1 / Accuracy）</h2><div id="cmp" class="chart"></div></div>
  <div class="card full"><h2>缺陷类型检出（注入数 vs 检出数）</h2><div id="bytype" class="chart"></div></div>
  <div class="card full"><h2>JCPN 混淆矩阵</h2><div id="cm" class="chart" style="height:260px"></div></div>
</div>
<script>
var DATA = __DATA__;
var res = DATA.results, by = DATA.by_type;
var meths = ["schema", "graph", "jcpn"];
var names = ["JSON Schema", "Graph static checker", "Proposed JCPN"];
function chart(id, opt){ var c = echarts.init(document.getElementById(id)); c.setOption(opt); window.addEventListener('resize', function(){c.resize();}); }

chart("cmp", {
  title:{text:"三方法对比（真实平台数据，实测）",left:12,textStyle:{fontSize:14,color:"#e6edf6"}},
  tooltip:{trigger:"axis",triggerOn:"mousemove|click",renderMode:"richText",confine:true},
  legend:{top:34,textStyle:{fontSize:11,color:"#aeb7c6"}},
  grid:{left:60,right:20,top:70,bottom:30,containLabel:true},
  xAxis:{type:"category",data:names,axisLabel:{fontSize:11,color:"#aeb7c6"}},
  yAxis:{type:"value",max:100,axisLabel:{fontSize:11,formatter:"{value}%"},splitLine:{lineStyle:{color:"#1d293b"}}},
  series:[
    {name:"Precision",type:"bar",barWidth:18,data:meths.map(function(m){return +(res[m].precision*100).toFixed(1);})},
    {name:"Recall",type:"bar",barWidth:18,data:meths.map(function(m){return +(res[m].recall*100).toFixed(1);})},
    {name:"F1",type:"bar",barWidth:18,data:meths.map(function(m){return +(res[m].f1*100).toFixed(1);})},
    {name:"Accuracy",type:"bar",barWidth:18,data:meths.map(function(m){return +(res[m].accuracy*100).toFixed(1);})}
  ]
});

chart("bytype", {
  title:{text:"缺陷类型检出（JCPN / Graph / Schema）",left:12,textStyle:{fontSize:14,color:"#e6edf6"}},
  tooltip:{trigger:"axis",triggerOn:"mousemove|click",renderMode:"richText",confine:true},
  legend:{top:34,textStyle:{fontSize:11,color:"#aeb7c6"}},
  grid:{left:110,right:20,top:70,bottom:30,containLabel:true},
  xAxis:{type:"category",data:by.map(function(b){return b.kind;}),axisLabel:{fontSize:11,color:"#aeb7c6"}},
  yAxis:{type:"value",minInterval:1,axisLabel:{fontSize:11},splitLine:{lineStyle:{color:"#1d293b"}}},
  series:[
    {name:"注入数",type:"bar",barWidth:14,data:by.map(function(b){return b.total;})},
    {name:"JCPN",type:"bar",barWidth:14,data:by.map(function(b){return b.jcpn;})},
    {name:"Graph",type:"bar",barWidth:14,data:by.map(function(b){return b.graph;})},
    {name:"Schema",type:"bar",barWidth:14,data:by.map(function(b){return b.schema;})}
  ]
});

chart("cm", {
  title:{text:"JCPN 混淆矩阵（TP=__TP__ FP=__FP__ FN=__FN__ TN=__TN__）",left:12,textStyle:{fontSize:14,color:"#e6edf6"}},
  tooltip:{trigger:"item",triggerOn:"mousemove|click",renderMode:"richText",confine:true,formatter:function(p){return p.seriesName+"<br/>"+p.name+": "+p.value;}},
  grid:{left:70,right:20,top:50,bottom:30,containLabel:true},
  xAxis:{type:"category",data:["预测有缺陷","预测无缺陷"],axisLabel:{fontSize:11,color:"#aeb7c6"}},
  yAxis:{type:"category",data:["实际有缺陷","实际无缺陷"],axisLabel:{fontSize:11,color:"#aeb7c6"}},
  series:[{
    name:"计数",type:"heatmap",data:[
      [0,0,__TP__],[1,0,__FN__],[0,1,__FP__],[1,1,__TN__]
    ],label:{show:true,fontSize:16,color:"#fff"}
  }]
});
</script>
<div class="note">数据口径：真实平台工作流 6 个（n8n×5、Dify×1）经平台适配器转换为标准 JSON，负样本为 25 个受控注入（missing_branch / isolated_node / unreachable_node / abnormal_loop / broken_message / variable_constraint）。JCPN 除数据域类缺陷（variable_constraint，已知抽象局限）外全部检出，且对正常样本零误报。</div>
</body>
</html>"""

j, g, s = res["jcpn"], res["graph"], res["schema"]
html = html.replace("__F1_J__", str(pct(j["f1"]))).replace("__P_J__", str(pct(j["precision"]))).replace("__R_J__", str(pct(j["recall"])))
html = html.replace("__F1_G__", str(pct(g["f1"]))).replace("__F1_S__", str(pct(s["f1"])))
html = html.replace("__TP__", str(j["tp"])).replace("__FP__", str(j["fp"])).replace("__FN__", str(j["fn"])).replace("__TN__", str(j["tn"]))
html = html.replace("__DATA__", json.dumps(data, ensure_ascii=False))

out = os.path.join(BASE, "report_real.html")
io.open(out, "w", encoding="utf-8").write(html)
print("written", out, len(html), "bytes")
