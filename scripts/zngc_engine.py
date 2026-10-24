# -*- coding: utf-8 -*-
"""智能工厂研判引擎：只用 Python 标准库，兼容 3.8+。

输入：企业情况（dict，格式见 SKILL.md“输入格式”）
输出：四个层级的研判结果、场景盘点、AI场景比例、指标计算、风险提示、时间倒排
所有“缺口”都区分为：已确认的缺口（miss） / 待证（unknown，信息没给或证据未坐实）。
"""
import datetime as _dt
import json
import math
import re

import zngc_rules as R

SC = R.scenario_by_id()
YES = {True, "是", "有", "yes", "y", "true", "1", "已", "对", "√"}
NO = {False, "否", "无", "没有", "no", "n", "false", "0", "×", "不是"}


# ---------------------------------------------------------------- 输入整理
def tri(v):
    """三值：True / False / None（不知道）。"""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in {str(x).lower() for x in YES}:
        return True
    if s in {str(x).lower() for x in NO}:
        return False
    return None


CN_NUM = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5}


def num(v):
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("，", "").replace("%", "").strip()
    m = re.search(r"-?\d+(\.\d+)?", s)
    if m:
        return float(m.group(0))
    m = re.match(r"^([零一二两三四五])(级)?$", s)
    return float(CN_NUM[m.group(1)]) if m else None


def enum_value(item, v):
    """枚举项既可填序号，也可填选项文字。"""
    n = num(v)
    if n is not None:
        return n
    s = str(v).strip()
    for i, opt in enumerate(item.get("options") or []):
        if s and (s == opt or s in opt or opt.startswith(s)):
            return float(i)
    return None


