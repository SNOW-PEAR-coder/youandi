#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""八字排盘引擎 / BaZi (Four Pillars) chart builder.

Deterministic layer of the ``youandi`` skill. Every pillar, solar term,
luck cycle and lunar-date conversion is *computed* here, so the model never has
to guess them.

Computes
--------
* 真太阳时   longitude offset + equation of time
* 24 节气    apparent solar longitude solved by Newton iteration (Meeus series)
* 四柱       year by 立春, month by 节, day by Julian Day Number (子时换日默认)
* 十神 / 藏干 / 空亡 / 神煞
* 大运       顺逆、起运年龄、交运日期、完整排布
* 流年扫描   干支、十神、与妻宫的关系、姻缘信号
* 农历→公历  实时朔望 + 无中气置闰，不依赖任何年份查表

No third-party dependencies. Python 3.8+.

Accuracy
--------
Solar terms use the low-precision Meeus apparent-longitude series: residuals are
typically a few minutes and worst case about 15 minutes. New moons are good to a
few minutes (validated against published 春节 dates 2000-2030). Births within
about an hour of a 节气 or 时辰 boundary are flagged in the output and should be
confirmed against an ephemeris. Do not treat a flagged boundary as resolved.

Usage
-----
    python bazi.py --date 1990-06-15 --time 05:00 --gender male --lon 104.1
    python bazi.py --lunar 1990-05-23 --time 05:00 --gender male --lon 104.1
    python bazi.py --date 1990-06-15 --time 05:00 --gender male --years 2026-2040
    python bazi.py --date 1990-06-15 --time 05:00 --gender male --json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timedelta

try:  # keep Chinese output readable when the console default is not UTF-8
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------

GAN = "甲乙丙丁戊己庚辛壬癸"
ZHI = "子丑寅卯辰巳午未申酉戌亥"

GAN_WX = {"甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
          "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水"}
GAN_YINYANG = {"甲": "阳", "乙": "阴", "丙": "阳", "丁": "阴", "戊": "阳",
               "己": "阴", "庚": "阳", "辛": "阴", "壬": "阳", "癸": "阴"}

# 地支藏干, 本气在前
CANGGAN = {
    "子": ["癸"],
    "丑": ["己", "癸", "辛"],
    "寅": ["甲", "丙", "戊"],
    "卯": ["乙"],
    "辰": ["戊", "乙", "癸"],
    "巳": ["丙", "庚", "戊"],
    "午": ["丁", "己"],
    "未": ["己", "丁", "乙"],
    "申": ["庚", "壬", "戊"],
    "酉": ["辛"],
    "戌": ["戊", "辛", "丁"],
    "亥": ["壬", "甲"],
}

# 十神按「五行关系 + 阴阳同异」判定。
# 注意: 常见的 (other - day) % 10 偏移表只对阳日干成立, 阴日干必须反向, 否则全盘十神错位。
SHISHEN_BY_REL = {
    0: ("比肩", "劫财"),   # 同我
    1: ("食神", "伤官"),   # 我生
    2: ("偏财", "正财"),   # 我克
    3: ("七杀", "正官"),   # 克我
    4: ("偏印", "正印"),   # 生我
}

# (节气名, 太阳视黄经, 大致公历月份)  12 节: 月建分界
JIE_TABLE = [
    ("小寒", 285, 1), ("立春", 315, 2), ("惊蛰", 345, 3), ("清明", 15, 4),
    ("立夏", 45, 5), ("芒种", 75, 6), ("小暑", 105, 7), ("立秋", 135, 8),
    ("白露", 165, 9), ("寒露", 195, 10), ("立冬", 225, 11), ("大雪", 255, 12),
]
# 12 中气: 农历月序判据 (含雨水之月为正月)
ZHONGQI_TABLE = [
    ("雨水", 330, 2, 0), ("春分", 0, 3, 0), ("谷雨", 30, 4, 0), ("小满", 60, 5, 0),
    ("夏至", 90, 6, 0), ("大暑", 120, 7, 0), ("处暑", 150, 8, 0), ("秋分", 180, 9, 0),
    ("霜降", 210, 10, 0), ("小雪", 240, 11, 0), ("冬至", 270, 12, 0),
    ("大寒", 300, 1, 1),
]
JIE_ORDER = [name for name, _, _ in
             [("立春", 315, 2), ("惊蛰", 345, 3), ("清明", 15, 4), ("立夏", 45, 5),
              ("芒种", 75, 6), ("小暑", 105, 7), ("立秋", 135, 8), ("白露", 165, 9),
              ("寒露", 195, 10), ("立冬", 225, 11), ("大雪", 255, 12), ("小寒", 285, 1)]]
JIE_LON_ORDER = [315, 345, 15, 45, 75, 105, 135, 165, 195, 225, 255, 285]
JIE_MONTH_ORDER = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 1]
JIE_ZHI_ORDER = ["寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥", "子", "丑"]

