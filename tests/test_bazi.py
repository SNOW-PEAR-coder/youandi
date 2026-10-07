#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for scripts/bazi.py.

No third-party dependencies, pytest-compatible.

    python tests/test_bazi.py
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import bazi  # noqa: E402

FAILURES = []


def check(name, got, want):
    ok = got == want
    if not ok:
        FAILURES.append((name, got, want))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        print(f"        got  = {got!r}")
        print(f"        want = {want!r}")
    return ok


def chart(datestr, timestr="12:00", gender="male", lon=None, db=23, lunar=False, leap=False):
    if lunar:
        y, m, d = (int(x) for x in datestr.split("-"))
        day = bazi.lunar_to_gregorian(y, m, d, leap)
    else:
        day = datetime.strptime(datestr, "%Y-%m-%d").date()
    hh, mm = (int(x) for x in timestr.split(":"))
    return bazi.build_chart(birth=datetime(day.year, day.month, day.day, hh, mm),
                            gender=gender, lon=lon, day_boundary_hour=db)


def pillars(c):
    p = c["四柱"]
    return f"{p['年']} {p['月']} {p['日']} {p['时']}"


# ---------------------------------------------------------------- day pillar

def test_day_pillars():
    """日柱 against independently published 干支 values."""
    print("test_day_pillars")
    cases = [("1949-10-01", "甲子"), ("1990-06-16", "壬子"),
             ("2000-01-01", "戊午"), ("2026-10-07", "甲寅")]
    for s, want in cases:
        y, m, d = (int(x) for x in s.split("-"))
        jdn = int(bazi.julian_day(y, m, d, 0.0) + 0.5)
        check(f"日柱 {s}", bazi._pillar((jdn - 11) % 60), want)


# ------------------------------------------------------------ lunar calendar

SPRING_FESTIVAL = {
    2000: "2000-02-05", 2001: "2001-01-24", 2002: "2002-02-12", 2003: "2003-02-01",
    2004: "2004-01-22", 2005: "2005-02-09", 2006: "2006-01-29", 2007: "2007-02-18",
    2008: "2008-02-07", 2009: "2009-01-26", 2010: "2010-02-14", 2011: "2011-02-03",
    2012: "2012-01-23", 2013: "2013-02-10", 2014: "2014-01-31", 2015: "2015-02-19",
    2016: "2016-02-08", 2017: "2017-01-28", 2018: "2018-02-16", 2019: "2019-02-05",
    2020: "2020-01-25", 2021: "2021-02-12", 2022: "2022-02-01", 2023: "2023-01-22",
    2024: "2024-02-10", 2025: "2025-01-29", 2026: "2026-02-17", 2027: "2027-02-06",
    2028: "2028-01-26", 2029: "2029-02-13", 2030: "2030-02-03",
}


def test_spring_festival_dates():
    """农历正月初一 -> 公历, 2000-2030. 联合校验朔望算法与无中气置闰规则."""
    print("test_spring_festival_dates")
    for y, want in SPRING_FESTIVAL.items():
        check(f"春节 {y}", bazi.lunar_to_gregorian(y, 1, 1).isoformat(), want)


def test_leap_months():
    """闰月: 朔日与闰月序号都要对."""
    print("test_leap_months")
    cases = [(2020, 4, True, "2020-05-23"), (2020, 4, False, "2020-04-23"),
             (2023, 2, True, "2023-03-22"), (2023, 2, False, "2023-02-20"),
             (2025, 6, True, "2025-07-25"), (2025, 6, False, "2025-06-25")]
    for y, m, leap, want in cases:
        tag = "闰" if leap else ""
        check(f"农历 {y} 年{tag}{m}月初一",
              bazi.lunar_to_gregorian(y, m, 1, leap).isoformat(), want)


def test_lunar_conversion_spot_check():
    """基准命例的农历换算 (1990-06-15 即 农历1990年五月廿三)."""
    print("test_lunar_conversion_spot_check")
    check("农历1990-05-23", bazi.lunar_to_gregorian(1990, 5, 23).isoformat(), "1990-06-15")
    check("农历1990-08-15", bazi.lunar_to_gregorian(1990, 8, 15).isoformat(), "1990-10-03")


def test_invalid_lunar_input():
    print("test_invalid_lunar_input")
    for args in [(2020, 13, 1), (1900, 1, 1), (2020, 4, 31)]:
        y, m, d = args
        try:
            bazi.lunar_to_gregorian(y, m, d)
        except ValueError:
            check(f"拒绝非法农历 {args}", True, True)
        else:
            check(f"拒绝非法农历 {args}", False, True)


# ------------------------------------------------------------- solar terms

