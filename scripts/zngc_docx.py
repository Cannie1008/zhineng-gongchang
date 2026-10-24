# -*- coding: utf-8 -*-
"""极简 Word（.docx）写入器：只用标准库，满足研判报告需要的标题、段落、表格、页码。"""
import datetime as _dt
import zipfile
from xml.sax.saxutils import escape

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

FONT_BODY = "宋体"
FONT_HEAD = "黑体"
FONT_LATIN = "Arial"
ACCENT = "1F3A5F"
GRID = "9AA7B4"
HEAD_FILL = "DCE3EA"
CONTENT_W = 9298  # A4 宽 11906 减去左右边距 1304×2（单位：缇）


def _t(text):
    text = "" if text is None else str(text)
    return '<w:t xml:space="preserve">%s</w:t>' % escape(text)


def _rpr(o):
    o = o or {}
    parts = []
    font = o.get("font")
    if font:
        parts.append('<w:rFonts w:ascii="%s" w:hAnsi="%s" w:eastAsia="%s"/>' % (FONT_LATIN, FONT_LATIN, font))
    if o.get("b"):
        parts.append("<w:b/><w:bCs/>")
    if o.get("i"):
        parts.append("<w:i/>")
    if o.get("color"):
        parts.append('<w:color w:val="%s"/>' % o["color"])
    if o.get("size"):
        hp = int(round(o["size"] * 2))
        parts.append('<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (hp, hp))
    return "<w:rPr>%s</w:rPr>" % "".join(parts) if parts else ""


def _runs(content, base=None):
    """content 可以是字符串，也可以是 [(文字, {b,color,size,font}), ...]。换行符拆成 <w:br/>。"""
    base = base or {}
    if content is None:
        content = ""
    if isinstance(content, str):
        content = [(content, {})]
    out = []
    for item in content:
        if isinstance(item, str):
            text, o = item, {}
        else:
            text, o = item[0], (item[1] if len(item) > 1 else {})
        opt = dict(base)
        opt.update(o)
        rpr = _rpr(opt)
        pieces = str(text).split("\n")
        for i, piece in enumerate(pieces):
            if i:
                out.append("<w:r>%s<w:br/></w:r>" % rpr)
            out.append("<w:r>%s%s</w:r>" % (rpr, _t(piece)))
    return "".join(out)


class Doc(object):
    def __init__(self, title=""):
        self.title = title
        self.body = []

    def heading(self, text, level=1):
        self.body.append('<w:p><w:pPr><w:pStyle w:val="Heading%d"/></w:pPr>%s</w:p>' % (level, _runs(text)))

    def para(self, content, align=None, size=None, color=None, bold=False, after=None, before=None,
             first_indent=False, keep_next=False, style=None, shade=None):
        ppr = []
        if style:
            ppr.append('<w:pStyle w:val="%s"/>' % style)
        if keep_next:
            ppr.append("<w:keepNext/>")
        if shade:
            ppr.append('<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % shade)
        if after is not None or before is not None:
            ppr.append('<w:spacing w:before="%d" w:after="%d"/>' % (before or 0, after if after is not None else 120))
        if first_indent:
            ppr.append('<w:ind w:firstLine="420"/>')
        if align:
            ppr.append('<w:jc w:val="%s"/>' % align)
        base = {}
        if size:
            base["size"] = size
        if color:
            base["color"] = color
        if bold:
            base["b"] = True
        self.body.append("<w:p>%s%s</w:p>" % ("<w:pPr>%s</w:pPr>" % "".join(ppr) if ppr else "", _runs(content, base)))

    def bullet(self, content, mark="·", color=None):
        self.para([(mark + " ", {"color": color or ACCENT, "b": True})] + (
            [(content, {})] if isinstance(content, str) else list(content)), after=60)

    def page_break(self):
        self.body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')

    def table(self, rows, widths, header=True, size=9, zebra=False):
        """rows: [[cell,...],...]；cell 为字符串、runs 列表，或 {"t":..., "fill":..., "color":..., "b":..., "align":...}。"""
        total = sum(widths)
        if total != CONTENT_W:
            widths = [int(w * CONTENT_W / float(total)) for w in widths]
            widths[-1] += CONTENT_W - sum(widths)
        x = ['<w:tbl><w:tblPr><w:tblW w:w="%d" w:type="dxa"/>' % CONTENT_W]
        x.append("<w:tblBorders>")
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
            x.append('<w:%s w:val="single" w:sz="4" w:space="0" w:color="%s"/>' % (side, GRID))
        x.append("</w:tblBorders>")
        x.append('<w:tblLayout w:type="fixed"/>')
        x.append('<w:tblCellMar><w:top w:w="40" w:type="dxa"/><w:left w:w="80" w:type="dxa"/>'
                 '<w:bottom w:w="40" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar>')
        x.append('<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="0" w:lastColumn="0" w:noHBand="0" w:noVBand="1"/>')
        x.append("</w:tblPr><w:tblGrid>")
        for w in widths:
            x.append('<w:gridCol w:w="%d"/>' % w)
        x.append("</w:tblGrid>")
        for ri, row in enumerate(rows):
            is_head = header and ri == 0
            x.append("<w:tr>")
            trpr = ["<w:cantSplit/>"]
            if is_head:
                trpr.append("<w:tblHeader/>")
            x.append("<w:trPr>%s</w:trPr>" % "".join(trpr))
            for ci, cell in enumerate(row):
                if isinstance(cell, dict):
                    content, fill, color = cell.get("t", ""), cell.get("fill"), cell.get("color")
                    bold, align = cell.get("b", False), cell.get("align")
                else:
                    content, fill, color, bold, align = cell, None, None, False, None
                if is_head:
                    fill = fill or HEAD_FILL
                    bold = True
                elif zebra and ri % 2 == 0 and not fill:
                    fill = "F4F6F8"
                tcpr = ['<w:tcW w:w="%d" w:type="dxa"/>' % widths[ci]]
                if fill:
                    tcpr.append('<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % fill)
                tcpr.append('<w:vAlign w:val="center"/>')
                base = {"size": size}
                if color:
                    base["color"] = color
                if bold:
                    base["b"] = True
                if is_head:
                    base["font"] = FONT_HEAD
                ppr = '<w:pPr><w:spacing w:before="0" w:after="0" w:line="276" w:lineRule="auto"/>%s</w:pPr>' % (
                    '<w:jc w:val="%s"/>' % align if align else "")
                x.append("<w:tc><w:tcPr>%s</w:tcPr><w:p>%s%s</w:p></w:tc>" % ("".join(tcpr), ppr, _runs(content, base)))
            x.append("</w:tr>")
        x.append("</w:tbl>")
        self.body.append("".join(x))
        self.body.append('<w:p><w:pPr><w:spacing w:before="0" w:after="60"/></w:pPr></w:p>')

    # ------------------------------------------------------------ 打包
    def save(self, path, footer_text=""):
        doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<w:document xmlns:w="%s" xmlns:r="%s"><w:body>%s'
               '<w:sectPr><w:footerReference w:type="default" r:id="rId3"/>'
               '<w:pgSz w:w="11906" w:h="16838"/>'
               '<w:pgMar w:top="1361" w:right="1304" w:bottom="1361" w:left="1304" w:header="851" w:footer="680" w:gutter="0"/>'
               '</w:sectPr></w:body></w:document>') % (W_NS, R_NS, "".join(self.body))
        footer = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                  '<w:ftr xmlns:w="%s" xmlns:r="%s"><w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
                  '%s<w:r><w:rPr><w:sz w:val="16"/></w:rPr><w:t xml:space="preserve">第 </w:t></w:r>'
                  '<w:r><w:rPr><w:sz w:val="16"/></w:rPr><w:fldChar w:fldCharType="begin"/></w:r>'
                  '<w:r><w:rPr><w:sz w:val="16"/></w:rPr><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
                  '<w:r><w:rPr><w:sz w:val="16"/></w:rPr><w:fldChar w:fldCharType="separate"/></w:r>'
                  '<w:r><w:rPr><w:sz w:val="16"/></w:rPr><w:t>1</w:t></w:r>'
                  '<w:r><w:rPr><w:sz w:val="16"/></w:rPr><w:fldChar w:fldCharType="end"/></w:r>'
                  '<w:r><w:rPr><w:sz w:val="16"/></w:rPr><w:t xml:space="preserve"> 页</w:t></w:r></w:p></w:ftr>') % (
            W_NS, R_NS, ('<w:r><w:rPr><w:color w:val="7A8794"/><w:sz w:val="16"/></w:rPr>%s</w:r>' % _t(footer_text + "　　")) if footer_text else "")
        now = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
                'xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                '<dc:title>%s</dc:title><dc:creator>智能工厂研判与申报技能</dc:creator>'
                '<dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created>'
                '<dcterms:modified xsi:type="dcterms:W3CDTF">%s</dcterms:modified></cp:coreProperties>') % (escape(self.title), now, now)
        app = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
               'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>zngc</Application></Properties>')
        ctypes = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                  '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                  '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                  '<Default Extension="xml" ContentType="application/xml"/>'
                  '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                  '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
                  '<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
                  '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
                  '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
                  '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
                  '</Types>')
        rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
                '</Relationships>')
        doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>'
                    '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>'
                    '</Relationships>')
        settings = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<w:settings xmlns:w="%s"><w:defaultTabStop w:val="420"/>'
                    '<w:characterSpacingControl w:val="compressPunctuation"/><w:compat>'
                    '<w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"/>'
                    '</w:compat></w:settings>') % W_NS
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", ctypes)
            z.writestr("_rels/.rels", rels)
            z.writestr("word/document.xml", doc)
            z.writestr("word/_rels/document.xml.rels", doc_rels)
            z.writestr("word/styles.xml", _styles())
            z.writestr("word/settings.xml", settings)
            z.writestr("word/footer1.xml", footer)
            z.writestr("docProps/core.xml", core)
            z.writestr("docProps/app.xml", app)