LIU_HE = {("子", "丑"), ("寅", "亥"), ("卯", "戌"), ("辰", "酉"), ("巳", "申"), ("午", "未")}
LIU_CHONG = {("子", "午"), ("丑", "未"), ("寅", "申"), ("卯", "酉"), ("辰", "戌"), ("巳", "亥")}
LIU_HAI = {("子", "未"), ("丑", "午"), ("寅", "巳"), ("卯", "辰"), ("申", "亥"), ("酉", "戌")}
AN_HE = {("子", "巳"), ("寅", "丑"), ("卯", "申"), ("午", "亥")}
BAN_HE = {("申", "子"), ("子", "辰"), ("申", "辰"),
          ("亥", "卯"), ("卯", "未"), ("亥", "未"),
          ("寅", "午"), ("午", "戌"), ("寅", "戌"),
          ("巳", "酉"), ("酉", "丑"), ("巳", "丑")}
XING_GROUP = [{"寅", "巳", "申"}, {"丑", "戌", "未"}]
SELF_XING = {"辰", "午", "酉", "亥"}

TIANYI = {"甲": "丑未", "戊": "丑未", "庚": "丑未", "乙": "子申", "己": "子申",
          "丙": "亥酉", "丁": "亥酉", "壬": "卯巳", "癸": "卯巳", "辛": "午寅"}
WENCHANG = {"甲": "巳", "乙": "午", "丙": "申", "丁": "酉", "戊": "申",
            "己": "酉", "庚": "亥", "辛": "子", "壬": "寅", "癸": "卯"}
JINYU = {"甲": "辰", "乙": "巳", "丙": "未", "丁": "申", "戊": "未",
         "己": "申", "庚": "戌", "辛": "亥", "壬": "丑", "癸": "寅"}
GANLU = {"甲": "寅", "乙": "卯", "丙": "巳", "丁": "午", "戊": "巳",
         "己": "午", "庚": "申", "辛": "酉", "壬": "亥", "癸": "子"}
YANGREN = {"甲": "卯", "乙": "辰", "丙": "午", "丁": "未", "戊": "午",
           "己": "未", "庚": "酉", "辛": "戌", "壬": "子", "癸": "丑"}
HONGYAN = {"甲": "午", "乙": "申", "丙": "寅", "丁": "未", "戊": "辰",
           "己": "辰", "庚": "戌", "辛": "酉", "壬": "子", "癸": "申"}
TIANDE = {"寅": "丁", "卯": "申", "辰": "壬", "巳": "辛", "午": "亥", "未": "甲",
          "申": "癸", "酉": "寅", "戌": "丙", "亥": "乙", "子": "巳", "丑": "庚"}
YUEDE = {"寅午戌": "丙", "申子辰": "壬", "亥卯未": "甲", "巳酉丑": "庚"}
SANHE_OF = {"寅": "寅午戌", "午": "寅午戌", "戌": "寅午戌",
            "申": "申子辰", "子": "申子辰", "辰": "申子辰",
            "巳": "巳酉丑", "酉": "巳酉丑", "丑": "巳酉丑",
            "亥": "亥卯未", "卯": "亥卯未", "未": "亥卯未"}
HUAGAI = {"寅午戌": "戌", "申子辰": "辰", "巳酉丑": "丑", "亥卯未": "未"}
TAOHUA = {"寅午戌": "卯", "申子辰": "酉", "巳酉丑": "午", "亥卯未": "子"}
YIMA = {"寅午戌": "申", "申子辰": "寅", "巳酉丑": "亥", "亥卯未": "巳"}
GUGUA = {"亥": ("寅", "戌"), "子": ("寅", "戌"), "丑": ("寅", "戌"),
         "寅": ("巳", "丑"), "卯": ("巳", "丑"), "辰": ("巳", "丑"),
         "巳": ("申", "辰"), "午": ("申", "辰"), "未": ("申", "辰"),
         "申": ("亥", "未"), "酉": ("亥", "未"), "戌": ("亥", "未")}

YINCHA_YANGCUO = {"丙子", "丁丑", "戊寅", "辛卯", "壬辰", "癸巳",
                  "丙午", "丁未", "戊申", "辛酉", "壬戌", "癸亥"}

# 姻缘直接相关, 输出时单独标注
MARRIAGE_STARS = {"天乙贵人", "金舆", "红鸾", "天喜", "桃花(以日支起)", "桃花(以年支起)",
                  "孤辰", "寡宿", "红艳煞", "阴差阳错日", "驿马(以日支起)"}

TZ_OFFSET_HOURS = 8.0  # 北京时间


# --------------------------------------------------------------------------
# astronomy
# --------------------------------------------------------------------------

