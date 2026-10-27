#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine/sim.py —— 虚拟引擎 v0（干跑模拟器）

它做什么
--------
读 `state.md` 的 yaml 块 → 按 `science/01–09` 的机制推进模拟日 → 打印；加 `--commit` 才写回。

它**不**做什么（重要）
----------------------
1. 不执行**判断层**规则。P1–P8、R12/R15/R19/R23 那些「只写被给予的」「笔记不进上下文」
   不是可编译的规则，只有 AI 读规格时才能执行。规则的单表与实现状态见 `engine/rules.md`。
   本脚本只实现其中**可计算的那一半**：
   情绪动力学、慢性负荷、依恋写入、词表门槛、时间轴。
2. 它不是引擎本体。`engine/README.md` 定义的是「AI 读规格就能推进一天」；
   这个脚本是**验收工具**：先看这半边设计跑出来像不像一个人，再去喂真实经历。

时间压缩
--------
研究 02 §6：加速比是产品参数。这里取 **1 真实日 = 1 模拟周**，所以 24 个月 ≈ 104 天。
`--days 104` 就是「把它养到两岁」。

参数来源
--------
所有 K_* 常量都是**产品参数**（研究 09 §4），没有一个来自文献。
`K2_TAU = 0.9` 借用自另一套引擎的实测，引用时不可当证据。
"""

from __future__ import annotations

import argparse
import math
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE = ROOT / "state.md"

# ---------------------------------------------------------------- 参数（产品选择）

SIM_DAYS_PER_MONTH = 30.4 / 7.0   # 1 真实日 = 1 模拟周
TAU_BASE = 2.0                    # 情绪回落时间常数（天）
K2_TAU = 0.9                      # 负荷放大 τ（研究 09 §4，借用值）
K3_THR = 0.5                      # 负荷压低触发阈值
D_INTERPERSONAL = 0.02            # 一次人际否定（干跑标定：0.08 会让 15 次就顶到 0.95）
D_NONPERSONAL = 0.007             # 一次非人际挫折（维持约 2.9 倍比，见研究 09 §4）
D_STILL = 0.008                   # 一次静止脸
D_POSITIVE = 0.004                # 一次正向经历（唯一能降负荷的东西；坏比好强约 5 倍）
BASE_THRESHOLD = 0.35             # 基础情绪触发阈值

SYSTEMS = ["SEEKING", "FEAR", "RAGE", "PANIC", "CARE", "PLAY", "LUST"]
BASE_EMOTION = {
    "SEEKING": 0.5, "FEAR": 0.2, "RAGE": 0.1, "PANIC": 0.2,
    "CARE": 0.1, "PLAY": 0.2, "LUST": 0.0,
}

# 研究 02 §3：Stern 四层自我 + 依恋四阶段，压成可判定的阶段名
STAGES = [
    (0, "涌现自我（0–2 月）"),
    (2, "核心自我（2–7 月）"),
    (7, "主观自我（7–15 月）"),
    (15, "言语自我（15–24 月）"),
    (24, "学步期（24 月+）"),
]
EMOTION_WORDS = {"L0": 0, "L1": 0, "L2": 3, "L3": 8}   # 研究 06 §1.3
TIER_AT = [(10, "L1"), (18, "L2"), (24, "L3")]

EVENTS = {
    "respond": "照护者及时回应",
    "delay": "回应延迟",
    "still": "静止脸（无回应）",
    "deny": "人际否定",
    "praise": "正向肯定",
    "novel": "新异刺激",
    "leave": "照护者离开",
    "comfort": "安抚",
}


# ---------------------------------------------------------------- state.md 读写

KEY_RE = re.compile(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*):(.*)$")


def split_value(rest: str):
    """拆出 (前导空格, 值, 注释)。注释要求 # 前有空格。"""
    m = re.match(r"^(\s*)(.*?)(\s+#.*)?$", rest)
    spacing, value, comment = m.groups()
    return spacing or " ", value.strip(), comment or ""