def load_input(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return json.loads(raw.decode(enc))
        except (UnicodeDecodeError, ValueError):
            continue
    raise ValueError("读不懂这个输入文件：请确认是 UTF-8 编码的 JSON")


def normalize(inp):
    inp = dict(inp or {})
    g = dict(inp.get("gates") or {})
    gates = {}
    for item in R.GATES:
        gates[item["key"]] = tri(g.get(item["key"]))
    gates["cmmm_level"] = int(num(g.get("cmmm_level"))) if num(g.get("cmmm_level")) is not None else None
    gates["cmmm_score"] = num(g.get("cmmm_score"))
    gates["cmmm_source"] = g.get("cmmm_source") or ""
    cl = str(g.get("current_level") or "").strip()
    gates["current_level_known"] = bool(cl)
    gates["current_level"] = cl if cl in R.LEVELS else "无"
    gates["current_level_date"] = str(g.get("current_level_date") or "").strip()
    if gates["cmmm_level"] is None and gates["cmmm_score"] is not None:
        gates["cmmm_level"] = cmmm_level_from_score(gates["cmmm_score"])

    scs = []
    for raw in inp.get("scenarios") or []:
        sid = int(num(raw.get("id")) or 0)
        if sid not in SC:
            continue
        types = raw.get("ai_types") or []
        if isinstance(types, str):
            types = [t for t in re.split(r"[、,，;；/\s]+", types) if t]
        ai = tri(raw.get("ai"))
        if ai is None and types:
            ai = True
        sc = {
            "id": sid, "scene": SC[sid]["name"], "seg": SC[sid]["seg"], "guide": SC[sid]["guide"],
            "name": raw.get("name") or SC[sid]["name"], "systems": raw.get("systems") or "",
            "inuse": tri(raw.get("inuse")) is not False,  # 列出来默认就是在用
            "linked": tri(raw.get("linked")) is True,
            "model": tri(raw.get("model")) is True,
            "quantified": tri(raw.get("quantified")) is True,
            "ai": ai is True, "ai_types": types,
            "months": num(raw.get("months")),
            "confirmed": tri(raw.get("confirmed")) is not False,
            "declare": tri(raw.get("declare")) is not False,
            "evidence": raw.get("evidence") or "",
        }
        sc["grade"] = grade(sc)
        scs.append(sc)

    ex = {}
    src = inp.get("extras") or {}
    for item in R.EXTRAS:
        v = src.get(item["key"])
        if item["type"] == "bool":
            ex[item["key"]] = tri(v)
        elif item["type"] == "enum":
            ex[item["key"]] = None if v is None or v == "" else enum_value(item, v)
        else:
            ex[item["key"]] = None if v is None or v == "" else num(v)

    kp = []
    for k in inp.get("kpis") or []:
        if not k or not k.get("name"):
            continue
        kp.append(k)

    loc = {}
    for k, v in (inp.get("local") or {}).items():
        loc[k] = tri(v)

    return {
        "company": dict(inp.get("company") or {}), "gates": gates, "scenarios": scs, "extras": ex, "local": loc,
        "kpis": kp, "investment": dict(inp.get("investment") or {}),
        "target": inp.get("target") or "auto", "overrides": dict(inp.get("overrides") or {}),
    }


def grade(sc):
    if not sc["inuse"]:
        return "未建"
    if sc["linked"] and sc["model"] and sc["quantified"]:
        return "A"
    if sc["linked"] and sc["model"]:
        return "B"
    if sc["linked"] or sc["model"]:
        return "C"
    return "D"


def cmmm_level_from_score(score):
    for low, lv in R.CMMM_SCORE_BANDS:
        if score >= low - 1e-9:
            return lv
    return 0


def ge(grade_a, grade_b):
    return R.GRADE_ORDER.get(grade_a, 0) >= R.GRADE_ORDER.get(grade_b, 0)


# ---------------------------------------------------------------- 三值判定
def _ai_ok(sc, need):
    if not need:
        return True
    if not sc["ai"]:
        return False
    return need == "any" or need in sc["ai_types"]


def eval_map(m, d):
    """返回 (state, by)；state ∈ hit / miss / unknown。"""
    if "any" in m:
        states = [eval_map(x, d) for x in m["any"]]
        hits = [b for s, b in states if s == "hit"]
        if hits:
            return "hit", hits[0]
        if any(s == "unknown" for s, _ in states):
            return "unknown", next(b for s, b in states if s == "unknown")
        return "miss", ""
    if "all" in m:
        states = [eval_map(x, d) for x in m["all"]]
        if any(s == "miss" for s, _ in states):
            return "miss", ""
        if any(s == "unknown" for s, _ in states):
            return "unknown", "；".join(b for _, b in states if b)
        return "hit", "；".join(b for _, b in states if b)
    if "s" in m:
        need_n = m.get("n", 1)
        sure, maybe = [], []
        for sc in d["scenarios"]:
            if sc["id"] in m["s"] and ge(sc["grade"], m["g"]) and _ai_ok(sc, m.get("ai")):
                (sure if sc["confirmed"] else maybe).append(sc)
        if len(sure) >= need_n:
            return "hit", "、".join("%d号%s(%s级)" % (s["id"], s["name"], s["grade"]) for s in sure[:4])
        if len(sure) + len(maybe) >= need_n:
            return "unknown", "待证：" + "、".join("%d号%s" % (s["id"], s["name"]) for s in maybe[:4])
        return "miss", ""
    if "x" in m:
        v = d["extras"].get(m["x"])
        if v is None:
            return "unknown", "未填写：" + extra_q(m["x"])
        if isinstance(v, bool):
            ok = v
        else:
            ok = v >= m.get("ge", 1)
        return ("hit", extra_q(m["x"])) if ok else ("miss", "")
    if "gate" in m:
        v = d["gates"].get(m["gate"])
        if v is None:
            return "unknown", "未确认：" + gate_q(m["gate"])
        return ("hit", gate_q(m["gate"])) if v else ("miss", "")
    return "unknown", ""


def extra_q(key):
    for e in R.EXTRAS:
        if e["key"] == key:
            return e["q"]
    return key


def gate_q(key):
    for g in R.GATES:
        if g["key"] == key:
            return g.get("req") or g["q"]
    return key


def fix_hint(m):
    """缺口的补法：由映射自动生成。"""
    if "any" in m:
        return " 或 ".join(fix_hint(x) for x in m["any"])
    if "all" in m:
        return " 并且 ".join(fix_hint(x) for x in m["all"])
    if "s" in m:
        names = "、".join("%d号%s" % (i, SC[i]["name"]) for i in m["s"][:4])
        tail = "等" if len(m["s"]) > 4 else ""
        n = m.get("n", 1)
        cnt = ("中至少%d个" % n) if n > 1 else ""
        ai = ""
        if m.get("ai") == "any":
            ai = "并应用AI"
        elif m.get("ai"):
            ai = "并应用" + m["ai"]
        return "把%s%s%s做到%s级及以上%s" % (names, tail, cnt, m["g"], ai)
    if "x" in m:
        item = next((e for e in R.EXTRAS if e["key"] == m["x"]), None)
        if item and item["type"] == "enum" and m.get("ge"):
            return "补齐：%s（达到“%s”）" % (item["q"], item["options"][int(m["ge"])])
        if item and item["type"] == "int":
            return "补齐：%s ≥ %d" % (item["q"], int(m.get("ge", 1)))
        return "补齐：" + extra_q(m["x"])
    if "gate" in m:
        return "补齐：" + gate_q(m["gate"])
    return ""


# ---------------------------------------------------------------- AI场景比例
def ai_stats(d, pool="confirmed"):
    scs = [s for s in d["scenarios"] if s["grade"] != "未建" and s["declare"] and (pool == "all" or s["confirmed"])]
    n = len(scs)
    ai_inst = [s for s in scs if s["ai"] and ge(s["grade"], "B")]
    ids = sorted({s["id"] for s in scs})
    ai_ids = sorted({s["id"] for s in ai_inst})
    r_inst = (len(ai_inst) / n) if n else 0.0
    r_name = (len(ai_ids) / len(ids)) if ids else 0.0
    return {"instances": n, "ai_instances": len(ai_inst), "distinct": len(ids), "ai_distinct": len(ai_ids),
            "ratio_instance": r_inst, "ratio_name": r_name, "ratio": min(r_inst, r_name) if n else 0.0,
            "ai_list": ["%d号%s" % (s["id"], s["name"]) for s in ai_inst]}


def ai_need(st, t):
    """达到比例t还差多少：升级现有场景 / 新增AI场景（两种口径取更严的）。"""
    res = {}
    for label, a, n in (("实例", st["ai_instances"], st["instances"]), ("场景名称", st["ai_distinct"], st["distinct"])):
        up = max(0, int(math.ceil(t * n - a - 1e-9)))
        add = max(0, int(math.ceil((t * n - a) / (1 - t) - 1e-9))) if t < 1 else None
        res[label] = {"upgrade": up, "add": add}
    return {"upgrade": max(res["实例"]["upgrade"], res["场景名称"]["upgrade"]),
            "add": max(res["实例"]["add"], res["场景名称"]["add"]), "detail": res}


# ---------------------------------------------------------------- 分级研判
def level_locals(level, d):
    out = []
    for r in R.local_rules_for(d["company"]):
        cfg = r["levels"].get(level)
        if cfg:
            out.append((r, cfg))
    return out


def evaluate_level(level, d):
    checks = []
    gates = d["gates"]
    locs = level_locals(level, d)
    all_locs = R.local_rules_for(d["company"])

    def add(cid, kind, text, state, detail="", fix="", req_level=None):
        checks.append({"id": cid, "kind": kind, "text": text, "state": state, "detail": detail, "fix": fix,
                       "req_level": req_level})

    for g in R.GATES:
        v = gates.get(g["key"])
        if v is None:
            st = "unknown"
        else:
            st = "hit" if v == g["want"] else "miss"
        detail, fix = g["note"], ""
        if g["key"] == "scale_above" and st == "miss" and level in ("基础级", "先进级"):
            exc = [r for r in all_locs if r.get("scale_exception")]
            if exc:
                if d["extras"].get("sme_tag") is True:
                    st, detail = "hit", "按%s：%s" % (exc[0]["region"], exc[0]["scale_exception"])
                else:
                    fix = "%s：%s；如属于这类企业，补充说明后可参照申报" % (exc[0]["region"], exc[0]["scale_exception"])
        kind = "硬门槛" if g["hard"] else "门槛"
        if st != "hit" and not fix:
            fix = "一票否决项，无法通过补材料解决" if (g["hard"] and st == "miss") else g["note"]
        add("G-" + g["key"], kind, g["req"], st, detail, fix)

    need_cm, cm_src = R.CMMM_MIN[level], ""
    for r, cfg in locs:
        if cfg.get("cmmm_min") is not None:
            need_cm, cm_src = cfg["cmmm_min"], r["region"]
    cm_text = "智能制造能力成熟度达到%d级及以上%s" % (need_cm, ("（%s要求）" % cm_src) if cm_src else "")
    lv = gates.get("cmmm_level")
    if lv is None:
        add("G-cmmm", "门槛", cm_text, "unknown",
            "还没有成熟度自评估结果", "到智能制造评估评价公共服务平台（www.c3mep.cn）完成自评估，保留报告")
    else:
        add("G-cmmm", "门槛", cm_text, "hit" if lv >= need_cm else "miss",
            "当前%d级%s" % (lv, ("（%.2f分）" % gates["cmmm_score"]) if gates.get("cmmm_score") is not None else ""),
            "" if lv >= need_cm else "按GB/T 39116补齐%d级要求后重新评估；常用分档：%.1f分以上为%d级" % (
                need_cm, [b for b, l in R.CMMM_SCORE_BANDS if l == need_cm][0], need_cm))

    cur = gates.get("current_level", "无")
    known = gates.get("current_level_known", True)
    pre = R.PREREQ[level]
    if pre:
        ok = R.LEVELS.index(cur) >= R.LEVELS.index(pre) if cur in R.LEVELS else False
        st = "hit" if ok else ("miss" if known else "unknown")
        add("G-prereq", "门槛", "已获评%s" % pre, st, "当前：%s" % (cur if known else "未说明"),
            "" if ok else "须先获评%s，才能申报%s" % (pre, level), req_level=pre)
    for r, cfg in locs:
        lp = cfg.get("prereq")
        if lp:
            ok = R.LEVELS.index(cur) >= R.LEVELS.index(lp) if cur in R.LEVELS else False
            st = "hit" if ok else ("miss" if known else "unknown")
            add("L-prereq", "地方", "已完成%s智能工厂自评或备案（%s要求）" % (lp, r["region"]), st,
                "当前：%s" % (cur if known else "未说明"),
                "" if ok else "按%s要求先完成%s自评或备案，再报%s" % (r["region"], lp, level), req_level=lp)
        for q in cfg.get("requires", []):
            v = d["local"].get(q["key"])
            st = "unknown" if v is None else ("hit" if v else "miss")
            add("L-req-" + q["key"], "地方", "%s（%s要求）" % (q["q"], r["region"]), st,
                "未确认是否已完成" if st == "unknown" else "",
                "" if st == "hit" else "按%s当年通知完成" % r["region"])

    seg_rows = []
    for seg in R.SEGMENTS:
        key = seg["key"]
        pts = [p for p in R.POINTS[level] if p["seg"] == key]
        prow = []
        for p in pts:
            st, by = eval_map(p["m"], d)
            ov = d["overrides"].get(p["id"])
            if isinstance(ov, dict) and ov.get("hit") is not None:
                st = "hit" if tri(ov.get("hit")) else "miss"
                by = "人工判定：" + str(ov.get("reason") or "")
            prow.append({"id": p["id"], "text": p["t"], "state": st, "by": by,
                         "fix": "" if st == "hit" else fix_hint(p["m"]), "sig": bool(p.get("sig"))})
        n_total = len(prow)
        n_hit = sum(1 for p in prow if p["state"] == "hit")
        n_unk = sum(1 for p in prow if p["state"] == "unknown")
        need = int(math.ceil(n_total * R.POINT_PASS_RATIO - 1e-9)) if n_total else 0
        cov_g = R.COVER_MIN_GRADE[level]
        sure = [s for s in d["scenarios"] if s["seg"] == key and ge(s["grade"], cov_g) and s["confirmed"]]
        maybe = [s for s in d["scenarios"] if s["seg"] == key and ge(s["grade"], cov_g) and not s["confirmed"]]
        covered = "hit" if sure else ("unknown" if maybe else "miss")
        if covered == "miss":
            sst = "未覆盖"
        elif n_hit >= need and covered == "hit":
            sst = "达标"
        elif n_hit + n_unk >= need:
            sst = "待证"
        else:
            sst = "不足"
        required = key in R.REQUIRED_SEGS[level]
        seg_rows.append({"seg": key, "name": seg["name"], "required": required, "covered": covered,
                         "hit": n_hit, "unknown": n_unk, "total": n_total, "need": need, "state": sst, "points": prow})
        if required:
            stmap = {"达标": "hit", "待证": "unknown", "不足": "miss", "未覆盖": "miss"}
            missing = [p for p in prow if p["state"] != "hit"]
            add("S-" + key, "环节", "%s环节（%s，要点%d/%d，需≥%d）" % (seg["name"], sst, n_hit, n_total, need),
                stmap[sst], R.REQUIRED_NOTE[level],
                "" if sst == "达标" else "；".join("%s %s%s" % (p["id"], p["text"], "（待证）" if p["state"] == "unknown" else "") for p in missing[:4]))
        for p in prow:
            if p["sig"] and required:
                add("SIG-" + p["id"], "标志", p["text"], p["state"], p["by"], p["fix"])

    if level == "先进级":
        sure = [s for s in d["scenarios"] if ge(s["grade"], "B") and s["confirmed"]]
        maybe = [s for s in d["scenarios"] if ge(s["grade"], "B") and not s["confirmed"]]
        st = "hit" if sure else ("unknown" if maybe else "miss")
        add("SIG-smart", "标志", "重点场景开展智能化应用（至少1个场景达到B级：有模型算法）", st,
            "、".join("%d号%s" % (s["id"], s["name"]) for s in sure[:3]),
            "" if st == "hit" else "选一个痛点最明显的场景（排产、质检、设备预警）上模型算法")

    t, t_src = R.AI_RATIO_MIN[level], ""
    for r, cfg in locs:
        if cfg.get("ai_ratio_min") is not None:
            t, t_src = cfg["ai_ratio_min"], r["region"]
    if t:
        st_c = ai_stats(d, "confirmed")
        st_a = ai_stats(d, "all")
        if st_c["ratio"] >= t - 1e-9:
            state = "hit"
        elif st_a["ratio"] >= t - 1e-9:
            state = "unknown"
        else:
            state = "miss"
        need = ai_need(st_c, t)
        add("AI-ratio", "比例", "应用人工智能技术场景比例≥%d%%%s" % (round(t * 100), ("（%s要求）" % t_src) if t_src else ""), state,
            "实例口径%d/%d=%.1f%%，场景名称口径%d/%d=%.1f%%，取低值%.1f%%" % (
                st_c["ai_instances"], st_c["instances"], st_c["ratio_instance"] * 100,
                st_c["ai_distinct"], st_c["distinct"], st_c["ratio_name"] * 100, st_c["ratio"] * 100),
            "" if state == "hit" else "还差：把现有场景升级为AI场景%d个，或新增AI场景%d个（AI场景须达到B级：在用、数据贯通、有模型）" % (
                need["upgrade"], need["add"]))

    mn, mn_note = R.MIN_DISTINCT[level], R.MIN_DISTINCT_NOTE
    for r, cfg in locs:
        if cfg.get("min_distinct") is not None:
            mn, mn_note = cfg["min_distinct"], "%s要求，%s" % (r["region"], r["source"])
    if mn:
        ids_c = {s["id"] for s in d["scenarios"] if ge(s["grade"], "C") and s["confirmed"] and s["declare"]}
        ids_a = {s["id"] for s in d["scenarios"] if ge(s["grade"], "C") and s["declare"]}
        st = "hit" if len(ids_c) >= mn else ("unknown" if len(ids_a) >= mn else "miss")
        add("CNT-distinct", "数量", "不同场景名称（C级及以上）不少于%d个" % mn, st,
            "当前%d个（%s）" % (len(ids_c), mn_note), "" if st == "hit" else "补足到%d个以上" % mn)

    for e in R.EFFECTS[level]:
        st, by = eval_map(e["m"], d)
        ov = d["overrides"].get(e["id"])
        if isinstance(ov, dict) and ov.get("hit") is not None:
            st = "hit" if tri(ov.get("hit")) else "miss"
            by = "人工判定：" + str(ov.get("reason") or "")
        add(e["id"], "成效", e["t"], st, by, "" if st == "hit" else fix_hint(e["m"]))

    hard_fail = [c for c in checks if c["kind"] == "硬门槛" and c["state"] == "miss"]
    gaps = [c for c in checks if c["state"] == "miss" and c["kind"] != "硬门槛"]
    pending = [c for c in checks if c["state"] == "unknown"]
    local_notes = [{"region": r["region"], "source": r["source"], "notes": cfg.get("notes", [])} for r, cfg in locs]
    return {"level": level, "checks": checks, "segments": seg_rows, "hard_fail": hard_fail, "gaps": gaps,
            "pending": pending, "verdict": verdict(hard_fail, gaps, pending),
            "verdict_opt": verdict(hard_fail, gaps, []), "local": local_notes}


def verdict(hard_fail, gaps, pending):
    if hard_fail:
        return "暂不具备（硬门槛不满足）"
    if not gaps and not pending:
        return "条件基本具备"
    if not gaps:
        return "补证后具备（待证%d项）" % len(pending)
    tail = "，另有%d项待证" % len(pending) if pending else ""
    if len(gaps) <= 3:
        return "有缺口（%d项%s）" % (len(gaps), tail)
    return "差距较大（%d项缺口%s）" % (len(gaps), tail)


def is_ready(v):
    return v.startswith("条件基本具备") or v.startswith("补证后具备")


# ---------------------------------------------------------------- 指标计算
def kpi_def(name):
    name = R.KPI_ALIASES.get(name, name)
    for k in R.KPIS:
        if k["name"] == name:
            return k
    return None


def calc_kpi(k):
    name = str(k.get("name")).strip()
    df = kpi_def(name)
    rb, ra = k.get("before"), k.get("after")
    b, a = num(rb), num(ra)
    row = {"name": df["name"] if df else name, "unit": k.get("unit") or "", "before": b, "after": a,
           "period": k.get("period") or "", "basis": k.get("basis") or "", "dir": df["dir"] if df else "up",
           "kind": df["kind"] if df else "value", "known": bool(df), "change": None, "pp": None, "text": "", "warn": []}
    if not df:
        row["warn"].append("不在常用指标表里：单独写清定义和计算方法")
    is_pct = row["kind"] in ("rate", "level")
    if is_pct:
        row["unit"] = "%"
        sb, sa = "%" in str(rb), "%" in str(ra)
        small = bool(df and df.get("small"))
        if a is not None and b is not None and sb != sa:
            if not sb and b <= 1 < a:
                b = b * 100
                row["warn"].append("建设前数值按小数理解（0.62即62%），请确认")
            elif not sa and a <= 1 < b:
                a = a * 100
                row["warn"].append("当前值按小数理解（0.62即62%），请确认")
        elif a is not None and not sb and not sa:
            if (b is None or b <= 1) and a <= 1 and (a > 0 or (b or 0) > 0):
                if small:
                    row["warn"].append("按百分数理解（0.9即0.9%）；如果填的是小数（0.009），请改成百分数")
                else:
                    a = a * 100
                    b = b * 100 if b is not None else None
                    row["warn"].append("按小数理解（0.95即95%）；如果原值本来就是百分数，请加上%号重算")
            elif b is not None and (b <= 1) != (a <= 1) and min(a, b) > 0:
                row["warn"].append("建设前和当前值的单位看起来不一致（一个像小数，一个像百分数）")
        row["before"], row["after"] = b, a
    if a is None:
        row["text"] = "缺当前值"
        return row
    if b is None:
        if row["kind"] in ("level", "count"):
            row["text"] = "当前%s%s" % (fmt(a), row["unit"])
        else:
            row["text"] = "缺建设前数值"
            row["warn"].append("缺建设前数值，算不出改善幅度")
        return row
    if b == 0:
        row["text"] = "建设前为0，无法算相对变化"
        return row
    ch = (a - b) / b if row["dir"] == "up" else (b - a) / b
    row["change"] = ch
    word_up, word_down = ("提升", "下降") if row["dir"] == "up" else ("下降", "上升")
    if row["name"] == "研制周期":
        word_up, word_down = "缩短", "延长"
    if ch >= 0:
        row["text"] = "%s%.1f%%" % (word_up, ch * 100)
    else:
        row["text"] = "%s%.1f%%（变差）" % (word_down, -ch * 100)
        row["warn"].append("指标变差或没有改善：不要放进成效表，先查原因")
    if is_pct:
        row["pp"] = a - b
        row["text"] += "（%+.1f个百分点）" % (a - b)
    if ch > 0.6 and row["kind"] == "value":
        row["warn"].append("改善幅度超过60%，评审和现场会追问：备好口径说明和原始台账")
    if not row["period"]:
        row["warn"].append("没写统计期：建设前、当前各对应哪段时间")
    if not row["basis"]:
        row["warn"].append("没写口径或数据来源")
    return row


def fmt(x):
    if x is None:
        return "—"
    if abs(x - round(x)) < 1e-9:
        return "%d" % round(x)
    return ("%.4f" % x).rstrip("0").rstrip(".")


# ---------------------------------------------------------------- 一致性与风险提示
def flags(d, ai_c):
    out = []

    def f(level, text):
        out.append({"level": level, "text": text})

    g = d["gates"]
    if g.get("built") is False:
        f("高", "工厂还没建成投产：在建内容不能按已建成申报，只能写进“后续实施计划”")
    for s in d["scenarios"]:
        if s["id"] == 3 and s["grade"] != "未建" and not ge(s["grade"], "B"):
            f("高", "3号数字孪生只到%s级：三维可视化大屏不等于数字孪生，需要实时数据驱动和模型交互（分析、仿真、反向控制或调度）" % s["grade"])
        if s["ai"] and not ge(s["grade"], "B"):
            f("中", "%d号%s标了AI但未达到B级（缺数据贯通或模型），按本技能口径不计入AI场景" % (s["id"], s["name"]))
        if s["ai"] and not s["ai_types"]:
            f("低", "%d号%s没写AI技术类型（如机器视觉、深度学习、强化学习、知识工程、生成式人工智能）" % (s["id"], s["name"]))
        if s["ai"] and ge(s["grade"], "B") and s["months"] is not None and s["months"] < 3:
            f("中", "%d号%s上线不足3个月：成效数据难以成立，现场也容易被问住" % (s["id"], s["name"]))
        elif s["quantified"] and s["months"] is not None and s["months"] < 6:
            f("低", "%d号%s运行不足6个月：成效数据说服力弱，注明统计期" % (s["id"], s["name"]))
        if s["id"] in (8, 9, 11) and s["model"] and not s["ai"]:
            f("低", "%d号%s有算法但未标AI：纯运筹优化/启发式算法是否算“应用人工智能技术”，按当年模板口径判断，保守起见不计入" % (s["id"], s["name"]))
    pend = [x for x in d["scenarios"] if not x["confirmed"] and x["grade"] != "未建"]
    if pend:
        f("中", "待证场景%d个（%s）：补齐运行记录、截图、数据后才计入；保守口径已把它们排除" % (
            len(pend), "、".join("%d号%s" % (x["id"], x["name"]) for x in pend[:5])))
    ex = d["extras"]
    gen_ai = any("生成式人工智能" in s["ai_types"] for s in d["scenarios"] if ge(s["grade"], "B"))
    if (ex.get("tokens_per_day") or 0) > 0 and not ex.get("llm_in_production") and not gen_ai:
        f("中", "填了日均词元调用量，但没有任何场景在用大模型：两处要对得上，并能拿出平台调用日志")
    agent_sc = any("工业智能体" in s["ai_types"] for s in d["scenarios"])
    if (ex.get("agents_count") or 0) > 0 and not agent_sc:
        f("中", "填了工业智能体数量，但没有场景标注“工业智能体”：每个智能体都要能对应到具体场景和运行记录")
    if ex.get("ai_models_count") is not None and ex["ai_models_count"] < ai_c["ai_instances"]:
        f("中", "AI模型数量（%d）少于AI场景实例数（%d）：每个AI场景至少对应一条模型清单" % (ex["ai_models_count"], ai_c["ai_instances"]))
    if g.get("cmmm_score") is not None and g.get("cmmm_level") is not None:
        lv = cmmm_level_from_score(g["cmmm_score"])
        if lv != g["cmmm_level"]:
            f("中", "成熟度得分%.2f按常用分档对应%d级，与填写的%d级不一致：以评估报告结论为准" % (g["cmmm_score"], lv, g["cmmm_level"]))
    if g.get("cmmm_source") and "自评" in g["cmmm_source"] and (g.get("cmmm_level") or 0) >= 3:
        f("低", "成熟度三级以上目前是自评结果：冲卓越级建议同时准备评估诊断报告或CMMM符合性证书，现场更有底气")
    name = (d["company"].get("factory") or "").strip()
    if name:
        cn = len(re.sub(r"[A-Za-z0-9]", "", name)) + int(math.ceil(len(re.findall(r"[A-Za-z0-9]", name)) / 3.0))
        if not name.endswith("智能工厂") or cn > 14:
            f("低", "工厂名称“%s”：不少模板要求以“智能工厂”结尾、不超过14个汉字（上海2026年模板明确如此）" % name)
    if not d["kpis"] and any(s["quantified"] for s in d["scenarios"]):
        f("中", "场景里写了量化成效，但关键指标表是空的：申报书要求填写建设前与当前值")
    if not d["investment"].get("total_wan"):
        f("低", "没有建设总投资：申报书必填，建议按年度、按软硬件拆分并与合同发票对得上")
    if d["gates"].get("current_level") in ("卓越级", "领航级"):
        lv = d["gates"]["current_level"]
        dt = parse_month(d["gates"].get("current_level_date"))
        if dt:
            exp = add_months(dt, 12 * R.VALIDITY[lv])
            rev = add_months(exp, -3)
            f("中", "%s有效期3年：约%s到期，须在%s前发起复核申请，到期未复核直接取消（管理办法）" % (lv, exp.isoformat()[:7], rev.isoformat()[:7]))
    return out


# ---------------------------------------------------------------- 时间倒排
def parse_month(s):
    if not s:
        return None
    m = re.match(r"(\d{4})[-/.年](\d{1,2})", str(s))
    if not m:
        return None
    return _dt.date(int(m.group(1)), int(m.group(2)), 1)


def add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    return _dt.date(d.year + y, m + 1, 1)


def _top_gaps(lvres, n=3):
    if not lvres:
        return ""
    items = [c for c in lvres["gaps"] if c["id"] not in PREREQ_IDS] + lvres["pending"]
    return "、".join(c["text"].split("（")[0] for c in items[:n])


def plan(level, today, shift=0, lvres=None, gates=None):
    out = []
    gates = gates or {}
    cm = gates.get("cmmm_level") or 0
    gap_txt = _top_gaps(lvres)
    if level == "先进级":
        y = (today.year if today < _dt.date(today.year, 3, 1) else today.year + 1) + shift
        t = _dt.date(y, 3, 31)
        first = ("在 www.c3mep.cn 完成智能制造能力成熟度自评估（目标二级以上）" if cm < 2
                 else "复核成熟度自评结果与现状是否一致，保留评估报告")
        if gates.get("current_level") in (None, "无"):
            first += "；按当地要求完成基础级自评或备案"
        steps = [(120, first),
                 (90, ("补齐：" + gap_txt) if gap_txt else "按先进级要点逐条复核，查漏补证"),
                 (60, "定指标口径，整理建设前与当前值的原始台账"),
                 (30, "写申报书，每个场景配现场图"),
                 (10, "定稿、盖章（首页和真实性承诺页）"),
                 (0, "省级申报截止（按江苏等省的常见节奏估计，以当地通知为准）")]
    else:
        y = (today.year if today < _dt.date(today.year, 5, 1) else today.year + 1) + shift
        t = _dt.date(y, 8, 1)
        need_cm = R.CMMM_MIN[level]
        steps = [(240, ("差距补强立项，先补：" + gap_txt) if gap_txt else "按要点逐条复核，补强薄弱环节"),
                 (180, "定指标口径，建立建设前与当前值台账（统计期、数据来源固定下来）"),
                 (150, ("成熟度评估：目标%d级，必要时做评估诊断或符合性评估" % need_cm) if cm < need_cm
                  else "成熟度已达%d级：准备评估报告原件，核对与现状一致" % cm),
                 (120, "新增或升级的AI场景上线：至少运行3个月才能拿出成效数据"),
                 (60, "申报书初稿、8分钟以内的工厂简介视频脚本"),
                 (30, "按现场核查标准内部预演：系统实操、数据实时性、指标台账、模型清单"),
                 (10, "定稿、盖章，线上填报全部保存"),
                 (0, "地方截止（估计：国家通知多在6—7月发布，线上截止7月中—8月中，地方再提前5—10天）")]
    for days, text in steps:
        dday = t - _dt.timedelta(days=days)
        status = "已过" if dday < today else ""
        out.append({"date": dday.isoformat(), "text": text, "status": status})
    note = ("缺口较多，建议瞄准%d年度窗口；在此之前先把前一级拿下，硬缺口从现在开始建" % t.year) if shift else ""
    if shift:
        out.insert(0, {"date": today.isoformat(), "text": "现在起：把耗时最长的硬缺口（AI场景、数字孪生、数据治理）列入建设计划，边建边积累运行数据", "status": ""})
    return {"level": level, "deadline_est": t.isoformat(), "steps": out, "history": R.WINDOWS[level]["history"], "note": note}



# ---------------------------------------------------------------- 申报日历
def calendar(today, d):
    regions = {"全国"} | {r["region"] for r in R.local_rules_for(d["company"])}
    out = []
    for e in R.EVENTS:
        if e["region"] not in regions:
            continue
        st = _dt.date(*[int(x) for x in e["start"].split("-")])
        en = _dt.date(*[int(x) for x in e["end"].split("-")])
        if st <= today <= en:
            status = "进行中"
        elif today < st and (st - today).days <= 240:
            status = "即将"
        elif en < today and (today - en).days <= 30:
            status = "刚结束"
        else:
            continue
        out.append({"start": e["start"], "end": e["end"], "region": e["region"], "status": status,
                    "text": e["text"] + ("" if e["verified"] else "（预计）"), "verified": e["verified"]})
    order = {"进行中": 0, "即将": 1, "刚结束": 2}
    out.sort(key=lambda x: (order[x["status"]], x["start"]))
    return out


# ---------------------------------------------------------------- 竞争力观察（卓越级、领航级是遴选，不是达标即过）
def competition(level, d, ai_c, kpis):
    good, weak = [], []
    scs = [s for s in d["scenarios"] if s["grade"] != "未建" and s["confirmed"]]
    a_cnt = sum(1 for s in scs if s["grade"] == "A")
    if a_cnt >= 8:
        good.append("A级场景%d个，主力场景充足" % a_cnt)
    elif a_cnt < 4:
        weak.append("A级场景只有%d个：主力场景少，评审看不到足够的量化成效" % a_cnt)
    t = R.AI_RATIO_MIN.get(level) or 0
    if ai_c["instances"]:
        margin = ai_c["ratio"] - t
        if margin >= 0.10:
            good.append("AI场景比例%.1f%%，高出门槛%.1f个百分点" % (ai_c["ratio"] * 100, margin * 100))
        elif margin >= 0:
            weak.append("AI场景比例%.1f%%，只高出门槛%.1f个百分点：评审逐个核减一两个就会掉线" % (ai_c["ratio"] * 100, margin * 100))
    src = d["gates"].get("cmmm_source") or ""
    if "证书" in src or "诊断" in src or "第三方" in src:
        good.append("成熟度有%s支撑" % src)
    elif src:
        weak.append("成熟度只有自评结果，建议补评估诊断或符合性评估")
    ex = d["extras"]
    if (ex.get("standards") or 0) >= 2:
        good.append("参与制定行业标准或国家标准")
    elif ex.get("standards") is not None and ex.get("standards") < 1:
        weak.append("没有标准成果：“标准群”是卓越级成效项之一")
    if (ex.get("solution") or 0) >= 1:
        good.append("解决方案已有复制推广")
    elif ex.get("solution") == 0:
        weak.append("没有可推广的解决方案")
    if (ex.get("supply_chain_driven") or 0) >= 5:
        good.append("带动上下游%d家企业" % ex["supply_chain_driven"])
    elif ex.get("supply_chain_driven") == 0:
        weak.append("没有带动上下游的实例")
    need_bm = 3 if level == "卓越级" else 4
    if (ex.get("benchmark") or 0) >= need_bm:
        good.append("主要指标领先有对比依据")
    else:
        weak.append("缺少%s领先的对比依据（行业协会数据、对标报告等）" % ("国内同行业" if level == "卓越级" else "全球"))
    strong_kpi = [k for k in kpis if k.get("change") is not None and k["change"] >= 0.2]
    if len(strong_kpi) >= 4:
        good.append("%d项关键指标改善20%%以上" % len(strong_kpi))
    elif not [k for k in kpis if k.get("change") is not None]:
        weak.append("没有建设前后对比的关键指标")
    if level == "领航级":
        if not ex.get("industry_leader"):
            weak.append("领军企业地位和核心产品全球竞争力需要充分证明")
        weak.append("参照：2025年首批15家领航级工厂，公开报道称AI已渗透70%以上业务场景")
    if ex.get("demo_factory"):
        good.append("已通过智能制造示范工厂揭榜验收：上海、内蒙古等地明确申报卓越级不占地方推荐名额")
    return {"level": level, "good": good, "weak": weak,
            "note": "卓越级每年全国两百多个、按省限额推荐（2026年公示253个）；以上是竞争力信号，不是官方评分"}


# ---------------------------------------------------------------- 材料准备清单
def materials(level, d, lvres):
    items = [{"item": x, "state": ""} for x in R.MATERIALS["通用"] + R.MATERIALS.get(level, [])]
    g, ex = d["gates"], d["extras"]
    for it in items:
        if it["item"].startswith("智能制造能力成熟度评估结果"):
            it["state"] = "有（%d级）" % g["cmmm_level"] if g.get("cmmm_level") is not None else "待办"
        elif it["item"].startswith("制造业数字化转型通用评估"):
            it["state"] = "有" if ex.get("dx_eval") else "待办"
        elif it["item"].startswith("已获评先进级"):
            it["state"] = "有" if g.get("current_level") in ("先进级", "卓越级", "领航级") else "待办"
        elif it["item"].startswith("已获评卓越级"):
            it["state"] = "有" if g.get("current_level") in ("卓越级", "领航级") else "待办"
        elif it["item"].startswith("人工智能模型清单"):
            it["state"] = "有（%d个模型）" % ex["ai_models_count"] if ex.get("ai_models_count") else "待办"
    if lvres:
        for c in lvres["checks"]:
            if c["kind"] == "地方" and c["id"].startswith("L-req-"):
                items.append({"item": c["text"], "state": {"hit": "有", "miss": "待办", "unknown": "待确认"}[c["state"]]})
    return items

# ---------------------------------------------------------------- 总装
def evaluate(inp, today=None):
    d = normalize(inp)
    today = today or _dt.date.today()
    levels = [evaluate_level(lv, d) for lv in R.LEVELS]
    ai_c = ai_stats(d, "confirmed")
    ai_a = ai_stats(d, "all")
    kpis = [calc_kpi(k) for k in d["kpis"]]
    have = {k["name"] for k in kpis}
    if "应用人工智能技术场景比例" not in have and ai_c["instances"]:
        kpis.append({"name": "应用人工智能技术场景比例", "unit": "%", "before": None, "after": round(ai_c["ratio"] * 100, 1),
                     "period": "当前", "basis": "场景盘点自动计算（保守口径，取低值）", "dir": "up", "kind": "level", "known": True,
                     "change": None, "pp": None, "text": "当前%.1f%%（自动计算）" % (ai_c["ratio"] * 100), "warn": []})
    if "应用人工智能模型数量" not in have and d["extras"].get("ai_models_count") is not None:
        kpis.append({"name": "应用人工智能模型数量", "unit": "个", "before": None, "after": d["extras"]["ai_models_count"],
                     "period": "当前", "basis": "能力补充项", "dir": "up", "kind": "count", "known": True,
                     "change": None, "pp": None, "text": "当前%s个" % fmt(d["extras"]["ai_models_count"]), "warn": []})
    for key, nm in (("agents_count", "开发工业智能体数量"), ("tokens_per_day", "日均词元调用量")):
        if nm not in have and (d["extras"].get(key) or 0) > 0:
            kpis.append({"name": nm, "unit": "个" if key == "agents_count" else "词元/日", "before": None, "after": d["extras"][key],
                         "period": "当前", "basis": "能力补充项", "dir": "up", "kind": "count", "known": True,
                         "change": None, "pp": None, "text": "当前%s" % fmt(d["extras"][key]), "warn": []})
    have = {k["name"] for k in kpis}
    missing_req = [k["name"] for k in R.KPIS if k["req"] and k["name"] not in have and k["name"] != "应用人工智能技术场景比例"]
    for k in kpis:
        if k["name"] == "应用人工智能技术场景比例" and k["after"] is not None and "自动计算" not in k["basis"]:
            claimed = k["after"]  # calc_kpi 已统一成百分数
            if abs(claimed - ai_c["ratio"] * 100) > 5:
                k["warn"].append("填写的%.1f%%与场景盘点算出的%.1f%%差距较大，以盘点口径为准" % (claimed, ai_c["ratio"] * 100))

    cur = d["gates"].get("current_level", "无")
    cap = None
    for lv in levels:
        if is_ready(lv["verdict"]) or (lv["level"] != "基础级" and only_prereq_missing(lv)):
            cap = lv["level"]
    rec = recommend(levels, cur, d["target"], d["gates"].get("current_level_known", True), d["extras"])
    plans = []
    L = {x["level"]: x for x in levels}
    al = rec.get("apply_level")
    if al in ("先进级", "卓越级", "领航级"):
        plans.append(plan(al, today, 0, L[al], d["gates"]))
    nl = rec.get("next_level")
    if nl in ("先进级", "卓越级", "领航级") and nl != al and L[nl]["hard_fail"]:
        rec["headline"] += "；下一目标%s目前不满足硬门槛（%s），先解决这一项" % (nl, "、".join(c["text"] for c in L[nl]["hard_fail"]))
    elif nl in ("先进级", "卓越级", "领航级") and nl != al:
        real_gaps = [c for c in L[nl]["gaps"] if c["id"] not in PREREQ_IDS]
        shift = 1 if len(real_gaps) >= 8 else 0
        plans.append(plan(nl, today, shift, L[nl], d["gates"]))
        rec["next_year_hint"] = int(plans[-1]["deadline_est"][:4])
        rec["headline"] += "；下一目标：%s，目前%s，建议按%d年度准备" % (nl, L[nl]["verdict"], rec["next_year_hint"])

    focus = [x for x in (rec.get("apply_level"), rec.get("next_level")) if x]
    comp = [competition(lv, d, ai_c, kpis) for lv in focus if lv in ("卓越级", "领航级")]
    mats = {lv: materials(lv, d, L[lv]) for lv in focus}
    cal = calendar(today, d)
    locs = [{"region": r["region"], "source": r["source"]} for r in R.local_rules_for(d["company"])]

    by_seg = {}
    for seg in R.SEGMENTS:
        items = [s for s in d["scenarios"] if s["seg"] == seg["key"] and s["grade"] != "未建"]
        by_seg[seg["key"]] = {"name": seg["name"], "count": len(items),
                              "grades": {g: sum(1 for s in items if s["grade"] == g) for g in ("A", "B", "C", "D")}}
    return {
        "rules_version": R.RULES_VERSION, "data_date": R.DATA_DATE, "today": today.isoformat(),
        "company": d["company"], "gates": d["gates"], "investment": d["investment"],
        "scenarios": d["scenarios"], "by_seg": by_seg, "ai": ai_c, "ai_all": ai_a,
        "levels": levels, "capability": cap, "current": cur, "recommend": rec,
        "kpis": kpis, "kpi_missing_required": missing_req, "flags": flags(d, ai_c), "plans": plans,
        "competition": comp, "materials": mats, "calendar": cal, "local_rules": locs,
    }


PREREQ_IDS = ("G-prereq", "L-prereq")


def only_prereq_missing(lv):
    gaps = [c for c in lv["gaps"] if c["id"] not in PREREQ_IDS]
    return not lv["hard_fail"] and not gaps and any(c["id"] in PREREQ_IDS for c in lv["gaps"])


def prereq_target(lv):
    """缺的前置层级里最高的那个。"""
    req = [c["req_level"] for c in lv["gaps"] if c["id"] in PREREQ_IDS and c.get("req_level")]
    return max(req, key=R.LEVELS.index) if req else None


def recommend(levels, cur, target, known=True, extras=None):
    extras = extras or {}
    L = {x["level"]: x for x in levels}
    order = R.LEVELS
    cur_i = order.index(cur) if cur in order else -1
    apply_level, next_level, notes = None, None, []
    if L["基础级"]["hard_fail"]:
        return {"apply_level": None, "next_level": None, "headline": "基本条件有一票否决项，暂不建议申报任何层级",
                "notes": [c["text"] for c in L["基础级"]["hard_fail"]]}
    for i, lv in enumerate(order):
        if i <= cur_i:
            continue
        x = L[lv]
        ready = is_ready(x["verdict"])
        if ready:
            apply_level = lv
            continue
        if only_prereq_missing(x):
            pt = prereq_target(x)
            notes.append("%s能力上已基本具备，但须先获评或完成%s" % (lv, pt))
            if apply_level is None:
                apply_level = pt
            next_level = lv
            break
        next_level = lv
        break
    # 只能逐级获评：卓越级以上要求已持有前一级
    if apply_level in ("卓越级", "领航级"):
        pre = R.PREREQ[apply_level]
        if cur_i < order.index(pre):
            next_level = apply_level
            apply_level = pre
    if apply_level == "基础级":
        head = "可先完成基础级自评/备案（规上企业自评自建），并以先进级为下一目标"
        if next_level is None:
            next_level = "先进级"
    elif apply_level:
        head = "本轮可冲：%s" % apply_level
    else:
        head = "现有条件下暂未达到%s要求，先补缺口" % (order[cur_i + 1] if cur_i + 1 < len(order) else "更高层级")
    if not known:
        notes.append("没有说明已获评的层级：前置条件按“待证”处理，请确认是否已获评基础级、先进级或卓越级")
    elif cur == "无" and apply_level in ("先进级", "卓越级"):
        notes.append("多数地方要求先完成基础级智能工厂自评或备案，再报先进级")
    if extras.get("old_title"):
        notes.append("曾获省级智能工厂、数字化车间等称号：上海已把2020—2023年度市级智能工厂一并认定为先进级，浙江做过转评转认，先核实是否已被转认")
    if extras.get("demo_factory") and "卓越级" in (next_level, apply_level):
        notes.append("已通过国家智能制造示范工厂揭榜验收：上海、内蒙古2026年通知明确申报卓越级不占地方推荐名额，以当地通知为准")
    if target in order and target != apply_level:
        notes.append("你设定的目标是%s，相关缺口见该级明细" % target)
    return {"apply_level": apply_level, "next_level": next_level, "headline": head, "notes": notes}


# ---------------------------------------------------------------- 文字摘要（给对话直接用）
STATE_MARK = {"hit": "✓", "miss": "✗", "unknown": "?"}


def summary_text(res, focus=None):
    lines = []
    c = res["company"]
    lines.append("【研判对象】%s %s（%s，%s）" % (c.get("name", ""), c.get("factory", ""), c.get("province", ""), c.get("industry", "")))
    lines.append("【结论】" + res["recommend"]["headline"])
    for n in res["recommend"]["notes"]:
        lines.append("  · " + n)
    lines.append("【四级对照】")
    for lv in res["levels"]:
        extra = "" if lv["verdict"] == lv["verdict_opt"] else "；若待证项坐实：%s" % lv["verdict_opt"]
        lines.append("  %s：%s%s" % (lv["level"], lv["verdict"], extra))
    a = res["ai"]
    lines.append("【AI场景比例】实例口径 %d/%d=%.1f%%；场景名称口径 %d/%d=%.1f%%；取低值 %.1f%%" % (
        a["ai_instances"], a["instances"], a["ratio_instance"] * 100, a["ai_distinct"], a["distinct"], a["ratio_name"] * 100, a["ratio"] * 100))
    focus_lvs = [focus] if focus else [x for x in (res["recommend"].get("apply_level"), res["recommend"].get("next_level")) if x]
    for lv in res["levels"]:
        if lv["level"] not in focus_lvs:
            continue
        lines.append("【%s缺口】" % lv["level"])
        if not (lv["hard_fail"] or lv["gaps"] or lv["pending"]):
            lines.append("  无：门槛、环节、标志性要求均已满足，重点转向材料质量和现场核查准备")
        for g in lv["hard_fail"] + lv["gaps"]:
            lines.append("  ✗ %s%s" % (g["text"], ("｜" + g["fix"]) if g["fix"] else ""))
        for g in lv["pending"][:8]:
            lines.append("  ? %s%s" % (g["text"], ("｜" + g["detail"]) if g["detail"] else ""))
        if len(lv["pending"]) > 8:
            lines.append("  ……另有%d项待证" % (len(lv["pending"]) - 8))
    for lv in res["levels"]:
        if lv["level"] in focus_lvs and lv.get("local"):
            lines.append("【%s·所在地附加要求】" % lv["level"])
            for loc in lv["local"]:
                for n in loc["notes"]:
                    lines.append("  · %s：%s" % (loc["region"], n))
    for c in res.get("competition", []):
        lines.append("【%s竞争力观察】（非官方评分）" % c["level"])
        for g in c["good"]:
            lines.append("  + " + g)
        for w in c["weak"]:
            lines.append("  - " + w)
    if res["kpis"]:
        lines.append("【关键指标】")
        for k in res["kpis"]:
            u = k["unit"]
            if k["before"] is None:
                lines.append("  %s：%s" % (k["name"], k["text"]))
            elif u == "%":
                lines.append("  %s：%s%% → %s%%，%s" % (k["name"], fmt(k["before"]), fmt(k["after"]), k["text"]))
            else:
                lines.append("  %s：%s → %s%s，%s" % (k["name"], fmt(k["before"]), fmt(k["after"]), (" " + u) if u else "", k["text"]))
    if res["flags"]:
        lines.append("【风险提示】")
        for f in res["flags"]:
            lines.append("  [%s] %s" % (f["level"], f["text"]))
    if res.get("calendar"):
        lines.append("【当前时间窗】")
        for e in res["calendar"][:6]:
            lines.append("  [%s] %s" % (e["status"], e["text"]))
    for p in res["plans"]:
        lines.append("【%s倒排（截止为估计：%s）%s】" % (p["level"], p["deadline_est"], ("｜" + p["note"]) if p.get("note") else ""))
        for s in p["steps"]:
            lines.append("  %s %s%s" % (s["date"], s["text"], "（已过）" if s["status"] else ""))
    lines.append("（依据：要素条件2026年版、场景指引2025年版、管理办法（暂行）；规则库%s。研判是按公开规则的推算，最终以主管部门评审为准）" % res["rules_version"])
    return "\n".join(lines)