def julian_day(year: int, month: int, day: int, hour: float = 0.0) -> float:
    """Julian Day for a Gregorian calendar date at ``hour`` UT."""
    y, m = year, month
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return (math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1))
            + day + b - 1524.5 + hour / 24.0)


def delta_t_seconds(year: float) -> float:
    """Approximate TT-UT in seconds (Espenak & Meeus polynomials)."""
    y = year
    if 1900 <= y < 1920:
        t = y - 1900
        return -2.79 + 1.494119 * t - 0.0598939 * t ** 2 + 0.0061966 * t ** 3 - 0.000197 * t ** 4
    if 1920 <= y < 1941:
        t = y - 1920
        return 21.20 + 0.84493 * t - 0.076100 * t ** 2 + 0.0020936 * t ** 3
    if 1941 <= y < 1961:
        t = y - 1950
        return 29.07 + 0.407 * t - t ** 2 / 233 + t ** 3 / 2547
    if 1961 <= y < 1986:
        t = y - 1975
        return 45.45 + 1.067 * t - t ** 2 / 260 - t ** 3 / 718
    if 1986 <= y <= 2050:
        t = y - 2000
        return 62.92 + 0.32217 * t + 0.005589 * t ** 2
    return 69.0


def sun_apparent_longitude(jd_tt: float) -> float:
    """Apparent geocentric longitude of the Sun, degrees [0, 360)."""
    t = (jd_tt - 2451545.0) / 36525.0
    l0 = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    m = 357.52911 + 35999.05029 * t - 0.0001537 * t * t
    mr = math.radians(m)
    c = ((1.914602 - 0.004817 * t - 0.000014 * t * t) * math.sin(mr)
         + (0.019993 - 0.000101 * t) * math.sin(2 * mr)
         + 0.000289 * math.sin(3 * mr))
    omega = 125.04 - 1934.136 * t
    return (l0 + c - 0.00569 - 0.00478 * math.sin(math.radians(omega))) % 360.0


def solar_term_jd(target_deg: float, year: int, month: int) -> float:
    """JD (UT) at which apparent solar longitude reaches ``target_deg``.

    ``month`` anchors the search so the solver cannot converge onto an
    occurrence in a neighbouring year.
    """
    def lon(jd_ut: float) -> float:
        return sun_apparent_longitude(jd_ut + delta_t_seconds(year) / 86400.0)

    guess = julian_day(year, month, 15, 0.0)
    guess += (((target_deg - lon(guess) + 180.0) % 360.0) - 180.0) / 0.98564736
    for _ in range(16):
        f = ((lon(guess) - target_deg + 180.0) % 360.0) - 180.0
        if abs(f) < 1e-9:
            break
        guess -= f / 0.98564736
    return guess


def jd_ut_to_beijing(jd_ut: float) -> datetime:
    return datetime(2000, 1, 1, 12, 0, 0) + timedelta(days=jd_ut - 2451545.0 + TZ_OFFSET_HOURS / 24.0)


def jie_datetime(year: int, i: int) -> datetime:
    """Beijing datetime of the i-th 节 (i=0 -> 立春) of the given Gregorian year."""
    return jd_ut_to_beijing(solar_term_jd(JIE_LON_ORDER[i], year, JIE_MONTH_ORDER[i]))


def equation_of_time_minutes(jd_ut: float, year: int) -> float:
    """Apparent minus mean solar time, in minutes."""
    jd_tt = jd_ut + delta_t_seconds(year) / 86400.0
    lam = math.radians(sun_apparent_longitude(jd_tt))
    t = (jd_tt - 2451545.0) / 36525.0
    eps = math.radians(23.439291 - 0.0130042 * t)
    alpha = math.degrees(math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))) % 360.0
    l0 = (280.46646 + 36000.76983 * t + 0.0003032 * t * t) % 360.0
    return (((l0 - 0.0057183 - alpha + 180.0) % 360.0) - 180.0) * 4.0


def true_solar_time(dt: datetime, lon: float) -> tuple[datetime, float, float]:
    """Beijing clock time -> true solar time. Returns (tst, lon_offset_min, eot_min)."""
    lon_offset = (lon - 120.0) * 4.0
    jd_ut = julian_day(dt.year, dt.month, dt.day,
                       dt.hour + dt.minute / 60.0 - TZ_OFFSET_HOURS)
    eot = equation_of_time_minutes(jd_ut, dt.year)
    return dt + timedelta(minutes=lon_offset + eot), lon_offset, eot


# --------------------------------------------------------------------------
# lunar calendar (astronomical, no lookup tables)
# --------------------------------------------------------------------------