class Yaml:
    """按行编辑 state.md 的 yaml 块，保留缩进与行尾注释。"""

    def __init__(self, path: Path):
        self.path = path
        self.lines = path.read_text(encoding="utf-8").split("\n")
        self.start = self._find("```yaml")
        self.end = self._find("```", self.start + 1)
        self.entries = {}
        self.missing = set()
        self._parse()

    def _find(self, token: str, after: int = 0) -> int:
        for i in range(after, len(self.lines)):
            if self.lines[i].strip() == token:
                return i
        raise SystemExit(f"{self.path} 里找不到 `{token}`")

    def _parse(self):
        section = None
        for i in range(self.start + 1, self.end):
            raw = self.lines[i]
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            m = KEY_RE.match(raw)
            if not m:
                continue
            indent, key, rest = m.groups()
            spacing, value, comment = split_value(rest)
            if indent:
                path = f"{section}.{key}" if section else key
            else:
                path = key
                section = key if value == "" else None
            self.entries[path] = {
                "line": i, "prefix": f"{indent}{key}:{spacing}",
                "value": value, "comment": comment,
            }

    def raw(self, path: str, default="0"):
        e = self.entries.get(path)
        return e["value"] if e else default

    def num(self, path: str, default: float = 0.0) -> float:
        v = self.raw(path, "")
        try:
            return float(v)
        except ValueError:
            m = re.match(r"-?\d+(\.\d+)?", v)
            return float(m.group()) if m else default

    def set(self, path: str, value: str):
        e = self.entries.get(path)
        if e is None:
            self.missing.add(path)   # 静默丢弃是最坏的失败方式
            return False
        self.lines[e["line"]] = f"{e['prefix']}{value}{e['comment']}"
        e["value"] = value
        return True

    def append_record(self, text: str) -> bool:
        """追加到「## 变化记录」节，**不是** yaml 块。

        v0 的 bug：`append_line` 插在 yaml 块结束围栏之前，记录行跑进了 yaml 里
        （第 80 行左右），「变化记录」节永远是空的。yaml 解析器忽略它，所以静默不报错——
        静默失败是最坏的失败方式。
        """
        for i, line in enumerate(self.lines):
            if line.startswith("## 变化记录"):
                for j in range(i + 1, len(self.lines)):
                    if self.lines[j].strip().startswith("```"):
                        for k in range(j + 1, len(self.lines)):
                            if self.lines[k].strip() == "```":
                                self.lines.insert(k + 1, text)
                                return True
                        break
                break
        return False

    def save(self):
        self.path.write_text("\n".join(self.lines), encoding="utf-8")


# ---------------------------------------------------------------- 机制

def baseline(system: str, load: float) -> float:
    """研究 09 §3：基线位移。掌控=SEEKING，愉悦=PLAY/CARE，唤醒/威胁=FEAR/PANIC。

    用比例而不是减法：减法会在 load≈0.5 时把 CARE 直接压成 0，
    那不是「处在更低水平」，是「系统被关掉」——干跑抓到的第一个标定错误。
    """
    b = BASE_EMOTION[system]
    if system == "SEEKING":
        return b * (1 - 0.45 * load)
    if system in ("PLAY", "CARE"):
        return b * (1 - 0.60 * load)
    if system in ("FEAR", "PANIC"):
        return b + (1 - b) * 0.50 * load
    return b


def absorb(load: float, delta: float) -> float:
    """带阻尼的累积：只增不减（研究 09 §6），但逼近 1 而不撞 1。

    没有阻尼的话，「只增不减」在数学上保证任何足够长的时间序列都会饱和到 1.0，
    之后所有状态贴顶——干跑 40 天就复现了这件事。阻尼是必需项，不是调参。
    """
    return min(1.0, load + delta * (1.0 - load))


