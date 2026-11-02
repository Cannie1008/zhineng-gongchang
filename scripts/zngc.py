# -*- coding: utf-8 -*-
"""智能工厂研判与申报 —— 命令行入口（只用标准库，Python 3.8+）。

用法（在技能目录下运行）：
  python scripts/zngc.py assess 输入.json [--json 结果.json] [--today 2026-10-22] [--focus 卓越级]
  python scripts/zngc.py report 输入.json -o 研判报告.docx [--org 出具单位] [--contact 联系方式]
  python scripts/zngc.py kpi --name 产品不良率 --before 1.8% --after 1.1%
  python scripts/zngc.py xlsx 填好的底稿.xlsx -o 输入.json
  python scripts/zngc.py check 申报书草稿.txt [--input 输入.json] [--template 国家卓越级|上海先进级]
  python scripts/zngc.py batch 企业资料文件夹 -o 批量初筛.csv   （文件夹里放多家企业的底稿xlsx或输入json）
  python scripts/zngc.py rules [--level 卓越级]
  python scripts/zngc.py scenes
"""
import argparse
import datetime as dt
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _fix_console():
    """Windows 中文控制台默认 GBK，直接 print 中文/符号会崩，统一改成 UTF-8 并容错。"""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            try:
                setattr(sys, name, io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace"))
            except Exception:
                pass


def _today(s):
    if not s:
        return dt.date.today()
    return dt.datetime.strptime(s, "%Y-%m-%d").date()


def _dump(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)


def cmd_assess(a):
    import zngc_engine as E
    res = E.evaluate(E.load_input(a.input), _today(a.today))
    if a.json:
        _dump(res, a.json)
    print(E.summary_text(res, a.focus))
    if a.json:
        print("\n完整结果已写入：%s" % a.json)


def cmd_report(a):
    import zngc_engine as E
    import zngc_report as RP
    res = E.evaluate(E.load_input(a.input), _today(a.today))
    out = a.output or "智能工厂研判报告.docx"
    if os.path.dirname(os.path.abspath(out)):
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    RP.build_report(res, out, org=a.org or "", contact=a.contact or "", focus=a.focus)
    print("研判报告已生成：%s" % os.path.abspath(out))
    print(res["recommend"]["headline"])


def cmd_kpi(a):
    import zngc_engine as E
    row = E.calc_kpi({"name": a.name, "before": a.before, "after": a.after, "unit": a.unit or "",
                      "period": a.period or "", "basis": a.basis or ""})
    u = row["unit"]
    if u == "%":
        print("%s：%s%% → %s%%，%s" % (row["name"], E.fmt(row["before"]), E.fmt(row["after"]), row["text"]))
    else:
        print("%s：%s → %s%s，%s" % (row["name"], E.fmt(row["before"]), E.fmt(row["after"]), (" " + u) if u else "", row["text"]))
    for w in row["warn"]:
        print("  提示：" + w)


def cmd_xlsx(a):
    import zngc_xlsx as X
    data = X.workbook_to_input(a.input)
    out = a.output or os.path.splitext(a.input)[0] + "_输入.json"
    _dump(data, out)
    print("已从底稿读出：场景%d个、指标%d项。输入文件：%s" % (len(data["scenarios"]), len(data["kpis"]), os.path.abspath(out)))
    for w in data.get("_warnings", []):
        print("  提示：" + w)


def cmd_check(a):
    import zngc_check as C
    text = C.read_text(a.input)
    inp = None
    if a.input_json:
        import zngc_engine as E
        inp = E.evaluate(E.load_input(a.input_json))
    issues = C.check(text, template=a.template, result=inp)
    if not issues:
        print("没有发现问题。")
    for it in issues:
        print("[%s] %s" % (it["level"], it["text"]))


def cmd_batch(a):
    import csv
    import glob
    import zngc_engine as E
    import zngc_xlsx as X
    files = sorted(glob.glob(os.path.join(a.folder, "*.json")) + glob.glob(os.path.join(a.folder, "*.xlsx")))
    files = [f for f in files if not os.path.basename(f).startswith(("~$", "."))]
    if not files:
        print("文件夹里没有 .json 或 .xlsx 文件：%s" % a.folder)
        return
    head = ["文件", "企业名称", "省份", "当前层级", "本轮可冲", "下一目标", "基础级", "先进级", "卓越级", "领航级",
            "AI场景比例", "下一目标主要缺口", "下一目标待证项数", "高风险提示数", "备注"]
    rows, ok = [], 0
    for f in files:
        name = os.path.basename(f)
        try:
            data = X.workbook_to_input(f) if f.lower().endswith(".xlsx") else E.load_input(f)
            res = E.evaluate(data, _today(a.today))
        except Exception as e:  # 单个文件出错不影响其他企业
            rows.append([name] + [""] * 13 + ["读取失败：%s" % e])
            continue
        ok += 1
        L = {x["level"]: x for x in res["levels"]}
        rec = res["recommend"]
        nl = rec.get("next_level")
        gaps, pend = "", ""
        if nl:
            items = L[nl]["hard_fail"] + L[nl]["gaps"]
            gaps = "；".join(c["text"].split("（")[0] for c in items[:3])
            pend = len(L[nl]["pending"])
        c = res["company"]
        rows.append([name, c.get("name", ""), c.get("province", ""),
                     res["gates"].get("current_level") if res["gates"].get("current_level_known") else "未说明",
                     rec.get("apply_level") or "—", nl or "—"] +
                    [L[lv]["verdict"] for lv in ("基础级", "先进级", "卓越级", "领航级")] +
                    ["%.1f%%" % (res["ai"]["ratio"] * 100), gaps, pend,
                     sum(1 for x in res["flags"] if x["level"] == "高"),
                     "" if rec.get("apply_level") else rec.get("headline", "")])
    out = a.output or os.path.join(a.folder, "批量初筛.csv")
    ext = os.path.splitext(out)[1].lower()
    if ext == ".xls":  # 老式二进制格式写不了，换成 xlsx，避免生成一个扩展名骗人的文件
        out = os.path.splitext(out)[0] + ".xlsx"
        ext = ".xlsx"
        print("提示：.xls 是老式二进制格式，已改存为 %s" % os.path.basename(out))
    if ext in (".xlsx", ".xlsm"):
        X.write_rows(out, [head] + rows, sheet_name="批量初筛")
    else:
        with open(out, "w", encoding="utf-8-sig", newline="") as fh:  # 带BOM，Excel直接打开不乱码
            w = csv.writer(fh)
            w.writerow(head)
            w.writerows(rows)
    print("已初筛%d家（读取失败%d个），汇总表：%s" % (ok, len(files) - ok, os.path.abspath(out)))
    for r in rows[:20]:
        print("  %s｜本轮可冲：%s｜下一目标：%s" % (r[1] or r[0], r[4], r[5]))


def cmd_rules(a):
    import zngc_rules as R
    levels = [a.level] if a.level else R.LEVELS
    for lv in levels:
        print("== %s（成熟度≥%d级；%s%s）" % (lv, R.CMMM_MIN[lv], R.REQUIRED_NOTE[lv],
                                         ("；AI场景比例≥%d%%" % round(R.AI_RATIO_MIN[lv] * 100)) if R.AI_RATIO_MIN[lv] else ""))
        for seg in R.SEGMENTS:
            pts = [p for p in R.POINTS[lv] if p["seg"] == seg["key"]]
            print("  [%s]" % seg["name"])
            for p in pts:
                print("    %s %s%s" % (p["id"], p["t"], "（标志性）" if p.get("sig") else ""))
        print("  [建设成效]")
        for e in R.EFFECTS[lv]:
            print("    %s %s" % (e["id"], e["t"]))


def cmd_scenes(a):
    import zngc_rules as R
    for s in R.SCENARIOS:
        print("%2d %s〔%s→%s〕%s" % (s["id"], s["name"], s["guide"], R.seg_name(s["seg"]), s["d"]))


def main(argv=None):
    _fix_console()
    p = argparse.ArgumentParser(prog="zngc", description="智能工厂研判与申报")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("assess", help="研判：输出四级结论、缺口、AI比例、指标与倒排")
    s.add_argument("input")
    s.add_argument("--json")
    s.add_argument("--today")
    s.add_argument("--focus")
    s.set_defaults(func=cmd_assess)

    s = sub.add_parser("report", help="生成Word研判报告")
    s.add_argument("input")
    s.add_argument("-o", "--output")
    s.add_argument("--org")
    s.add_argument("--contact")
    s.add_argument("--today")
    s.add_argument("--focus")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("kpi", help="单个指标的变化率与百分点")
    s.add_argument("--name", required=True)
    s.add_argument("--before")
    s.add_argument("--after", required=True)
    s.add_argument("--unit")
    s.add_argument("--period")
    s.add_argument("--basis")
    s.set_defaults(func=cmd_kpi)

    s = sub.add_parser("xlsx", help="把填好的研判底稿转成输入JSON")
    s.add_argument("input")
    s.add_argument("-o", "--output")
    s.set_defaults(func=cmd_xlsx)

    s = sub.add_parser("check", help="检查申报书草稿：字数、夸大表述、数字是否与研判一致")
    s.add_argument("input")
    s.add_argument("--input-json", dest="input_json")
    s.add_argument("--template", default="国家卓越级")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("batch", help="批量初筛：一个文件夹里多家企业的底稿或输入")
    s.add_argument("folder")
    s.add_argument("-o", "--output")
    s.add_argument("--today")
    s.set_defaults(func=cmd_batch)

    s = sub.add_parser("rules", help="列出各级要点")
    s.add_argument("--level")
    s.set_defaults(func=cmd_rules)

    s = sub.add_parser("scenes", help="列出40个典型场景")
    s.set_defaults(func=cmd_scenes)

    a = p.parse_args(argv)
    if not getattr(a, "func", None):
        p.print_help()
        return 1
    try:
        a.func(a)
    except FileNotFoundError as e:
        print("找不到文件：%s" % e.filename)
        return 2
    except ValueError as e:
        print("输入有问题：%s" % e)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