def new_moon_jde(k: float) -> float:
    """JDE (TT) of the k-th new moon; k=0 -> 2000 Jan 6."""
    t = k / 1236.85
    jde = (2451550.09766 + 29.530588861 * k + 0.00015437 * t ** 2
           - 0.00000015 * t ** 3 + 0.00000000073 * t ** 4)
    e = 1 - 0.002516 * t - 0.0000074 * t ** 2
    m = math.radians(2.5534 + 29.10535670 * k - 0.0000014 * t ** 2 - 0.00000011 * t ** 3)
    mp = math.radians(201.5643 + 385.81693528 * k + 0.0107582 * t ** 2
                      + 0.00001238 * t ** 3 - 0.000000058 * t ** 4)
    f = math.radians(160.7108 + 390.67050284 * k - 0.0016118 * t ** 2
                     - 0.00000227 * t ** 3 + 0.000000011 * t ** 4)
    om = math.radians(124.7746 - 1.56375588 * k + 0.0020672 * t ** 2 + 0.00000215 * t ** 3)

    corr = (-0.40720 * math.sin(mp)
            + 0.17241 * e * math.sin(m)
            + 0.01608 * math.sin(2 * mp)
            + 0.01039 * math.sin(2 * f)
            + 0.00739 * e * math.sin(mp - m)
            - 0.00514 * e * math.sin(mp + m)
            + 0.00208 * e * e * math.sin(2 * m)
            - 0.00111 * math.sin(mp - 2 * f)
            - 0.00057 * math.sin(mp + 2 * f)
            + 0.00056 * e * math.sin(2 * mp + m)
            - 0.00042 * math.sin(3 * mp)
            + 0.00042 * e * math.sin(m + 2 * f)
            + 0.00038 * e * math.sin(m - 2 * f)
            - 0.00024 * e * math.sin(2 * mp - m)
            - 0.00017 * math.sin(om)
            - 0.00007 * math.sin(mp + 2 * m)
            + 0.00004 * math.sin(2 * mp - 2 * f)
            + 0.00004 * math.sin(3 * m)
            + 0.00003 * math.sin(mp + m - 2 * f)
            + 0.00003 * math.sin(2 * mp + 2 * f)
            - 0.00003 * math.sin(mp + m + 2 * f)
            + 0.00003 * math.sin(mp - m + 2 * f)
            - 0.00002 * math.sin(mp - m - 2 * f)
            - 0.00002 * math.sin(3 * mp + m)
            + 0.00002 * math.sin(4 * mp))

    a = [299.77 + 0.107408 * k - 0.009173 * t ** 2,
         251.88 + 0.016321 * k, 251.83 + 26.651886 * k, 349.42 + 36.412478 * k,
         84.66 + 18.206239 * k, 141.74 + 53.303771 * k, 207.14 + 2.453732 * k,
         154.84 + 7.306860 * k, 34.52 + 27.261239 * k, 207.19 + 0.121824 * k,
         291.34 + 1.844379 * k, 161.72 + 24.198154 * k, 239.56 + 25.513099 * k,
         331.55 + 3.592518 * k]
    w = [0.000325, 0.000165, 0.000164, 0.000126, 0.000110, 0.000062, 0.000060,
         0.000056, 0.000047, 0.000042, 0.000040, 0.000037, 0.000035, 0.000023]
    corr += sum(wi * math.sin(math.radians(ai)) for wi, ai in zip(w, a))
    return jde + corr


def _new_moon_dates(from_year: int, to_year: int) -> list[date]:
    """Beijing civil dates of the new-moon day across the given year span."""
    k0 = math.floor((from_year - 2000) * 12.3685) - 2
    k1 = math.ceil((to_year - 2000) * 12.3685) + 2
    out: list[date] = []
    for k in range(k0, k1 + 1):
        jde = new_moon_jde(k)
        jd_ut = jde - delta_t_seconds(2000 + k / 12.3685) / 86400.0
        d = jd_ut_to_beijing(jd_ut).date()
        if not out or d > out[-1]:
            out.append(d)
    return out


def _zhongqi_dates(year: int) -> list[date]:
    """Beijing dates of the 12 中气 spanning 农历 year ``year`` (雨水 -> 大寒)."""
    out = []
    for _, lon, month, yoff in ZHONGQI_TABLE:
        jd = solar_term_jd(lon, year + yoff, month)
        out.append(jd_ut_to_beijing(jd).date())
    return out