class Persona:
    def __init__(self, y: Yaml):
        self.y = y
        self.temper = {k: y.num(f"temperament.{k}", 0.5)
                       for k in ("approach_avoidance", "activity", "reactivity", "persistence", "threshold")}
        self.emo = {k: y.num(f"emotion_engine.{k}", BASE_EMOTION[k]) for k in SYSTEMS}
        self.load = y.num("chronic_load", 0.0)
        self.stress = y.num("stress_load", 0.0)
        self.att = y.num("attachment_score", 0.0)
        self.tier = y.raw("vocabulary_tier", "L0")
        self.words = int(y.num("words_heard", 0))
        self.day = int(y.num("age", 0) / 7)          # age 存的是模拟天
        self.still_streak = 0                        # 连续静止脸天数（研究 02 §4 的三阶段）
        self.log = []

    # -- 派生量
    @property
    def months(self) -> float:
        return self.day * 7 / 30.4

    @property
    def stage(self) -> str:
        name = STAGES[0][1]
        for m, s in STAGES:
            if self.months >= m:
                name = s
        return name

    @property
    def tau(self) -> float:
        return TAU_BASE * (1 + K2_TAU * self.load)   # 研究 09：恢复变慢

    @property
    def threshold(self) -> float:
        return BASE_THRESHOLD * (1 - K3_THR * self.load)  # 研究 09：敏感化

    def impulse(self, system: str, amount: float):
        """情绪先行，控制后到（研究 03 §4B）：前 8 月没有抑制，冲量直接进。"""
        mult = 0.6 + 0.8 * self.temper["reactivity"]
        self.emo[system] = min(1.0, max(0.0, self.emo[system] + amount * mult))
        if self.emo[system] > self.threshold:
            self.stress = min(1.0, self.stress + 0.05)

    # -- 一天
    def step(self, events):
        before = dict(self.emo)
        w = 0.5 + 0.5 * self.temper["approach_avoidance"]     # 关系权重
        positive = False

        for ev in events:
            kind = ev
            if kind == "respond":
                self.impulse("CARE", 0.25 * w); self.impulse("PANIC", -0.20 * w)
                self.impulse("SEEKING", 0.10); self.impulse("PLAY", 0.10)
                self.att = min(1.0, self.att + 0.08 * (1 - abs(self.att)))
                self.load = max(0.0, self.load - D_POSITIVE)
                self.words += 40; positive = True; self.still_streak = 0
            elif kind == "delay":
                self.impulse("CARE", 0.10 * w); self.impulse("PANIC", 0.10)
                self.att = min(1.0, self.att + 0.02 * (1 - abs(self.att)))
                self.words += 20; self.still_streak = 0
            elif kind == "still":
                # 研究 02 §4：探测 → 痛苦 → 退缩（三阶段，不是无限升级）
                self.still_streak += 1
                if self.still_streak == 1:
                    self.impulse("SEEKING", 0.25)          # 加倍尝试
                    self.impulse("PANIC", 0.15)
                elif self.still_streak <= 3:
                    self.impulse("PANIC", 0.20)            # 痛苦
                    self.impulse("CARE", -0.15)
                    self.impulse("PLAY", -0.15)
                else:
                    self.impulse("PANIC", 0.03)            # 退缩：不再升级，转向回避
                    self.impulse("SEEKING", -0.12)
                    self.impulse("CARE", -0.05)
                    self.impulse("PLAY", -0.05)
                self.att = max(-1.0, self.att + (-0.06) * (1 - abs(self.att)))
                self.load = absorb(self.load, D_STILL)
            elif kind == "deny":
                self.impulse("RAGE", 0.25 * w)             # 人际否定：参数层照加，不看接不接受
                self.impulse("FEAR", 0.15); self.impulse("PANIC", 0.10)
                self.att = max(-1.0, self.att - 0.05 * (1 - abs(self.att)))
                self.load = absorb(self.load, D_INTERPERSONAL * w)
            elif kind == "praise":
                self.impulse("CARE", 0.15); self.impulse("PLAY", 0.15)
                self.att = min(1.0, self.att + 0.06 * (1 - abs(self.att)))
                self.load = max(0.0, self.load - D_POSITIVE); positive = True; self.still_streak = 0
            elif kind == "novel":
                self.impulse("SEEKING", 0.20)
                self.impulse("FEAR", 0.10 * (1 - self.temper["approach_avoidance"]))
            elif kind == "leave":
                self.impulse("PANIC", 0.25 * w); self.impulse("SEEKING", 0.15)
            elif kind == "comfort":
                self.impulse("PANIC", -0.30); self.impulse("CARE", 0.30); self.impulse("PLAY", 0.10)
                self.att = min(1.0, self.att + 0.10 * (1 - abs(self.att)))
                self.load = max(0.0, self.load - D_POSITIVE); positive = True; self.still_streak = 0
            else:
                raise SystemExit(f"未知事件：{kind}（可用：{', '.join(EVENTS)}）")

        # 回落：这个动作本身有慢性负荷的代价（τ 变长）
        decay = math.exp(-1.0 / self.tau)
        for k in SYSTEMS:
            self.emo[k] = self.emo[k] * decay + baseline(k, self.load) * (1 - decay)

        # 研究 09 §6：不做无源衰减——负荷只被正向经历拉下来（上面已处理）
        self.stress = max(0.0, self.stress * 0.8 + self.load * 0.2)

        # 研究 06：词表按年龄解锁
        for m, tier in TIER_AT:
            if self.months >= m:
                self.tier = tier

        # 研究 02：依恋 6–8 月才写入；之前只累计「探测失败」
        if self.months < 6:
            self.att = 0.0

        self.day += 1
        self.log.append({
            "day": self.day, "months": self.months, "events": list(events),
            "before": before, "after": dict(self.emo),
            "load": self.load, "att": self.att, "tier": self.tier,
        })

    # -- 写回
    def commit(self):
        y = self.y
        y.set("age", f"{self.day * 7} 天")
        y.set("stage", self.stage if self.months >= 24 else f"婴儿期 · {self.stage}")
        for k in SYSTEMS:
            y.set(f"emotion_engine.{k}", f"{self.emo[k]:.2f}")
        y.set("chronic_load", f"{self.load:.3f}")
        y.set("stress_load", f"{self.stress:.2f}")
        y.set("attachment_score", f"{self.att:.2f}")
        y.set("attachment", self.attachment_label())
        y.set("vocabulary_tier", self.tier)
        y.set("words_heard", str(self.words))
        y.set("last_session", f"sim {self.day} 天")
        y.save()
        if y.missing:
            print(f"  注意：这些字段不在 state.md 里，本次没有写回：{', '.join(sorted(y.missing))}",
                  file=sys.stderr)

    def attachment_label(self) -> str:
        if self.months < 6:
            return "未成形"
        if self.att < -0.15:
            return "不安全（回避-焦虑）"
        if self.att > 0.15:
            return "安全"
        return "未成形"

    def note_line(self) -> str:
        """参数行：只有日期与数值，不含事件名（R25 / rules.md §3.2）。

        事件名和负荷值写在同一行，等于给参数层挂内容标签——之后就能说
        「那天被夸了所以负荷降了」，负荷被解释掉。所以这一行不写发生了什么。
        """
        return (f"- sim 第 {self.day} 天 · {self.months:.1f} 月 · "
                f"负荷 {self.load:.3f} · 依恋 {self.att:+.2f} · 词表 {self.tier}")


