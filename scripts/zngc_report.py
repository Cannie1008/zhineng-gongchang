# -*- coding: utf-8 -*-
"""把研判结果排成一份 Word 研判报告（可直接发给企业）。"""
import zngc_rules as R
from zngc_docx import Doc, ACCENT
from zngc_engine import fmt

OK, BAD, WAIT = "1E7B4F", "B23A3A", "8A5A00"
OK_F, BAD_F, WAIT_F = "E6F2EC", "F7E4E4", "FBF1DA"
STATE = {"hit": ("✓ 达成", OK, OK_F), "miss": ("✗ 缺口", BAD, BAD_F), "unknown": ("? 待证", WAIT, WAIT_F)}
REQ_TEXT = {
    "基础级": "成熟度≥2级；至少覆盖生产作业；规上企业自评自建",
    "先进级": "成熟度≥2级；覆盖生产作业、生产管理、运营管理；省级认定",
    "卓越级": "已获评先进级；成熟度≥3级；原则上覆盖五个环节；AI场景≥30%",
    "领航级": "已获评卓越级；成熟度≥4级；须覆盖五个环节；AI场景≥60%",
}


def _verdict_cell(v):
    if v.startswith("条件基本具备"):
        return {"t": v, "color": OK, "fill": OK_F, "b": True}
    if v.startswith("补证后具备"):
        return {"t": v, "color": WAIT, "fill": WAIT_F, "b": True}
    return {"t": v, "color": BAD, "fill": BAD_F, "b": True}


def _state_cell(st):
    t, c, f = STATE.get(st, ("—", "5B6773", None))
    return {"t": t, "color": c, "fill": f, "align": "center"}