def lunar_to_gregorian(year: int, month: int, day: int, leap: bool = False) -> date:
    """Convert a 农历 date to the Gregorian date. Raises ValueError if invalid."""
    if not 1901 <= year <= 2099:
        raise ValueError("农历年份超出支持范围 (1901-2099)")
    if not 1 <= month <= 12:
        raise ValueError("农历月份必须为 1-12")
    if not 1 <= day <= 30:
        raise ValueError("农历日期必须为 1-30")

    moons = _new_moon_dates(year - 1, year + 1)
    zhongqi = _zhongqi_dates(year)

    zheng_start = None
    for i in range(len(moons) - 1):
        if moons[i] <= zhongqi[0] < moons[i + 1]:
            zheng_start = i
            break
    if zheng_start is None:
        raise ValueError("无法定位正月初一（节气推算失败）")

    next_zheng = None
    for i in range(zheng_start + 1, len(moons) - 1):
        if moons[i] <= zhongqi[11] < moons[i + 1]:
            next_zheng = i
            break

    months: list[tuple[int, bool, date, date]] = []
    expected = 0
    num = 0
    idx = zheng_start
    limit = next_zheng if next_zheng is not None else len(moons) - 1
    while idx < limit:
        start, end = moons[idx], moons[idx + 1]
        if expected < len(zhongqi) and start <= zhongqi[expected] < end:
            num += 1
            months.append((num, False, start, end))
            expected += 1
        else:
            months.append((num, True, start, end))
        idx += 1

    for m_num, m_leap, start, end in months:
        if m_num == month and m_leap == leap:
            if day > (end - start).days:
                raise ValueError(f"该农历月只有 {(end - start).days} 天")
            return start + timedelta(days=day - 1)
    kind = "闰" if leap else ""
    raise ValueError(f"农历 {year} 年不存在 {kind}{month} 月")


# --------------------------------------------------------------------------
# chart construction
# --------------------------------------------------------------------------

def _pillar(index: int) -> str:
    return GAN[index % 10] + ZHI[index % 12]