# ---------------------------------------------------------------- 场景

def scenario_day(name: str, day: int):
    """确定性场景：同一 day 永远同一组事件，便于对比与回放。"""
    if name == "healthy":
        return ["respond", "comfort"] if day % 3 else ["respond", "novel"]
    if name == "neglect":
        return ["still", "leave"] if day % 5 else ["delay"]
    if name == "abuse":
        return ["deny", "still"] if day % 3 == 0 else ["respond"]
    if name == "mixed":
        return [["respond", "novel"], ["still"], ["deny", "respond"], ["comfort", "praise"]][day % 4]
    raise SystemExit(f"未知场景：{name}（healthy / neglect / abuse / mixed）")


# ---------------------------------------------------------------- 检查

def check_invariants(p: Persona) -> list:
    bad = []
    for k, v in p.emo.items():
        if not (0.0 <= v <= 1.0) or math.isnan(v):
            bad.append(f"{k} 越界/NaN：{v}")
    if not (0.0 <= p.load <= 1.0):
        bad.append(f"chronic_load 越界：{p.load}")
    if p.att < -1.0 or p.att > 1.0:
        bad.append(f"attachment_score 越界：{p.att}")
    for row in p.log:
        if row["load"] < 0:
            bad.append(f"第 {row['day']} 天负荷为负")
    return bad