def test_solar_terms_land_in_expected_month():
    """全部 24 节气必须落在各自应有的公历月份 (防止求解器跨年收敛)."""
    print("test_solar_terms_land_in_expected_month")
    bad = 0
    for y in (1960, 1980, 1990, 2025, 2026, 2050):
        for name, lon, month in bazi.JIE_TABLE:
            dt = bazi.jd_ut_to_beijing(bazi.solar_term_jd(lon, y, month))
            if dt.month != month:
                bad += 1
                print(f"        {y} {name} -> {dt.month} 月, 期望 {month} 月")
        for name, lon, month, yoff in bazi.ZHONGQI_TABLE:
            dt = bazi.jd_ut_to_beijing(bazi.solar_term_jd(lon, y + yoff, month))
            if dt.month != month:
                bad += 1
                print(f"        {y} {name} -> {dt.month} 月, 期望 {month} 月")
    check("24 节气月份全部正确", bad, 0)


def test_jie_spacing():
    """相邻两个『节』相隔约 30 天; 近日点(1月)最短, 远日点(7月)最长."""
    print("test_jie_spacing")
    seq = []
    for y in (2024, 2025, 2026):
        for i in range(12):
            seq.append((bazi.jie_datetime(y, i), bazi.JIE_ORDER[i]))
    seq.sort()
    gaps = [(b[0] - a[0]).total_seconds() / 86400 for a, b in zip(seq, seq[1:])]
    check("节间隔在 29.4~31.5 天", all(29.4 < g < 31.5 for g in gaps), True)
    jan = (bazi.jie_datetime(2025, 0) - bazi.jie_datetime(2025, 11)).days
    jul = (bazi.jie_datetime(2025, 5) - bazi.jie_datetime(2025, 4)).days
    check("近日点间隔(1月) < 远日点间隔(7月)", jan < jul, True)


def test_lichun_year_boundary():
    """立春换年: 2004 立春约在 2 月 4 日 19:5x, 前后年柱必须切换."""
    print("test_lichun_year_boundary")

    def year_month(c):
        return " ".join(pillars(c).split()[:2])

    check("2004-02-04 19:00", year_month(chart("2004-02-04", "19:00")), "癸未 乙丑")
    check("2004-02-04 20:30", year_month(chart("2004-02-04", "20:30")), "甲申 丙寅")


# --------------------------------------------------------------- full charts

def test_full_chart_hour_variants():
    """基准命例四个变体: 真太阳时把两个时辰都往前推了一位."""
    print("test_full_chart_hour_variants")
    check("05:30 北京时间", pillars(chart("1990-06-15", "05:30")),
          "庚午 壬午 辛亥 辛卯")
    check("05:30 真太阳时(104.1E)", pillars(chart("1990-06-15", "05:30", lon=104.1)),
          "庚午 壬午 辛亥 庚寅")
    check("17:30 北京时间", pillars(chart("1990-06-15", "17:30")),
          "庚午 壬午 辛亥 丁酉")
    check("17:30 真太阳时(104.1E)", pillars(chart("1990-06-15", "17:30", lon=104.1)),
          "庚午 壬午 辛亥 丙申")


def test_derived_values():
    print("test_derived_values")
    c = chart("1990-06-15", "05:30", lon=104.1)
    check("真太阳时", c["输入"]["真太阳时"], "1990-06-15 04:26")
    check("经度时差", c["输入"]["经度时差_分"], -63.6)
    check("十神", [c["十神"][k] for k in "年月日时"], ["劫财", "伤官", "比肩", "劫财"])
    check("日主", c["日主"], "辛(金,阴)")
    check("月令", c["月令"], "午")
    check("空亡", c["空亡"], ["寅", "卯"])
    check("大运方向", c["大运"]["方向"], "顺排")
    check("起运", c["输入"]["起运"], "7岁6个月")
    check("交运", c["输入"]["交运日期"], "1997-12-15")
    check("前四步大运", [x["干支"] for x in c["大运"]["列表"][:4]],
          ["癸未", "甲申", "乙酉", "丙戌"])
    check("天乙贵人", c["神煞"]["天乙贵人"], ["年", "月", "时"])
    check("金舆在日柱", c["神煞"]["金舆"], ["日"])


def test_ten_gods():
    """日主辛 对十天干的十神映射."""
    print("test_ten_gods")
    check("辛日十神表", [bazi.ten_god("辛", g) for g in "甲乙丙丁戊己庚辛壬癸"],
          ["正财", "偏财", "正官", "七杀", "正印", "偏印", "劫财", "比肩", "伤官", "食神"])
    check("戊日十神表", [bazi.ten_god("戊", g) for g in "甲乙丙丁戊己庚辛壬癸"],
          ["七杀", "正官", "偏印", "正印", "比肩", "劫财", "食神", "伤官", "偏财", "正财"])


