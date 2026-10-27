#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine/preview.py —— 把 sim.py 的干跑结果渲染成一个自包含的 HTML 预览。

它**不重新实现引擎**：直接 `import sim`，跑四个场景，把逐日状态塞进页面。
所以页面上的曲线永远和 `python engine/sim.py --table` 的数字一致。

用法：
    python engine/preview.py            # 生成 engine/preview.html
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
import sim  # noqa: E402

SCENARIOS = {
    "healthy": "健康回应",
    "neglect": "长期无回应",
    "abuse": "频繁否定",
    "mixed": "混合",
}
DAYS = 105

COLORS = {
    "SEEKING": "#f5a524",
    "FEAR": "#7c8cff",
    "RAGE": "#e5484d",
    "PANIC": "#a855f7",
    "CARE": "#46a758",
    "PLAY": "#ec4899",
    "LUST": "#8b8f98",
}


def collect() -> dict:
    """跑四个场景，返回逐日状态（不含判断层）。"""
    data = {}
    for name in SCENARIOS:
        y = sim.Yaml(ROOT / "state.md")
        person = sim.Persona(y)
        for _ in range(DAYS):
            person.step(sim.scenario_day(name, person.day))
        data[name] = [
            {
                "d": row["day"],
                "m": round(row["months"], 2),
                "e": {k: round(v, 3) for k, v in row["after"].items()},
                "load": round(row["load"], 3),
                "att": round(row["att"], 3),
                "tier": row["tier"],
                "ev": row["events"],
            }
            for row in person.log
        ]
    return data


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>another-me · 引擎 v0 干跑预览</title>
<style>
  :root{
    --bg:#f7f8fa; --panel:#ffffff; --ink:#14161a; --sub:#656c78; --line:#e3e6eb;
    --grid:#eef0f4; --accent:#4f6df5; --warn:#e5484d; --shadow:0 1px 2px rgba(16,20,30,.06),0 8px 24px rgba(16,20,30,.05);
  }
  [data-theme="dark"]{
    --bg:#0f1115; --panel:#16191f; --ink:#e8eaf0; --sub:#98a0ad; --line:#252a33;
    --grid:#1d222a; --accent:#7c8cff; --warn:#ff6b6b;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 30px rgba(0,0,0,.35);
  }
  *{box-sizing:border-box}
  body{
    margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",system-ui,sans-serif;
    -webkit-font-smoothing:antialiased;
  }
  .wrap{max-width:1080px;margin:0 auto;padding:28px 20px 64px}
  header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:22px}
  h1{font-size:20px;margin:0 0 6px;letter-spacing:.2px}
  .sub{color:var(--sub);font-size:13px;margin:0}
  .btn{
    border:1px solid var(--line);background:var(--panel);color:var(--ink);
    border-radius:8px;padding:6px 11px;font-size:13px;cursor:pointer;
  }
  .btn:hover{border-color:var(--accent)}
  .tabs{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0 10px}
  .tab{
    border:1px solid var(--line);background:var(--panel);color:var(--sub);
    border-radius:999px;padding:7px 14px;font-size:13.5px;cursor:pointer;transition:.15s;
  }
  .tab:hover{color:var(--ink)}
  .tab[aria-selected="true"]{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:500}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow)}
  .chartbox{padding:14px 14px 6px;margin-top:6px}
  svg{display:block;width:100%;height:auto;touch-action:none}
  .grid{stroke:var(--grid);stroke-width:1}
  .line{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round;vector-effect:non-scaling-stroke}
  .area{fill:var(--accent);opacity:.10}
  .axis{fill:var(--sub);font-size:11px}
  .marker{stroke:var(--ink);stroke-width:1;opacity:.45;vector-effect:non-scaling-stroke}
  .gate{stroke:var(--sub);stroke-width:1;stroke-dasharray:3 4;opacity:.55;vector-effect:non-scaling-stroke}
  .dot{stroke:var(--panel);stroke-width:1.5}
  .legend{display:flex;flex-wrap:wrap;gap:14px;padding:4px 8px 10px;font-size:12.5px;color:var(--sub)}
  .legend i{display:inline-block;width:10px;height:3px;border-radius:2px;margin-right:6px;vertical-align:2px}
  .scrub{display:flex;align-items:center;gap:14px;padding:0 18px 16px}
  input[type=range]{flex:1;accent-color:var(--accent)}
  .daynum{font-variant-numeric:tabular-nums;color:var(--sub);font-size:13px;min-width:132px;text-align:right}
  .grid2{display:grid;grid-template-columns:1.15fr .85fr;gap:16px;margin-top:16px}
  @media(max-width:820px){.grid2{grid-template-columns:1fr}}
  .card{padding:16px 18px}
  .card h2{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--sub);margin:0 0 12px;font-weight:600}
  .events{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px}
  .chip{border:1px solid var(--line);border-radius:7px;padding:4px 9px;font-size:12.5px;color:var(--sub)}
  .chip.neg{border-color:var(--warn);color:var(--warn)}
  .bar{display:grid;grid-template-columns:64px 1fr 46px;align-items:center;gap:10px;margin:5px 0;font-size:12.5px}
  .bar span:first-child{color:var(--sub)}
  .track{height:7px;border-radius:4px;background:var(--grid);overflow:hidden}
  .fill{height:100%;border-radius:4px;transition:width .12s linear}
  .val{text-align:right;font-variant-numeric:tabular-nums;color:var(--ink);opacity:.85}
  .kv{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px dashed var(--line);font-size:13.5px}
  .kv:last-child{border-bottom:0}
  .kv b{font-weight:600;font-variant-numeric:tabular-nums}
  .muted{color:var(--sub)}
  table{width:100%;border-collapse:collapse;font-size:13.5px;margin-top:6px}
  th,td{text-align:right;padding:8px 10px;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}
  th:first-child,td:first-child{text-align:left}
  th{color:var(--sub);font-weight:500;font-size:12.5px}
  .note{color:var(--sub);font-size:12.5px;line-height:1.7;margin:10px 0 0}
  footer{margin-top:26px;color:var(--sub);font-size:12.5px;line-height:1.8}
  code{background:var(--grid);padding:1px 5px;border-radius:4px;font-size:12px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>another-me · 引擎 v0 干跑</h1>
      <p class="sub">机制层由 <code>engine/sim.py</code> 推进（1 真实日 = 1 模拟周，105 天 ≈ 24 个月）。判断层不在这里。</p>
    </div>
    <button class="btn" id="theme">切换主题</button>
  </header>

  <div class="tabs" role="tablist" id="tabs"></div>

  <div class="panel chartbox">
    <svg id="chart" viewBox="0 0 1000 300" preserveAspectRatio="none" aria-label="情绪与负荷曲线"></svg>
    <div class="legend" id="legend"></div>
    <div class="scrub">
      <button class="btn" id="play">▶ 播放</button>
      <input type="range" id="range" min="0" max="104" value="104">
      <div class="daynum" id="daynum"></div>
    </div>
  </div>

  <div class="grid2">
    <div class="panel card">
      <h2>这一刻</h2>
      <div class="events" id="events"></div>
      <div id="bars"></div>
    </div>
    <div class="panel card">
      <h2>状态</h2>
      <div id="kv"></div>
    </div>
  </div>

  <div class="panel card" style="margin-top:16px">
    <h2>四个场景的终局（第 105 天）</h2>
    <table id="tbl"></table>
    <p class="note">第三行是这套机制最想跑出来的状态：<b>被否定不等于被抛弃</b>——依恋仍然安全，但 FEAR 基线和慢性负荷被抬上去。</p>
  </div>

  <footer>
    由 <code>python engine/preview.py</code> 生成，数据来自 <code>engine/sim.py</code>，页面本身不重算任何东西。<br>
    已知偏差：sim 不执行判断层（P1–P8 那些规则没有代码形态）；所有 <code>K_*</code> 是产品参数；
    依恋在 6 月前强制为 0；<b>没有随机性</b>，所以同一场景必然复现同一条轨迹。
  </footer>
</div>

<script>
const DATA = __DATA__;
const META = __META__;
const SYS = META.systems;
const COLORS = META.colors;
const NEG = new Set(["still","deny","leave"]);

let cur = "healthy";
const qsc = new URLSearchParams(location.search).get("sc");
if (qsc && DATA[qsc]) cur = qsc;
let idx = DATA[cur].length - 1;
let timer = null;

const $ = s => document.querySelector(s);

function rows(){ return DATA[cur]; }

function xAt(i, n, W, P){ return P + i * (W - 2*P) / (n - 1); }
function yAt(v, H, P){ return H - P - v * (H - 2*P); }

function drawChart(){
  const n = rows().length, W = 1000, H = 300, P = 38;
  const r = rows();
  let g = "";

  for (let k = 0; k <= 4; k++){
    const v = k / 4;
    const y = yAt(v, H, P);
    g += `<line class="grid" x1="${P}" x2="${W-P}" y1="${y}" y2="${y}"/>`;
    g += `<text class="axis" x="${P-9}" y="${y+4}" text-anchor="end">${v.toFixed(2)}</text>`;
  }
  for (let i = 0; i < n; i += 12){
    g += `<text class="axis" x="${xAt(i,n,W,P)}" y="${H-P+18}" text-anchor="middle">${r[i].d}</text>`;
  }

  const gate = r.findIndex(x => x.m >= 6);
  if (gate > 0){
    const gx = xAt(gate, n, W, P);
    g += `<line class="gate" x1="${gx.toFixed(1)}" x2="${gx.toFixed(1)}" y1="${P}" y2="${H-P}"/>`;
    g += `<text class="axis" x="${(gx + 7).toFixed(1)}" y="${P + 12}">6 月 · 依恋开始写入</text>`;
  }

  let area = r.map((row,i) => `${i ? "L" : "M"}${xAt(i,n,W,P).toFixed(1)},${yAt(row.load,H,P).toFixed(1)}`).join(" ");
  area += ` L${xAt(n-1,n,W,P).toFixed(1)},${H-P} L${xAt(0,n,W,P).toFixed(1)},${H-P} Z`;

  let lines = "";
  for (const s of SYS){
    const pts = r.map((row,i) => `${i ? "L" : "M"}${xAt(i,n,W,P).toFixed(1)},${yAt(row.e[s]||0,H,P).toFixed(1)}`).join(" ");
    lines += `<path class="line" stroke="${COLORS[s]}" d="${pts}"/>`;
  }

  const mx = xAt(idx, n, W, P).toFixed(1);
  let dots = "";
  for (const s of SYS){
    dots += `<circle class="dot" cx="${mx}" cy="${yAt(r[idx].e[s]||0,H,P).toFixed(1)}" r="3.2" fill="${COLORS[s]}"/>`;
  }

  $("#chart").innerHTML = `
    <path class="area" d="${area}"/>
    ${g}
    ${lines}
    <line class="marker" x1="${mx}" x2="${mx}" y1="${P}" y2="${H-P}"/>
    ${dots}`;
}

function attLabel(row){
  if (row.m < 6) return "未成形（6 月后才写入）";
  if (row.att < -0.15) return "不安全（回避-焦虑）";
  if (row.att > 0.15) return "安全";
  return "未成形";
}

function drawCard(){
  const row = rows()[idx];

  $("#events").innerHTML = row.ev
    .map(e => `<span class="chip ${NEG.has(e) ? "neg" : ""}">${META.events[e] || e}</span>`)
    .join("");

  $("#bars").innerHTML = SYS.concat(["LUST"]).filter(s => META.all.includes(s))
    .map(s => {
      const v = row.e[s] || 0;
      return `<div class="bar"><span>${s}</span>
        <div class="track"><div class="fill" style="width:${(v*100).toFixed(1)}%;background:${COLORS[s]}"></div></div>
        <span class="val">${v.toFixed(2)}</span></div>`;
    }).join("") +
    `<div class="bar" style="margin-top:10px"><span>负荷</span>
      <div class="track"><div class="fill" style="width:${(row.load*100).toFixed(1)}%;background:var(--accent)"></div></div>
      <span class="val">${row.load.toFixed(3)}</span></div>`;

  const tau = (1 + 0.9 * row.load).toFixed(2);
  const thr = (1 - 0.5 * row.load).toFixed(2);

  $("#kv").innerHTML = `
    <div class="kv"><span class="muted">依恋</span><b>${attLabel(row)}（${row.att >= 0 ? "+" : ""}${row.att.toFixed(2)}）</b></div>
    <div class="kv"><span class="muted">词表</span><b>${row.tier} · 可说 ${META.words[row.tier]} 个情绪词</b></div>
    <div class="kv"><span class="muted">恢复 τ</span><b>×${tau}</b></div>
    <div class="kv"><span class="muted">触发阈值</span><b>×${thr}</b></div>`;

  $("#daynum").textContent = `第 ${row.d} 天 · ${row.m.toFixed(1)} 月`;
  $("#range").value = idx;
  drawChart();
}

function drawTable(){
  const head = `<tr><th>场景</th><th>负荷</th><th>FEAR</th><th>RAGE</th><th>PANIC</th><th>CARE</th><th>依恋</th></tr>`;
  const body = Object.keys(DATA).map(k => {
    const r = DATA[k][DATA[k].length - 1];
    return `<tr><td>${META.scenarios[k]}</td><td>${r.load.toFixed(2)}</td>
      <td>${r.e.FEAR.toFixed(2)}</td><td>${r.e.RAGE.toFixed(2)}</td><td>${r.e.PANIC.toFixed(2)}</td>
      <td>${r.e.CARE.toFixed(2)}</td><td>${r.att >= 0 ? "+" : ""}${r.att.toFixed(2)}</td></tr>`;
  }).join("");
  $("#tbl").innerHTML = head + body;
}

function buildTabs(){
  $("#tabs").innerHTML = Object.keys(DATA).map(k =>
    `<button class="tab" role="tab" data-sc="${k}" aria-selected="${k===cur}">${META.scenarios[k]}</button>`
  ).join("");
  $("#tabs").querySelectorAll(".tab").forEach(btn => {
    btn.onclick = () => {
      cur = btn.dataset.sc;
      idx = rows().length - 1;
      $("#tabs").querySelectorAll(".tab").forEach(b => b.setAttribute("aria-selected", b === btn));
      drawCard();
    };
  });
}

$("#range").oninput = e => { idx = +e.target.value; drawCard(); };

$("#chart").addEventListener("pointermove", e => {
  const rect = e.target.getBoundingClientRect();
  const n = rows().length, P = 38;
  const rel = (e.clientX - rect.left) / rect.width * 1000;
  const i = Math.round((rel - P) / (1000 - 2*P) * (n - 1));
  idx = Math.max(0, Math.min(n - 1, i));
  drawCard();
});

$("#play").onclick = () => {
  if (timer) { clearInterval(timer); timer = null; $("#play").textContent = "▶ 播放"; return; }
  idx = 0; drawCard(); $("#play").textContent = "❚❚ 暂停";
  timer = setInterval(() => {
    if (idx >= rows().length - 1) { clearInterval(timer); timer = null; $("#play").textContent = "▶ 播放"; return; }
    idx++; drawCard();
  }, 70);
};

const themeBtn = $("#theme");
function setTheme(t){
  document.documentElement.dataset.theme = t;
  localStorage.setItem("am-theme", t);
}
themeBtn.onclick = () => {
  setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
};
setTheme(localStorage.getItem("am-theme") ||
  (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));

$("#legend").innerHTML = SYS.map(s => `<span><i style="background:${COLORS[s]}"></i>${s}</span>`).join("")
  + `<span><i style="background:var(--accent);opacity:.5"></i>慢性负荷（面积）</span>`;

$("#range").max = DATA.healthy.length - 1;
buildTabs();
drawCard();
drawTable();
</script>
</body>
</html>
"""


def main() -> int:
    data = collect()
    meta = {
        "systems": [s for s in sim.SYSTEMS if s != "LUST"],
        "all": list(sim.SYSTEMS),
        "colors": COLORS,
        "events": sim.EVENTS,
        "scenarios": SCENARIOS,
        "words": sim.EMOTION_WORDS,
    }
    html = (
        TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False))
        .replace("__META__", json.dumps(meta, ensure_ascii=False))
    )
    out = ROOT / "engine" / "preview.html"
    out.write_text(html, encoding="utf-8")
    print(f"已生成 {out}（{out.stat().st_size / 1024:.0f} KB，{DAYS} 天 × {len(SCENARIOS)} 场景）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