def ten_god(day_gan: str, other_gan: str) -> str:
    """十神 of ``other_gan`` seen from ``day_gan``.

    天干按 (甲乙)(丙丁)(戊己)(庚辛)(壬癸) 两两一组配五行, 组序即五行相生序
    (木->火->土->金->水)。阴阳看奇偶下标。
    """
    di, oi = GAN.index(day_gan), GAN.index(other_gan)
    rel = (oi // 2 - di // 2) % 5
    same_polarity = (di % 2) == (oi % 2)
    return SHISHEN_BY_REL[rel][0 if same_polarity else 1]


def branch_relations(a: str, b: str) -> str:
    """All relations between two branches as a slash-joined label."""
    out: list[str] = []
    if a == b:
        out.append("伏吟")
    for pair_set, label in ((LIU_HE, "六合"), (LIU_CHONG, "六冲"),
                            (LIU_HAI, "六害"), (AN_HE, "暗合")):
        if (a, b) in pair_set or (b, a) in pair_set:
            out.append(label)
    if a != b and ((a, b) in BAN_HE or (b, a) in BAN_HE):
        out.append("半合")
    if a != b:
        for grp in XING_GROUP:
            if a in grp and b in grp:
                out.append("相刑")
                break
    if {a, b} == {"子", "卯"}:
        out.append("相刑")
    if a == b and a in SELF_XING:
        out.append("自刑")
    return "/".join(dict.fromkeys(out)) if out else "—"


def xunkong(day_index: int) -> tuple[str, str]:
    first = ((day_index // 10) * 10) % 12
    return ZHI[(first + 10) % 12], ZHI[(first + 11) % 12]


def hongluan_tianxi(year_zhi: str) -> tuple[str, str]:
    i = ZHI.index(year_zhi)
    return ZHI[(3 - i) % 12], ZHI[(3 - i + 6) % 12]


def find_stars(pillars: dict, day_gan: str) -> dict:
    """Return {神煞: [所在柱]}."""
    branches = {k: v[1] for k, v in pillars.items()}
    stems = {k: v[0] for k, v in pillars.items()}
    year_zhi, month_zhi, day_zhi = branches["年"], branches["月"], branches["日"]

    def by_branch(target: str) -> list[str]:
        return [p for p, b in branches.items() if b == target]

    def by_stem(target: str) -> list[str]:
        return [p for p, s in stems.items() if s == target]

    raw: list[tuple[str, list[str]]] = [
        ("天乙贵人", [p for p, b in branches.items() if b in TIANYI[day_gan]]),
        ("文昌贵人", by_branch(WENCHANG[day_gan])),
        ("金舆", by_branch(JINYU[day_gan])),
        ("禄神", by_branch(GANLU[day_gan])),
        ("羊刃", by_branch(YANGREN[day_gan])),
        ("红艳煞", by_branch(HONGYAN[day_gan])),
        ("月德贵人", by_stem(YUEDE[SANHE_OF[month_zhi]])),
        ("天德贵人", by_stem(TIANDE[month_zhi]) + by_branch(TIANDE[month_zhi])),
        ("华盖", by_branch(HUAGAI[SANHE_OF[year_zhi]])),
        ("孤辰", by_branch(GUGUA[year_zhi][0])),
        ("寡宿", by_branch(GUGUA[year_zhi][1])),
        ("桃花(以日支起)", by_branch(TAOHUA[SANHE_OF[day_zhi]])),
        ("桃花(以年支起)", by_branch(TAOHUA[SANHE_OF[year_zhi]])),
        ("驿马(以日支起)", by_branch(YIMA[SANHE_OF[day_zhi]])),
        ("驿马(以年支起)", by_branch(YIMA[SANHE_OF[year_zhi]])),
    ]
    hl, tx = hongluan_tianxi(year_zhi)
    raw += [("红鸾", by_branch(hl)), ("天喜", by_branch(tx))]

    stars: dict[str, list[str]] = {}
    for name, positions in raw:
        if positions:
            stars[name] = sorted(set(positions), key=lambda p: "年月日时".index(p))
    if (pillars["日"] in YINCHA_YANGCUO):
        stars["阴差阳错日"] = ["日"]
    return stars


def _add_months(dt: datetime, months: int) -> datetime:
    total = dt.year * 12 + (dt.month - 1) + months
    y, m = divmod(total, 12)
    m += 1
    leap = (y % 4 == 0 and y % 100 != 0) or y % 400 == 0
    last = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return dt.replace(year=y, month=m, day=min(dt.day, last))


def build_chart(*, birth: datetime, gender: str, lon: float | None,
                day_boundary_hour: int = 23) -> dict:
    """Build the full chart from a Beijing-clock birth datetime."""
    gender_cn = "男" if gender.lower().startswith("m") or gender == "男" else "女"

    if lon is None:
        clock, tst, lon_off, eot = birth, None, None, None
    else:
        tst, lon_off, eot = true_solar_time(birth, lon)
        clock = tst

    # 日柱: 子时换日
    # day_boundary_hour=23 -> 子时换日: 23:00 起算次日
    # day_boundary_hour=0  -> 零点换日: 民用日期即日柱日期, 不位移
    if day_boundary_hour == 23 and clock.hour >= 23:
        eff = clock + timedelta(days=1)
    else:
        eff = clock
    jdn = int(julian_day(eff.year, eff.month, eff.day, 0.0) + 0.5)
    day_index = (jdn - 11) % 60

    # 时柱
    hour_zhi_i = ((clock.hour + 1) // 2) % 12
    hour_gan_i = ((day_index % 10) * 2 + hour_zhi_i) % 10
    hour_index = next(i for i in range(60)
                      if i % 10 == hour_gan_i and i % 12 == hour_zhi_i)

    # 节令窗口 (前一年 ~ 后一年), 用于年柱/月柱/大运
    window: list[tuple[str, datetime]] = []
    for y in (clock.year - 1, clock.year, clock.year + 1):
        for i, name in enumerate(JIE_ORDER):
            window.append((name, jie_datetime(y, i)))
    window.sort(key=lambda x: x[1])

    lichun = next(dt for name, dt in window if name == "立春" and dt.year == clock.year)
    year_index = (((clock.year - 1) if clock < lichun else clock.year) - 4) % 60

    month_idx = None
    for i in range(len(window) - 1):
        if window[i][1] <= clock < window[i + 1][1]:
            month_idx = JIE_ORDER.index(window[i][0])
            break
    if month_idx is None:  # pragma: no cover
        raise ValueError("无法定位月建")

    month_branch_i = (2 + month_idx) % 12
    month_gan_i = ((year_index % 10) * 2 + 2 + month_idx) % 10
    month_index = next(i for i in range(60)
                       if i % 10 == month_gan_i and i % 12 == month_branch_i)

    pillars = {"年": _pillar(year_index), "月": _pillar(month_index),
               "日": _pillar(day_index), "时": _pillar(hour_index)}
    day_gan = pillars["日"][0]

    # 大运
    yang_year = (year_index % 10) % 2 == 0
    forward = (yang_year and gender_cn == "男") or (not yang_year and gender_cn == "女")
    if forward:
        nxt = next(dt for _, dt in window if dt > clock)
        span_days = (nxt - clock).total_seconds() / 86400.0
        direction, prev_jie, next_jie = "顺排", None, nxt
    else:
        prv = [dt for _, dt in window if dt <= clock][-1]
        span_days = (clock - prv).total_seconds() / 86400.0
        direction, prev_jie, next_jie = "逆排", prv, None

    years_f = span_days / 3.0
    start_years = int(years_f)
    start_months = int(round((years_f - start_years) * 12))
    if start_months >= 12:
        start_years, start_months = start_years + 1, start_months - 12
    start_dt = _add_months(birth, start_years * 12 + start_months)

    step = 1 if forward else -1
    luck = []
    for n in range(1, 13):
        idx = (month_index + step * n) % 60
        d_from = _add_months(start_dt, (n - 1) * 120)
        d_to = _add_months(start_dt, n * 120)
        age = start_years + (n - 1) * 10
        luck.append({
            "序号": n,
            "干支": _pillar(idx),
            "干十神": ten_god(day_gan, GAN[idx % 10]),
            "周岁": f"{age}-{age + 9}",
            "交运": d_from.strftime("%Y-%m-%d"),
            "止运": d_to.strftime("%Y-%m-%d"),
            "与日支": branch_relations(ZHI[idx % 12], pillars["日"][1]),
            "与年支": branch_relations(ZHI[idx % 12], pillars["年"][1]),
            "_from": d_from, "_to": d_to,
        })

    # 边界提醒
    warns = []
    nearest_jie = min(window, key=lambda x: abs((x[1] - clock).total_seconds()))
    gap_min_jie = abs((nearest_jie[1] - clock).total_seconds()) / 60.0
    if gap_min_jie <= 60:
        warns.append(f"出生时刻距「{nearest_jie[0]}」仅 {gap_min_jie:.0f} 分钟, 本引擎节气推算"
                     f"误差约±15分钟, 年柱或月柱可能受影响的临界情形, 请用星历复核")
    mins = clock.hour * 60 + clock.minute
    gap_min_zhi = min(abs(mins - b * 60) for b in range(-1, 26, 2))  # 时辰起于奇数整点
    if gap_min_zhi <= 30:
        warns.append(f"出生时刻距时辰交界仅 {gap_min_zhi:.0f} 分钟, 时柱在临界, "
                     f"建议用出生证明核对")

    return {
        "输入": {
            "公历": birth.strftime("%Y-%m-%d %H:%M"),
            "性别": gender_cn,
            "经度": lon,
            "真太阳时": tst.strftime("%Y-%m-%d %H:%M") if tst else None,
            "经度时差_分": round(lon_off, 2) if lon_off is not None else None,
            "均时差_分": round(eot, 2) if eot is not None else None,
            "日界": f"{day_boundary_hour}:00",
            "起运": f"{start_years}岁{start_months}个月",
            "交运日期": start_dt.strftime("%Y-%m-%d"),
        },
        "四柱": pillars,
        "十神": {k: ten_god(day_gan, v[0]) for k, v in pillars.items()},
        "藏干": {k: [(g, ten_god(day_gan, g)) for g in CANGGAN[v[1]]] for k, v in pillars.items()},
        "日主": f"{day_gan}({GAN_WX[day_gan]},{GAN_YINYANG[day_gan]})",
        "月令": pillars["月"][1],
        "空亡": list(xunkong(day_index)),
        "神煞": find_stars(pillars, day_gan),
        "大运": {"方向": direction,
                 "上一个节": prev_jie.strftime("%Y-%m-%d %H:%M") if prev_jie else None,
                 "下一个节": next_jie.strftime("%Y-%m-%d %H:%M") if next_jie else None,
                 "列表": luck},
        "提醒": warns,
        "_day_branch": pillars["日"][1],
        "_year_branch": pillars["年"][1],
        "_day_gan": day_gan,
    }


def scan_years(chart: dict, y0: int, y1: int) -> list[dict]:
    """Per-year romance triggers: ten-god, branch relations, key stars."""
    day_branch = chart["_day_branch"]
    year_branch = chart["_year_branch"]
    day_gan = chart["_day_gan"]
    hl, tx = hongluan_tianxi(year_branch)
    out = []
    for y in range(y0, y1 + 1):
        idx = (y - 4) % 60
        g, z = GAN[idx % 10], ZHI[idx % 12]
        flags = []
        if z == TAOHUA[SANHE_OF[day_branch]]:
            flags.append("桃花(日支起)")
        if z == TAOHUA[SANHE_OF[year_branch]]:
            flags.append("桃花(年支起)")
        if z == hl:
            flags.append("红鸾")
        if z == tx:
            flags.append("天喜")
        if z == YIMA[SANHE_OF[day_branch]]:
            flags.append("驿马")
        if z == YIMA[SANHE_OF[year_branch]]:
            flags.append("驿马(年支起)")
        if z in chart["空亡"]:
            flags.append("落空亡")
        god = ten_god(day_gan, g)
        if god in ("正财", "偏财"):
            flags.append(f"财星透干·{god}")
        this_year = datetime(y, 7, 1)
        luck = next((lu["干支"] for lu in chart["大运"]["列表"]
                     if lu["_from"] <= this_year < lu["_to"]), "—")
        out.append({"年份": y, "干支": g + z, "年干十神": god,
                    "与日支(妻宫)": branch_relations(z, day_branch),
                    "与年支": branch_relations(z, year_branch),
                    "所在大运": luck, "姻缘信号": flags})
    return out


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def render(chart: dict, years: list[dict] | None) -> str:
    L: list[str] = []
    inp = chart["输入"]
    L += ["=" * 66, "八字排盘 / BaZi Chart", "=" * 66]
    L.append(f"公历    : {inp['公历']}  ({inp['性别']}命)")
    if inp["真太阳时"]:
        L.append(f"真太阳时 : {inp['真太阳时']}"
                 f"   [经度差 {inp['经度时差_分']:+.1f} 分, 均时差 {inp['均时差_分']:+.1f} 分]")
    L.append(f"日界    : {inp['日界']} 换日")
    L.append("")

    p, sh = chart["四柱"], chart["十神"]
    L.append("          年         月         日         时")
    L.append(f"干支   {p['年']}       {p['月']}       {p['日']}       {p['时']}")
    L.append(f"十神   {sh['年']:<4}      {sh['月']:<4}      {sh['日']:<4}      {sh['时']:<4}")
    for key in ("年", "月", "日", "时"):
        txt = " ".join(f"{g}({s})" for g, s in chart["藏干"][key])
        L.append(f"{key}支藏干 {txt}")
    L.append("")
    L.append(f"日主: {chart['日主']}    月令: {chart['月令']}    空亡: {'、'.join(chart['空亡'])}")
    L.append("")
    L.append(f"起运: {inp['起运']}    交运: {inp['交运日期']}")

    L.append("")
    L.append("-- 神煞 " + "-" * 56)
    for star, pos in chart["神煞"].items():
        tag = "  ★姻缘" if star in MARRIAGE_STARS else ""
        L.append(f"  {star:<16}{'、'.join(pos)}柱{tag}")
    if not chart["神煞"]:
        L.append("  (无)")

    lu = chart["大运"]
    L.append("")
    L.append("-- 大运 " + "-" * 56)
    L.append(f"  {lu['方向']}   上一个节 {lu['上一个节'] or '—'}   下一个节 {lu['下一个节'] or '—'}")
    L.append(f"  {'大运':<6}{'十神':<6}{'周岁':<9}{'交运':<12}{'止运':<12}{'与日支':<12}{'与年支'}")
    for it in lu["列表"]:
        L.append(f"  {it['干支']:<6}{it['干十神']:<6}{it['周岁']:<9}"
                 f"{it['交运']:<12}{it['止运']:<12}{it['与日支']:<12}{it['与年支']}")

    if years:
        L.append("")
        L.append("-- 流年扫描 " + "-" * 52)
        L.append(f"  {'年':<6}{'干支':<6}{'十神':<6}{'大运':<6}{'与日支':<12}{'与年支':<12}信号")
        for r in years:
            L.append(f"  {r['年份']:<6}{r['干支']:<6}{r['年干十神']:<6}{r['所在大运']:<6}"
                     f"{r['与日支(妻宫)']:<12}{r['与年支']:<12}"
                     f"{' '.join(r['姻缘信号']) or '—'}")

    if chart["提醒"]:
        L.append("")
        L.append("-- 精度提醒 " + "-" * 54)
        for w in chart["提醒"]:
            L.append(f"  ! {w}")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="八字排盘引擎 / BaZi chart builder")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--date", help="公历出生日期 YYYY-MM-DD")
    src.add_argument("--lunar", help="农历出生日期 YYYY-MM-DD")
    ap.add_argument("--leap", action="store_true", help="农历输入为闰月")
    ap.add_argument("--time", default="12:00", help="出生时间 HH:MM (北京时间)")
    ap.add_argument("--gender", required=True, choices=["male", "female", "男", "女"])
    ap.add_argument("--lon", type=float, default=None,
                    help="出生地经度(东经为正), 例如 104.1; 给了就换算真太阳时")
    ap.add_argument("--day-boundary", type=int, default=23, choices=[0, 23],
                    help="日柱换日时刻: 23(子时换日,默认) 或 0(零点换日)")
    ap.add_argument("--years", help="流年扫描范围, 例如 2026-2040")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)

    try:
        if args.date:
            d = datetime.strptime(args.date, "%Y-%m-%d").date()
        else:
            ly, lm, ld = (int(x) for x in args.lunar.split("-"))
            d = lunar_to_gregorian(ly, lm, ld, args.leap)
        hh, mm = (int(x) for x in args.time.split(":"))
        birth = datetime(d.year, d.month, d.day, hh, mm)
    except ValueError as exc:
        print(f"输入错误: {exc}", file=sys.stderr)
        return 2

    chart = build_chart(birth=birth, gender=args.gender, lon=args.lon,
                        day_boundary_hour=args.day_boundary)

    years = None
    if args.years:
        y0, y1 = (int(x) for x in args.years.split("-"))
        years = scan_years(chart, y0, y1)

    if args.json:
        out = {k: v for k, v in chart.items() if not k.startswith("_")}
        out["大运"]["列表"] = [{k: v for k, v in it.items() if not k.startswith("_")}
                             for it in out["大运"]["列表"]]
        if years is not None:
            out["流年"] = years
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(render(chart, years))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