def _styles():
    def heading(n, size, before, after, color=ACCENT):
        hp = int(size * 2)
        return ('<w:style w:type="paragraph" w:styleId="Heading%d"><w:name w:val="heading %d"/>'
                '<w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/>'
                '<w:pPr><w:keepNext/><w:keepLines/><w:spacing w:before="%d" w:after="%d"/><w:outlineLvl w:val="%d"/></w:pPr>'
                '<w:rPr><w:rFonts w:ascii="%s" w:hAnsi="%s" w:eastAsia="%s"/><w:b/><w:bCs/><w:color w:val="%s"/>'
                '<w:sz w:val="%d"/><w:szCs w:val="%d"/></w:rPr></w:style>') % (
            n, n, before, after, n - 1, FONT_LATIN, FONT_LATIN, FONT_HEAD, color, hp, hp)
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:styles xmlns:w="%s"><w:docDefaults><w:rPrDefault><w:rPr>'
            '<w:rFonts w:ascii="%s" w:hAnsi="%s" w:eastAsia="%s" w:cs="%s"/>'
            '<w:color w:val="22272E"/><w:sz w:val="21"/><w:szCs w:val="21"/><w:lang w:val="en-US" w:eastAsia="zh-CN"/>'
            '</w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="300" w:lineRule="auto"/>'
            '</w:pPr></w:pPrDefault></w:docDefaults>'
            '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
            '%s%s%s'
            '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:qFormat/>'
            '<w:pPr><w:spacing w:before="0" w:after="120"/></w:pPr>'
            '<w:rPr><w:rFonts w:ascii="%s" w:hAnsi="%s" w:eastAsia="%s"/><w:b/><w:color w:val="%s"/><w:sz w:val="44"/><w:szCs w:val="44"/></w:rPr></w:style>'
            '<w:style w:type="paragraph" w:styleId="Note"><w:name w:val="Note"/><w:basedOn w:val="Normal"/>'
            '<w:rPr><w:color w:val="5B6773"/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>'
            '<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/><w:uiPriority w:val="99"/>'
            '<w:semiHidden/><w:tblPr><w:tblInd w:w="0" w:type="dxa"/><w:tblCellMar><w:top w:w="0" w:type="dxa"/>'
            '<w:left w:w="108" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>'
            '</w:styles>') % (W_NS, FONT_LATIN, FONT_LATIN, FONT_BODY, FONT_LATIN,
                              heading(1, 15, 360, 160), heading(2, 12.5, 240, 100), heading(3, 11, 180, 80),
                              FONT_LATIN, FONT_LATIN, FONT_HEAD, ACCENT)