def build_report(res, path, org="", contact="", focus=None):
    c = res["company"]
    title = "智能工厂研判报告"
    doc = Doc(title)
    doc.para(title, style="Title")
    doc.para("%s　%s" % (c.get("name", ""), c.get("factory", "")), size=13, color="3B4652", after=200)
    meta = [["项目", "内容"],
            ["研判对象", "%s（%s%s，%s）" % (c.get("factory") or c.get("name", ""), c.get("province", "—"), c.get("city", "") or "", c.get("industry", "—"))],
            ["研判日期", res["today"]],
            ["研判依据", "智能工厂梯度培育要素条件（2026年版）、智能制造典型场景参考指引（2025年版）、智能工厂梯度培育管理办法（暂行）"],
            ["规则库版本", "%s（政策信息截至%s）" % (res["rules_version"], res["data_date"])]]
    if res.get("local_rules"):
        meta.append(["已套用地方规则", "；".join("%s（%s）" % (x["region"], x["source"]) for x in res["local_rules"])])
    if org:
        meta.append(["出具单位", org])
    if contact:
        meta.append(["联系方式", contact])
    doc.table(meta, [1800, 7498])

    # 一、结论
    rec = res["recommend"]
    doc.heading("一、结论", 1)
    doc.para(rec["headline"], bold=True, size=11.5, color=ACCENT, shade="EEF2F6", after=120, before=60)
    for n in rec.get("notes", []):
        doc.bullet(n)
    rows = [["层级", "研判结论", "若待证项全部坐实", "主要要求"]]
    for lv in res["levels"]:
        rows.append([{"t": lv["level"], "b": True}, _verdict_cell(lv["verdict"]), _verdict_cell(lv["verdict_opt"]), REQ_TEXT[lv["level"]]])
    doc.table(rows, [1100, 2700, 2300, 3198])
    doc.para("说明：“缺口”是已经确认不满足的项；“待证”是信息没给全或证据还没坐实的项，保守口径下不计入。", style="Note")

    # 二、基本条件
    doc.heading("二、基本条件核查", 1)
    lv0 = res["levels"][0]
    rows = [["条件", "结果", "说明"]]
    for chk in lv0["checks"]:
        if chk["kind"] in ("硬门槛", "门槛") and chk["id"] != "G-prereq":
            rows.append([chk["text"] + ("（一票否决项）" if chk["kind"] == "硬门槛" else ""), _state_cell(chk["state"]),
                         chk["detail"] if chk["state"] == "hit" else (chk["fix"] or chk["detail"])])
    g = res["gates"]
    rows.append(["当前已获评层级", {"t": g.get("current_level") or "无", "align": "center"},
                 ("获评时间：%s" % g["current_level_date"]) if g.get("current_level_date") else "—"])
    doc.table(rows, [3900, 1100, 4298])

    # 三、场景盘点
    doc.heading("三、典型场景盘点", 1)
    scs = [s for s in res["scenarios"] if s["grade"] != "未建"]
    pend = [s for s in scs if not s["confirmed"]]
    gc = {k: sum(1 for s in scs if s["grade"] == k) for k in ("A", "B", "C", "D")}
    segs_cov = [R.seg_name(k) for k, v in res["by_seg"].items() if v["count"]]
    doc.para("共盘点在用场景实例%d个（其中待证%d个），涉及%d个不同场景，覆盖%s。A级%d个、B级%d个、C级%d个、D级%d个。" % (
        len(scs), len(pend), len({s["id"] for s in scs}), "、".join(segs_cov) or "—", gc["A"], gc["B"], gc["C"], gc["D"]), first_indent=True)
    a = res["ai"]
    doc.para("应用人工智能技术场景比例（保守口径）：实例口径%d/%d=%.1f%%，场景名称口径%d/%d=%.1f%%，取低值%.1f%%。卓越级要求≥30%%，领航级要求≥60%%。" % (
        a["ai_instances"], a["instances"], a["ratio_instance"] * 100, a["ai_distinct"], a["distinct"], a["ratio_name"] * 100, a["ratio"] * 100),
        first_indent=True)
    rows = [["环节", "场景", "企业实例", "等级", "AI", "月数", "说明"]]
    order = {s["key"]: i for i, s in enumerate(R.SEGMENTS)}
    for s in sorted(scs, key=lambda x: (order[x["seg"]], x["id"])):
        gfill = {"A": OK_F, "B": "EAF1F8", "C": None, "D": "F1F1F1"}.get(s["grade"])
        note = []
        if not s["confirmed"]:
            note.append("待证")
        if s["systems"]:
            note.append(s["systems"])
        if s["ai"] and s["ai_types"]:
            note.append("AI：" + "、".join(s["ai_types"]))
        if s["evidence"]:
            note.append("证据：" + s["evidence"])
        rows.append([R.seg_name(s["seg"]), "%d %s" % (s["id"], s["scene"]), s["name"],
                     {"t": s["grade"], "fill": gfill, "align": "center", "b": True},
                     {"t": "是" if (s["ai"] and s["grade"] in ("A", "B")) else ("标注未计" if s["ai"] else ""), "align": "center"},
                     {"t": fmt(s["months"]) if s["months"] is not None else "—", "align": "center"},
                     "；".join(note)])
    doc.table(rows, [900, 1700, 1800, 600, 700, 600, 2998], size=8.5)
    doc.para("分级口径：" + "；".join(R.GRADE_TEXT[k] for k in ("A", "B", "C", "D")) + "。AI场景须达到B级及以上才计入。", style="Note")

    # 四、要点对照
    doc.heading("四、分级要点对照", 1)
    focus_lvs = [focus] if focus else [x for x in (rec.get("apply_level"), rec.get("next_level")) if x and x != "基础级"]
    if not focus_lvs:
        focus_lvs = ["先进级"]
    for idx, lvname in enumerate(focus_lvs):
        lv = next(x for x in res["levels"] if x["level"] == lvname)
        doc.heading("（%s）%s：%s" % ("一二三四"[idx], lvname, lv["verdict"]), 2)
        rows = [["门槛、标志性要求与成效", "结果", "情况与补法"]]
        for chk in lv["checks"]:
            if chk["kind"] in ("硬门槛", "门槛") and chk["state"] == "hit" and chk["id"] not in ("G-cmmm", "G-prereq"):
                continue
            if chk["kind"] == "环节":
                continue
            if chk["state"] == "hit":
                info = chk["detail"]
            elif chk["state"] == "unknown":
                info = chk["detail"] or chk["fix"]
            else:
                info = "；".join(x for x in (chk["detail"] if chk["detail"].startswith("当前") else "", chk["fix"]) if x)
            rows.append([chk["text"], _state_cell(chk["state"]), info])
        doc.table(rows, [3500, 1000, 4798], size=8.5)
        rows = [["环节", "要点", "结果", "依据或补法"]]
        for sg in lv["segments"]:
            tag = "%s\n%s（%d/%d）" % (sg["name"], sg["state"] if sg["required"] else "选做", sg["hit"], sg["total"])
            for i, p in enumerate(sg["points"]):
                rows.append([{"t": tag if i == 0 else "", "b": i == 0}, "%s %s" % (p["id"], p["text"]), _state_cell(p["state"]),
                             p["by"] if p["state"] == "hit" else (p["by"] + "；" if p["by"] else "") + p["fix"]])
        doc.table(rows, [1300, 3300, 1000, 3698], size=8.5)
        if lv.get("local"):
            doc.para("所在地附加要求", bold=True, color=ACCENT, after=60, keep_next=True)
            for loc in lv["local"]:
                for n in loc["notes"]:
                    doc.bullet("%s：%s" % (loc["region"], n))
                doc.para("来源：" + loc["source"], style="Note")
        comp = [x for x in res.get("competition", []) if x["level"] == lvname]
        if comp:
            doc.para("竞争力观察（非官方评分）", bold=True, color=ACCENT, after=60, keep_next=True)
            for g in comp[0]["good"]:
                doc.bullet(g, mark="＋", color=OK)
            for w in comp[0]["weak"]:
                doc.bullet(w, mark="－", color=BAD)
            doc.para(comp[0]["note"], style="Note")
    doc.para("要点是对《要素条件（2026年版）》各环节建设内容的逐条归纳；一个环节命中≥2/3视为达标，这是本技能的研判口径，不是官方评分。", style="Note")

    # 五、关键指标
    doc.heading("五、关键绩效指标", 1)
    if res["kpis"]:
        rows = [["指标", "建设前", "当前", "变化", "统计期与口径", "提示"]]
        for k in res["kpis"]:
            u = k["unit"]
            fb = (fmt(k["before"]) + ("%" if u == "%" else "")) if k["before"] is not None else "—"
            fa = (fmt(k["after"]) + ("%" if u == "%" else "")) if k["after"] is not None else "—"
            col = OK if (k["change"] is not None and k["change"] > 0) else (BAD if k["change"] is not None else None)
            rows.append([k["name"] + ("" if u in ("", "%") else "（%s）" % u), {"t": fb, "align": "center"}, {"t": fa, "align": "center"},
                         {"t": k["text"], "color": col}, "；".join(x for x in (k["period"], k["basis"]) if x) or "—",
                         {"t": "；".join(k["warn"]), "color": WAIT if k["warn"] else None}])
        doc.table(rows, [1700, 900, 900, 1900, 2100, 1798], size=8.5)
    else:
        doc.para("尚未提供指标数据。申报书要求填写建设前与当前值，建议先建立指标台账。")
    if res["kpi_missing_required"]:
        doc.para("常见必填但还没有的指标：" + "、".join(res["kpi_missing_required"]) + "（以当年申报模板为准）。", style="Note")

    # 六、风险提示
    doc.heading("六、风险提示", 1)
    if res["flags"]:
        colors = {"高": BAD, "中": WAIT, "低": "5B6773"}
        for f in sorted(res["flags"], key=lambda x: "高中低".index(x["level"])):
            doc.para([("[%s] " % f["level"], {"b": True, "color": colors[f["level"]]}), (f["text"], {})], after=80)
    else:
        doc.para("未发现明显的一致性问题。")

    # 七、材料准备清单
    doc.heading("七、申报材料准备清单", 1)
    if res.get("materials"):
        for lvname, items in res["materials"].items():
            doc.heading("%s" % lvname, 2)
            rows = [["材料", "状态"]]
            for it in items:
                st = it["state"]
                col = OK if st.startswith("有") else (WAIT if st else None)
                rows.append([it["item"], {"t": st or "—", "color": col, "align": "center"}])
            doc.table(rows, [7598, 1700], size=8.5)
        doc.para("清单按国家通知、各地转发件和往年平台设置整理；份数、装订、截止时间以当年当地通知为准。", style="Note")
    else:
        doc.para("当前没有明确的申报目标层级。")

    # 八、时间窗与倒排
    doc.heading("八、当前时间窗与倒排计划", 1)
    if res.get("calendar"):
        rows = [["状态", "事项", "时间"]]
        for e in res["calendar"]:
            span = e["start"] if e["start"] == e["end"] else "%s 至 %s" % (e["start"], e["end"])
            rows.append([{"t": e["status"], "align": "center", "b": e["status"] == "进行中"}, e["text"], {"t": span, "align": "center"}])
        doc.table(rows, [1100, 5598, 2600], size=8.5)
        doc.para("标“预计”的按往年节奏推测，以当年通知为准。", style="Note")
    if not res["plans"]:
        doc.para("当前没有需要倒排的申报节点。")
    for p in res["plans"]:
        doc.heading("%s（截止时间为估计：%s）" % (p["level"], p["deadline_est"]), 2)
        if p.get("note"):
            doc.para(p["note"], color=WAIT, bold=True)
        rows = [["日期", "事项", "状态"]]
        for s in p["steps"]:
            rows.append([{"t": s["date"], "align": "center"}, s["text"], {"t": s["status"] or "", "align": "center"}])
        doc.table(rows, [1500, 6798, 1000], size=9)
        doc.para("往年节奏：" + p["history"], style="Note")

    # 九、依据与说明
    doc.heading("九、依据与说明", 1)
    for b in R.BASIS:
        doc.bullet("%s%s%s" % (b["name"], ("（%s）" % b["no"]) if b["no"] else "", ("，" + b["date"]) if b["date"] else ""))
    doc.para("本报告按公开政策文件和企业提供的信息推算，不是主管部门的评审结论，最终以评审和现场核查为准。"
             "企业对申报材料真实性负责；依据《智能工厂梯度培育管理办法（暂行）》，材料或数据造假的，已认定的直接取消，且至少3年内不得再次申报。",
             style="Note")
    doc.save(path, footer_text="%s　智能工厂研判报告" % (c.get("name") or ""))
    return path
