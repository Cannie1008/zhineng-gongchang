# -*- coding: utf-8 -*-
"""申报书草稿自查：字数、需要证据的说法、数字与研判是否一致、AI说法有没有对应场景、待补充占位。"""
import re

import zngc_rules as R
from zngc_engine import kpi_def

TEMPLATES = {"国家卓越级": "国家平台·卓越级（2025年度设置）", "上海先进级": "上海·先进级申报书（2026年）"}
AI_WORDS = {"大模型": "生成式人工智能", "生成式": "生成式人工智能", "智能体": "工业智能体", "深度学习": "深度学习",
            "机器视觉": "机器视觉", "视觉检测": "机器视觉", "强化学习": "强化学习", "知识图谱": "知识工程",
            "机器学习": "统计机器学习"}
SECRET_HINTS = ["合同金额", "单价", "配方", "客户名单", "报价单", "成本价"]


def read_text(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def count_chars(s):
    return len(re.sub(r"\s", "", s))


def split_sections(text):
    """按【标题】、# 标题、“一、标题”切分。"""
    pat = re.compile(r"^\s*(?:【([^】]{1,30})】|#{1,4}\s*(.{1,30})|[一二三四五六七八九十]+、\s*(.{1,30}))\s*$", re.M)
    marks = [(m.start(), m.end(), next(g for g in m.groups() if g)) for m in pat.finditer(text)]
    secs = []
    for i, (s, e, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        secs.append((name.strip(), text[e:end]))
    return secs


def check(text, template="国家卓越级", result=None):
    issues = []

    def add(level, msg):
        issues.append({"level": level, "text": msg})

    limits = R.PLATFORM_LIMITS.get(TEMPLATES.get(template, template), [])
    for name, body in split_sections(text):
        lim = next((n for n in limits if n[0] in name or name in n[0]), None)
        n = count_chars(body)
        if lim:
            if n > lim[1]:
                add("高", "“%s”%d字，超过上限%d字（%s）" % (name, n, lim[1], TEMPLATES.get(template, template)))
            elif n > lim[1] * 0.95:
                add("低", "“%s”%d字，接近上限%d字，平台计数可能含标点，留点余量" % (name, n, lim[1]))

    for w in R.HYPE_WORDS:
        k = text.count(w)
        if k:
            add("中", "“%s”出现%d次：需要查新报告、第三方评价或权威排名支撑，没有就改成可核实的说法（写具体数据和对比对象）" % (w, k))

    # 100% 是正常指标值，但满分项是评审重点核查对象，给提示而不是当夸大
    n_full = len(re.findall(r"(?<![\d.])100(?:\.0+)?\s*%", text))
    if n_full:
        add("低", "出现%d处“100%%”：满分指标要能拿出台账或系统截图，评审通常会重点抽查这几项" % n_full)

    for sent in re.split(r"[。！？\n]", text):
        for w in R.VAGUE_WORDS:
            if w in sent and not re.search(r"\d", sent):
                add("低", "“%s……”用了“%s”但没有数字，评审看不出幅度" % (sent.strip()[:24], w))
                break

    ph = len(re.findall(r"【待补充[^】]*】|XX|××|＊＊|TODO", text))
    if ph:
        add("中", "还有%d处待补充的占位，提交前必须替换成真实信息" % ph)

    for w in SECRET_HINTS:
        if w in text:
            add("低", "出现“%s”：申报材料不得涉及商业秘密，确认是否需要删去或脱敏" % w)

    if result:
        kmap = {k["name"]: k for k in result.get("kpis", [])}
        rx = re.compile(r"([\u4e00-\u9fa5A-Za-z]{2,14}?)(?:由[^，。；]{0,20})?(提升|提高|增长|增加|降低|下降|缩短|减少)了?约?(\d+(?:\.\d+)?)\s*(%|个百分点)")
        for m in rx.finditer(text):
            name_raw, val, unit = m.group(1), float(m.group(3)), m.group(4)
            df = None
            for k in R.KPIS:
                if k["name"] in name_raw or name_raw.endswith(k["name"]):
                    df = k
                    break
            if not df:
                for alias, real in R.KPI_ALIASES.items():
                    if alias in name_raw:
                        df = kpi_def(real)
                        break
            if not df or df["name"] not in kmap:
                continue
            k = kmap[df["name"]]
            if unit == "%" and k.get("change") is not None:
                rel = k["change"] * 100
                if abs(val - rel) > 0.6:
                    if k.get("pp") is not None and abs(val - abs(k["pp"])) <= 0.15:
                        add("高", "“%s”：%.1f更像是百分点变化（测算%+.1f个百分点），相对变化是%.1f%%，不要混用" % (m.group(0), val, k["pp"], rel))
                    else:
                        add("高", "“%s”与测算不一致：按填报数据是%s" % (m.group(0), k["text"]))
            elif unit == "个百分点" and k.get("pp") is not None and abs(val - abs(k["pp"])) > 0.15:
                add("高", "“%s”与测算不一致：测算为%+.1f个百分点" % (m.group(0), k["pp"]))
        # 绝对值表述：“交付率达到99.5%”“不良率为0.8%”要和填报的当前值对得上
        rx_abs = re.compile(r"([\u4e00-\u9fa5A-Za-z]{2,14}?)(?:已)?(?:达到|达|为|是|提升至|提高至|降至|下降到)"
                            r"约?(\d+(?:\.\d+)?)\s*(%|个百分点)")
        # 门槛类表述（“卓越级要求≥30%”“不低于…”）不是企业自己的数据，跳过
        REQ_HINT = re.compile(r"要求|须|需|不低于|不少于|不少于|门槛|标准|规定|目标|指引|条件")
        for m in rx_abs.finditer(text):
            sent = re.split(r"[。！？\n]", text[:m.start()])[-1] + text[m.start():m.end()]
            sent = sent + re.split(r"[。！？\n]", text[m.end():])[0]
            if REQ_HINT.search(sent):
                continue
            name_raw, val, unit = m.group(1), float(m.group(2)), m.group(3)
            df = None
            for k in R.KPIS:
                if k["name"] in name_raw or name_raw.endswith(k["name"]):
                    df = k
                    break
            if not df:
                for alias, real in R.KPI_ALIASES.items():
                    if alias in name_raw:
                        df = kpi_def(real)
                        break
            if not df or df["name"] not in kmap:
                continue
            k = kmap[df["name"]]
            cur = k.get("after")
            if cur is None:
                continue
            if unit == "%" and k.get("kind") in ("rate", "level") and abs(val - cur) > 0.5:
                add("高", "“%s”与填报的当前值不一致：按填报数据当前是%.1f%%" % (m.group(0), cur))
            elif unit == "个百分点" and k.get("pp") is not None and abs(val - abs(k["pp"])) > 0.15:
                add("高", "“%s”把百分点写成了绝对值：测算变化为%+.1f个百分点，当前值%.1f%%"
                    % (m.group(0), k["pp"], cur))
        m = re.search(r"人工智能[^。；\n]{0,12}?(?:场景)?(?:占比|比例|覆盖)[^0-9]{0,6}(\d+(?:\.\d+)?)\s*%", text)
        if m and result.get("ai"):
            sent = (re.split(r"[。！？\n]", text[:m.start()])[-1] + m.group(0)
                    + re.split(r"[。！？\n]", text[m.end():])[0])
            if not REQ_HINT.search(sent):
                claimed, calc = float(m.group(1)), result["ai"]["ratio"] * 100
                if abs(claimed - calc) > 1:
                    add("高", "文中AI场景比例写%.1f%%，按场景盘点保守口径算是%.1f%%：两处要一致" % (claimed, calc))
        types = set()
        for s in result.get("scenarios", []):
            if s.get("ai") and s.get("grade") in ("A", "B"):
                types.update(s.get("ai_types") or [])
        for w, t in AI_WORDS.items():
            if w in text and t not in types:
                add("中", "文中提到“%s”，但场景盘点里没有达到B级、标注为“%s”的场景：要么补盘点，要么删掉这个说法" % (w, t))
    order = {"高": 0, "中": 1, "低": 2}
    issues.sort(key=lambda x: order[x["level"]])
    return issues
