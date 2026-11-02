# -*- coding: utf-8 -*-
"""读取填好的研判底稿（assets/workbook.xlsx），转成研判输入。只用标准库，Excel、WPS 保存的文件都能读。"""
import re
import zipfile
import xml.etree.ElementTree as ET

import zngc_rules as R

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "pr": "http://schemas.openxmlformats.org/package/2006/relationships"}


def _col(ref):
    letters = re.match(r"([A-Z]+)", ref).group(1)
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def _row(ref):
    return int(re.search(r"(\d+)$", ref).group(1))


def read_workbook(path):
    """返回 {工作表名: {(行, 列): 值}}，值为字符串或数字（公式取缓存值）。"""
    z = zipfile.ZipFile(path)
    names = set(z.namelist())
    shared = []
    if "xl/sharedStrings.xml" in names:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    target = {}
    for r in rels.findall("pr:Relationship", NS):
        t = r.get("Target")
        t = t.lstrip("/")
        if not t.startswith("xl/"):
            t = "xl/" + t
        target[r.get("Id")] = t
    out = {}
    for sh in wb.find("m:sheets", NS).findall("m:sheet", NS):
        rid = sh.get("{%s}id" % NS["r"])
        p = target.get(rid)
        if not p or p not in names:
            continue
        cells = {}
        root = ET.fromstring(z.read(p))
        for c in root.iter("{%s}c" % NS["m"]):
            ref = c.get("r")
            if not ref:
                continue
            t = c.get("t")
            v = c.find("m:v", NS)
            val = None
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter("{%s}t" % NS["m"]))
            elif t in ("str", "e") and v is not None:
                val = v.text
            elif t == "b" and v is not None:
                val = "是" if v.text == "1" else "否"
            elif v is not None and v.text is not None:
                try:
                    val = float(v.text)
                except ValueError:
                    val = v.text
            if isinstance(val, str):
                val = val.strip()
                if val == "":
                    val = None
            if val is not None:
                cells[(_row(ref), _col(ref))] = val
        out[sh.get("name")] = cells
    return out


def _yn(v):
    if v is None:
        return None
    s = str(v).strip()
    if s in ("是", "有", "Y", "y", "1", "1.0"):
        return True
    if s in ("否", "无", "没有", "N", "n", "0", "0.0"):
        return False
    return None


def _clean_num(v):
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def workbook_to_input(path):
    wb = read_workbook(path)
    warn = []
    data = {"company": {}, "gates": {}, "scenarios": [], "extras": {}, "kpis": [], "investment": {}, "target": "auto", "local": {}}

    sh = wb.get("基本条件", {})
    max_r = max([r for r, _ in sh] or [0])
    for r in range(4, max_r + 1):
        key, val = sh.get((r, 4)), sh.get((r, 2))
        if not key or val is None:
            continue
        val = _clean_num(val)
        if key == "target":
            data["target"] = "auto" if str(val).startswith("自动") else str(val)
        elif key.startswith("company."):
            data["company"][key.split(".", 1)[1]] = str(val)
        elif key.startswith("local."):
            data["local"][key.split(".", 1)[1]] = _yn(val)
        elif key.startswith("investment."):
            data["investment"][key.split(".", 1)[1]] = val
        elif key.startswith("gates."):
            k = key.split(".", 1)[1]
            if k in ("current_level", "current_level_date", "cmmm_source"):
                data["gates"][k] = str(val)
            elif k in ("cmmm_level", "cmmm_score"):
                data["gates"][k] = val
            else:
                data["gates"][k] = _yn(val)

    sh = wb.get("场景盘点", {})
    max_r = max([r for r, _ in sh] or [0])
    for r in range(5, max_r + 1):
        sid = sh.get((r, 1))
        try:
            sid = int(float(sid))
        except (TypeError, ValueError):
            continue
        if not 1 <= sid <= 40:
            continue
        has = _yn(sh.get((r, 5)))
        if has is not True:
            continue
        name = sh.get((r, 6))
        if not name:
            name = sh.get((r, 4)) or ""
            warn.append("第%d行（%d号场景）没写实例名称，暂用场景名代替" % (r, sid))
        types = sh.get((r, 11)) or ""
        sc = {"id": sid, "name": str(name), "systems": str(sh.get((r, 7)) or ""),
              "linked": _yn(sh.get((r, 8))) is True, "model": _yn(sh.get((r, 9))) is True,
              "ai": _yn(sh.get((r, 10))) is True,
              "ai_types": [t for t in re.split(r"[、,，;；/\s]+", str(types)) if t],
              "quantified": _yn(sh.get((r, 12))) is True, "months": _clean_num(sh.get((r, 13))),
              "confirmed": _yn(sh.get((r, 14))) is not True, "declare": _yn(sh.get((r, 15))) is not False,
              "evidence": str(sh.get((r, 16)) or "")}
        if sc["ai"] and not sc["ai_types"]:
            warn.append("第%d行标了应用AI但没写AI技术类型" % r)
        data["scenarios"].append(sc)

    sh = wb.get("能力补充", {})
    max_r = max([r for r, _ in sh] or [0])
    types = {e["key"]: e["type"] for e in R.EXTRAS}
    for r in range(4, max_r + 1):
        key, val = sh.get((r, 5)), sh.get((r, 2))
        if not key or val is None or key not in types:
            continue
        if types[key] == "bool":
            data["extras"][key] = _yn(val)
        else:
            data["extras"][key] = _clean_num(val)

    sh = wb.get("关键指标", {})
    max_r = max([r for r, _ in sh] or [0])
    kinds = {k["name"]: k["kind"] for k in R.KPIS}
    for r in range(5, max_r + 1):
        name = sh.get((r, 1))
        b, a = sh.get((r, 4)), sh.get((r, 5))
        if not name or (b is None and a is None):
            continue
        kind = kinds.get(str(name), "value")
        if kind in ("rate", "level"):
            b = None if b is None else "%s%%" % _clean_num(b)
            a = None if a is None else "%s%%" % _clean_num(a)
        data["kpis"].append({"name": str(name), "before": _clean_num(b), "after": _clean_num(a),
                             "unit": str(sh.get((r, 3)) or ""), "period": str(sh.get((r, 8)) or ""),
                             "basis": str(sh.get((r, 9)) or "")})
    if not data["scenarios"]:
        warn.append("场景盘点里没有任何“有没有=是”的行")
    data["_warnings"] = warn
    return data