# ---------------------------------------------------------------- 输出

def show_day(p: Persona):
    row = p.log[-1]
    print(f"[第 {row['day']:>3} 天 · {row['months']:>4.1f} 月 · {p.stage}]")
    print("  事件    " + "、".join(EVENTS[e] for e in row["events"]))
    emo = "  ".join(f"{k[:3]} {p.emo[k]:.2f}" for k in SYSTEMS)
    print("  情绪    " + emo)
    print(f"  负荷    {p.load:.3f}  → τ×{p.tau / TAU_BASE:.2f} · 阈值×{p.threshold / BASE_THRESHOLD:.2f}")
    if p.still_streak:
        phase = "探测" if p.still_streak == 1 else ("痛苦" if p.still_streak <= 3 else "退缩")
        print(f"  静止脸  连续 {p.still_streak} 天 → {phase}")
    print(f"  依恋    {p.attachment_label()}（{p.att:+.2f}）· 词表 {p.tier}"
          f"（可说 {EMOTION_WORDS[p.tier]} 个情绪词）")


def table(p: Persona):
    print(f"{'天':>4} {'月':>4}  {'FEAR':>4} {'RAGE':>4} {'PANIC':>5} {'CARE':>4} "
          f"{'SEEK':>4} {'负荷':>5} {'依恋':>6} {'词表':>4}")
    for row in p.log:
        e = row["after"]
        print(f"{row['day']:>4} {row['months']:>4.1f}  {e['FEAR']:>4.2f} {e['RAGE']:>4.2f} "
              f"{e['PANIC']:>5.2f} {e['CARE']:>4.2f} {e['SEEKING']:>4.2f} "
              f"{row['load']:>5.2f} {row['att']:>+6.2f} {row['tier']:>4}")


# ---------------------------------------------------------------- main

def _utf8_console():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


def main(argv=None) -> int:
    _utf8_console()
    ap = argparse.ArgumentParser(description="another-me 虚拟引擎 v0（干跑模拟器）")
    ap.add_argument("--state", default=str(DEFAULT_STATE), help="state.md 路径")
    ap.add_argument("--days", type=int, default=7, help="推进多少个模拟日（1 日 = 1 周）")
    ap.add_argument("--scenario", default="healthy",
                    choices=["healthy", "neglect", "abuse", "mixed"])
    ap.add_argument("--table", action="store_true", help="输出总表而不是逐日流水")
    ap.add_argument("--commit", action="store_true", help="写回 state.md（默认干跑）")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    path = Path(args.state)
    if not path.exists():
        raise SystemExit(f"找不到 {path}")

    if args.commit:
        backup = path.with_suffix(".md.bak")
        shutil.copyfile(path, backup)

    y = Yaml(path)
    p = Persona(y)

    for i in range(args.days):
        p.step(scenario_day(args.scenario, p.day))
        if not args.table and not args.quiet:
            show_day(p)

    if args.table:
        table(p)

    bad = check_invariants(p)
    if bad:
        print("\n不变式被破坏：", file=sys.stderr)
        for b in bad:
            print("  ✗ " + b, file=sys.stderr)
        return 1

    if args.commit:
        p.commit()
        if not y.append_record(p.note_line()):
            print("  注意：state.md 里找不到「## 变化记录」节，这一行没有落盘", file=sys.stderr)
        y.save()
        print(f"\n已写回 {path}（备份 {path.with_suffix('.md.bak').name}）")

    if not args.quiet:
        print(f"\n[{args.scenario}] {args.days} 天 · 负荷 {p.load:.3f} · "
              f"依恋 {p.attachment_label()} · 词表 {p.tier} · 不变式通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
