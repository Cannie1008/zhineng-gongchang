"""冒烟测试：确认脚本能在当前 Python 版本下跑通，且固定样例的结论没变。

用法：python tests/smoke_test.py
不依赖 pytest，只用标准库；CI 与本地同一份代码。
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZNC = os.path.join(ROOT, "scripts", "zngc.py")
SAMPLE = os.path.join(ROOT, "assets", "sample_input.json")


def run(*args):
    proc = subprocess.run(
        [sys.executable, ZNC] + list(args),
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    out = proc.stdout.decode("utf-8", "replace")
    if proc.returncode != 0:
        print(out)
        raise SystemExit("命令失败：zngc.py " + " ".join(args))
    return out


def expect(out, *needles):
    missing = [n for n in needles if n not in out]
    if missing:
        print(out)
        raise SystemExit("结论不符，缺少：" + "、".join(missing))


def main():
    # 1. 固定样例的研判结论
    out = run("assess", SAMPLE, "--today", "2026-10-23")
    expect(
        out,
        "本轮可冲：先进级",
        "12项缺口",
        "1/17=5.9%",
        "把现有场景升级为AI场景5个，或新增AI场景6个",
        "智能工厂基座大模型使用情况表",
        "2026年度卓越级智能工厂项目公示",
    )

    # 2. JSON 输出可解析，且四级结论齐全
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "result.json")
        run("assess", SAMPLE, "--json", target, "--today", "2026-10-23")
        with open(target, encoding="utf-8") as fh:
            data = json.load(fh)
        levels = data.get("levels") or data.get("tiers") or {}
        if not levels:
            raise SystemExit("结果 JSON 里没有四级结论：" + ", ".join(data.keys()))

    # 3. 指标口径：相对变化与百分点不能混
    out = run("kpi", "--name", "产品不良率", "--before", "1.8%", "--after", "1.1%")
    expect(out, "38.9%", "0.7个百分点")

    # 4. 场景清单能列出来
    out = run("scenes")
    expect(out, "数字孪生工厂构建", "智能排产")

    # 5. 地方规则确实会改变结论（上海样例）
    shanghai = os.path.join(ROOT, "tests", "shanghai.json")
    if os.path.exists(shanghai):
        out = run("assess", shanghai, "--today", "2026-10-23")
        expect(out, "上海要求")

    # 6. 草稿自查：绝对值和相对变化都要能对上填报数据
    with tempfile.TemporaryDirectory() as tmp:
        draft = os.path.join(tmp, "draft.md")
        with open(draft, "w", encoding="utf-8") as fh:
            fh.write("生产效率提升35%，产品不良率下降50%，订单准时交付率达到99.5%。\n"
                     "卓越级要求人工智能场景比例达到30%，本公司为国内领先。\n")
        out = run("check", draft, "--input", SAMPLE)
        expect(
            out,
            "与测算不一致",            # 相对变化对不上
            "达到99.5%",               # 绝对值对不上当前值
            "国内领先",                # 夸大表述
        )
        if "30.0%" in out and "卓越级要求" in out:
            raise SystemExit("门槛表述被误报成企业数据：卓越级要求30% 不应触发不一致")

    # 7. 批量初筛：-o 给 .xlsx 就要产出真正的 xlsx（能被解析），不能是改了扩展名的 CSV
    with tempfile.TemporaryDirectory() as tmp:
        import shutil
        src = os.path.join(tmp, "in")
        os.makedirs(src)
        shutil.copy(SAMPLE, os.path.join(src, "a.json"))
        out_xlsx = os.path.join(tmp, "汇总.xlsx")
        run("batch", src, "-o", out_xlsx, "--today", "2026-10-23")
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import zngc_xlsx as X
        wb = X.read_workbook(out_xlsx)   # 不是 zip 会在这里直接抛异常
        cells = sum(len(sh) for sh in wb.values())
        if cells < 5:
            raise SystemExit("批量初筛的 xlsx 读回来是空的（%d 个单元格）" % cells)

    print("smoke test passed")


if __name__ == "__main__":
    main()