def test_xunkong():
    print("test_xunkong")
    check("甲子旬空亡", bazi.xunkong(0), ("戌", "亥"))
    check("甲辰旬空亡", bazi.xunkong(40), ("寅", "卯"))
    check("甲寅旬空亡", bazi.xunkong(50), ("子", "丑"))


def test_branch_relations():
    print("test_branch_relations")
    cases = [("午", "未", "六合"), ("寅", "申", "六冲/相刑"), ("巳", "申", "六合/相刑"),
             ("申", "亥", "六害"), ("子", "未", "六害"), ("卯", "申", "暗合"),
             ("酉", "酉", "伏吟/自刑"), ("未", "未", "伏吟"),
             ("丑", "未", "六冲/相刑"), ("子", "卯", "相刑"), ("辰", "申", "半合")]
    for a, b, want in cases:
        check(f"{a}{b}", bazi.branch_relations(a, b), want)


def test_day_boundary():
    """23:40 出生: 子时换日应进次日, 零点换日应留当日."""
    print("test_day_boundary")
    check("23:40 子时换日", pillars(chart("1990-06-15", "23:40", db=23)),
          "庚午 壬午 壬子 庚子")
    check("23:40 零点换日", pillars(chart("1990-06-15", "23:40", db=0)),
          "庚午 壬午 辛亥 戊子")


def test_luck_direction():
    """阳年男顺排 / 阴年男逆排, 女命相反."""
    print("test_luck_direction")
    check("阳年(庚午)男", chart("1990-06-15", gender="male")["大运"]["方向"], "顺排")
    check("阳年(庚午)女", chart("1990-06-15", gender="female")["大运"]["方向"], "逆排")
    check("阴年(乙亥)男", chart("1995-06-15", gender="male")["大运"]["方向"], "逆排")
    check("阴年(乙亥)女", chart("1995-06-15", gender="female")["大运"]["方向"], "顺排")
    check("阴年女顺排第一步", chart("1995-06-15", gender="female")["大运"]["列表"][0]["干支"],
          "癸未")


def test_scan_years():
    """流年扫描: 校验机制而非硬编码年份, 这样换命例也不会失效."""
    print("test_scan_years")
    c = chart("1990-06-15", "05:30", lon=104.1)
    rows = bazi.scan_years(c, 2026, 2034)
    check("行数", len(rows), 9)
    check("干支与年份一致",
          [r["年份"] for r in rows
           if r["干支"] != bazi._pillar((r["年份"] - 4) % 60)], [])

    day_branch = c["_day_branch"]
    hits = 0
    for r in rows:
        if r["干支"][1] == day_branch:
            hits += 1
            check(f"{r['年份']} 流年支与日支相同须报伏吟", "伏吟" in r["与日支(妻宫)"], True)
    check("伏吟情形覆盖到", hits > 0, True)

    hits = 0
    for r in rows:
        if r["年干十神"] in ("正财", "偏财"):
            hits += 1
            check(f"{r['年份']} 财星透干须标注",
                  any("财星透干" in f for f in r["姻缘信号"]), True)
    check("财星情形覆盖到", hits > 0, True)

    hits = 0
    for r in rows:
        if r["干支"][1] in c["空亡"]:
            hits += 1
            check(f"{r['年份']} 落空亡须标注", "落空亡" in r["姻缘信号"], True)
    check("空亡情形覆盖到", hits > 0, True)

    check("2032 桃花(日支起)",
          "桃花(日支起)" in {r["年份"]: r for r in rows}[2032]["姻缘信号"], True)


def test_boundary_warning_fires():
    print("test_boundary_warning_fires")
    near = chart("1990-06-15", "05:50", lon=104.1)   # 真太阳时 04:46, 距 05:00 交界 14 分钟
    check("时柱临界会报警", any("时辰交界" in w for w in near["提醒"]), True)
    far = chart("1990-06-15", "12:00")               # 午时正中, 距两岸各 60 分钟
    check("时柱正中不报警", any("时辰交界" in w for w in far["提醒"]), False)
    jie = chart("1990-07-07", "17:00")               # 距小暑约 2 分钟
    check("节气临界会报警", any("小暑" in w for w in jie["提醒"]), True)
    clean = chart("1990-06-15", "05:30", lon=104.1)  # 距两岸 34 / 86 分钟
    check("基准命例无提醒", clean["提醒"], [])


def main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print()
    print("=" * 60)
    if FAILURES:
        print(f"{len(FAILURES)} 项失败:")
        for name, got, want in FAILURES:
            print(f"  - {name}: got={got!r} want={want!r}")
        return 1
    print(f"全部通过 ({len(tests)} 个测试函数)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())