# ---------------------------------------------------------------- 写 xlsx（只用标准库）
def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _colname(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(ref, v, bold=False):
    st = ' s="1"' if bold else ""
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return '<c r="%s"%s t="inlineStr"><is><t>%s</t></is></c>' % (ref, st, "是" if v else "否")
    if isinstance(v, (int, float)):
        return '<c r="%s"%s><v>%s</v></c>' % (ref, st, repr(float(v)).rstrip("0").rstrip(".") or "0")
    s = str(v)
    # 纯数字文本（如 "2"）按数字写，避免左上角绿三角
    if re.fullmatch(r"-?\d+(\.\d+)?", s) and not s.startswith("0") and len(s) < 15:
        return '<c r="%s"%s><v>%s</v></c>' % (ref, st, s)
    return ('<c r="%s"%s t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>'
            % (ref, st, _esc(s)))


def write_rows(path, rows, sheet_name="Sheet1", widths=None, bold_first=True):
    """把二维表写成真正的 .xlsx。rows 第一行为表头；宽度按内容估算，首行加粗并冻结。"""
    rows = [list(r) for r in rows if r is not None]
    if not rows:
        rows = [[""]]
    ncol = max(len(r) for r in rows)
    if widths is None:
        widths = []
        for c in range(ncol):
            longest = 0
            for r in rows:
                v = r[c] if c < len(r) else ""
                if v is None:
                    continue
                w = sum(2 if ord(ch) > 127 else 1 for ch in str(v))
                longest = max(longest, w)
            widths.append(min(max(longest + 2, 8), 52))
    cols = "".join('<col min="%d" max="%d" width="%d" customWidth="1"/>' % (i + 1, i + 1, w)
                   for i, w in enumerate(widths))
    body = []
    for ri, r in enumerate(rows, 1):
        cells = "".join(_cell("%s%d" % (_colname(ci + 1), ri), r[ci] if ci < len(r) else "",
                              bold=(bold_first and ri == 1))
                        for ci in range(ncol))
        body.append('<row r="%d">%s</row>' % (ri, cells))
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<sheetPr><outlinePr summaryBelow="1" summaryRight="1"/></sheetPr>'
             '<sheetViews><sheetView workbookViewId="0"%s>'
             '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
             '</sheetView></sheetViews>'
             '<sheetFormatPr defaultRowHeight="15"/>'
             '<cols>%s</cols><sheetData>%s</sheetData></worksheet>'
             % (' tabSelected="1"' if True else "", cols, "".join(body)))
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
          '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>')
    wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
          '<sheets><sheet name="%s" sheetId="1" r:id="rId1"/></sheets></workbook>' % _esc(sheet_name[:31]))
    wbr = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
           '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
           '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
           '</Relationships>')
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<fonts count="2"><font><sz val="11"/><name val="等线"/></font>'
              '<font><b/><sz val="11"/><name val="等线"/></font></fonts>'
              '<fills count="2"><fill><patternFill patternType="none"/></fill>'
              '<fill><patternFill patternType="gray125"/></fill></fills>'
              '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
              '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
              '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
              '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
              '<cellStyles count="1"><cellStyle name="常规" xfId="0" builtinId="0"/></cellStyles>'
              '</styleSheet>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", wbr)
        z.writestr("xl/styles.xml", styles)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return path
