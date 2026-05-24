"""
fish-price-master.json 生成スクリプト

- 月報最新月（wholesale-prices.json の months[-1]）のみを採用
- 業界一般値カテゴリ × 大物プレミアム倍率 で size_bands を構築
- size_weight_curve は cm 入力魚種のみ・体型別の経験値カーブを採用

実行: python docs/fish-value/generate_price_master.py
出力: docs/fish-value/fish-price-master.json
"""

import json
import os
from datetime import date

BASE = os.path.dirname(os.path.abspath(__file__))


# ---- 体型別 size_weight_curve（cm 入力魚種で使用） --------------------
# 経験値ベース。各魚種で参考にしたエビデンス:
#  - 細長型: アジ/キス/タチウオ/アナゴ/カマス/コノシロ/ボラ/ハゼ/カタクチイワシ/ウルメイワシ
#  - 標準型: マイワシ/イサキ/ハナダイ/ホウボウ/メバル/カサゴ/イシモチ
#  - 体高型: カワハギ/カレイ/コチ/オニカサゴ
#  - 平体型: ヒラメ/マゴチ
SIZE_CURVES = {
    "細長型": [
        {"cm": 10, "kg": 0.010},
        {"cm": 15, "kg": 0.035},
        {"cm": 20, "kg": 0.080},
        {"cm": 25, "kg": 0.160},
        {"cm": 30, "kg": 0.280},
        {"cm": 40, "kg": 0.650},
        {"cm": 50, "kg": 1.200},
    ],
    "標準型": [
        {"cm": 10, "kg": 0.025},
        {"cm": 15, "kg": 0.070},
        {"cm": 20, "kg": 0.150},
        {"cm": 25, "kg": 0.300},
        {"cm": 30, "kg": 0.520},
        {"cm": 40, "kg": 1.200},
    ],
    "体高型": [
        {"cm": 10, "kg": 0.030},
        {"cm": 15, "kg": 0.090},
        {"cm": 20, "kg": 0.200},
        {"cm": 25, "kg": 0.380},
        {"cm": 30, "kg": 0.650},
        {"cm": 35, "kg": 1.000},
    ],
    "平体型": [
        {"cm": 20, "kg": 0.180},
        {"cm": 30, "kg": 0.500},
        {"cm": 40, "kg": 1.100},
        {"cm": 50, "kg": 2.000},
        {"cm": 60, "kg": 3.200},
        {"cm": 70, "kg": 4.800},
    ],
    "超細長型": [  # タチウオ・アナゴ系
        {"cm": 50, "kg": 0.200},
        {"cm": 80, "kg": 0.500},
        {"cm": 100, "kg": 0.900},
        {"cm": 120, "kg": 1.500},
        {"cm": 140, "kg": 2.200},
    ],
}


# ---- 倍率カテゴリ別 base 小売倍率 ------------------------------------
# Phase 1 採用: 業界一般値（甲案）
# 検証: docs/fish-value/tmp_retail_verify.md（小売物価統計 vs 月報 実倍率）
CATEGORIES = {
    "大衆魚":   {"base_low": 2.0, "base_high": 3.0},
    "中級魚":   {"base_low": 1.8, "base_high": 2.5},
    "高級魚":   {"base_low": 1.6, "base_high": 2.2},
    "青物":     {"base_low": 1.7, "base_high": 2.4},
    "イカタコ": {"base_low": 1.8, "base_high": 2.6},
}


# ---- size_class 倍率ブースト（大物プレミアム）-------------------------
SIZE_CLASS_MULT = {
    "small":    0.95,
    "standard": 1.00,
    "large":    1.20,
    "premium":  1.45,
}


# ---- 各 pfid のサイズ帯設計 -------------------------------------------
# {pfid: {category, size_curve, bands}}
# size_curve は cm 入力魚種のみ・kg 入力魚種は None
# bands: kg_max 昇順・最後の帯は kg_max=999 必須
PRICE_DESIGN = {
    # ───── 大衆魚 ─────
    "maaji": {
        "category": "大衆魚", "curve": "細長型",
        "bands": [
            {"kg_max": 0.05, "label": "豆アジ",   "size_class": "small"},
            {"kg_max": 0.15, "label": "中小",     "size_class": "small"},
            {"kg_max": 0.30, "label": "中",       "size_class": "standard"},
            {"kg_max": 999,  "label": "大・尺",   "size_class": "large"},
        ],
    },
    "saba": {
        "category": "大衆魚", "curve": "細長型",
        "bands": [
            {"kg_max": 0.3, "label": "小サバ",   "size_class": "small"},
            {"kg_max": 0.8, "label": "中サバ",   "size_class": "standard"},
            {"kg_max": 1.5, "label": "大サバ",   "size_class": "large"},
            {"kg_max": 999, "label": "寒サバ",   "size_class": "premium"},
        ],
    },
    "maiwashi": {
        "category": "大衆魚", "curve": "標準型",
        "bands": [
            {"kg_max": 0.05, "label": "小羽",   "size_class": "small"},
            {"kg_max": 0.12, "label": "中羽",   "size_class": "standard"},
            {"kg_max": 999,  "label": "大羽",   "size_class": "large"},
        ],
    },
    "shirogisu": {
        "category": "大衆魚", "curve": "細長型",
        "bands": [
            {"kg_max": 0.03, "label": "小ピン", "size_class": "small"},
            {"kg_max": 0.08, "label": "標準",   "size_class": "standard"},
            {"kg_max": 0.15, "label": "良型",   "size_class": "large"},
            {"kg_max": 999,  "label": "尺キス", "size_class": "premium"},
        ],
    },
    "bora": {
        "category": "大衆魚", "curve": "細長型",
        "bands": [
            {"kg_max": 0.5, "label": "中",     "size_class": "standard"},
            {"kg_max": 999, "label": "大",     "size_class": "large"},
        ],
    },
    "katakuchiiwashi": {
        "category": "大衆魚", "curve": "標準型",
        "bands": [
            {"kg_max": 999, "label": "標準",   "size_class": "standard"},
        ],
    },
    "urumeiwashi": {
        "category": "大衆魚", "curve": "標準型",
        "bands": [
            {"kg_max": 999, "label": "標準",   "size_class": "standard"},
        ],
    },
    "soudagatsuo": {
        "category": "大衆魚", "curve": None,
        "bands": [
            {"kg_max": 999, "label": "標準",   "size_class": "standard"},
        ],
    },
    "konoshiro": {
        "category": "大衆魚", "curve": "細長型",
        "bands": [
            {"kg_max": 0.05, "label": "シンコ", "size_class": "premium"},  # 寿司ネタ希少
            {"kg_max": 0.10, "label": "コハダ", "size_class": "standard"},
            {"kg_max": 0.20, "label": "ナカズミ","size_class": "small"},
            {"kg_max": 999,  "label": "コノシロ","size_class": "small"},
        ],
    },
    "ishimochi": {
        "category": "大衆魚", "curve": "細長型",
        "bands": [
            {"kg_max": 0.3, "label": "中",     "size_class": "standard"},
            {"kg_max": 999, "label": "大",     "size_class": "large"},
        ],
    },
    "haze": {
        "category": "大衆魚", "curve": "細長型",
        "bands": [
            {"kg_max": 0.05, "label": "デキ",   "size_class": "small"},
            {"kg_max": 0.15, "label": "良型",   "size_class": "standard"},
            {"kg_max": 999,  "label": "落ちハゼ","size_class": "large"},
        ],
        "fallback_wholesale_avg": 1200,
        "fallback_wholesale_high": 2800,
        "fallback_wholesale_low": 500,
        "fallback_note": "月報単独項目なし。江戸前ハゼは季節商品で経験値運用",
    },

    # ───── 中級魚 ─────
    "madai": {
        "category": "中級魚", "curve": None,
        "bands": [
            {"kg_max": 0.5, "label": "小ダイ",   "size_class": "small"},
            {"kg_max": 1.5, "label": "標準",     "size_class": "standard"},
            {"kg_max": 3.0, "label": "大ダイ",   "size_class": "large"},
            {"kg_max": 999, "label": "特大",     "size_class": "premium"},
        ],
    },
    "kurodai": {
        "category": "中級魚", "curve": None,
        "bands": [
            {"kg_max": 0.5, "label": "小型",     "size_class": "small"},
            {"kg_max": 1.5, "label": "標準",     "size_class": "standard"},
            {"kg_max": 999, "label": "年無し",   "size_class": "large"},
        ],
    },
    "hanadai": {
        "category": "中級魚", "curve": "標準型",
        "bands": [
            {"kg_max": 0.3, "label": "小",       "size_class": "small"},
            {"kg_max": 999, "label": "標準",     "size_class": "standard"},
        ],
    },
    "kawahagi": {
        "category": "中級魚", "curve": "体高型",
        "bands": [
            {"kg_max": 0.10, "label": "小",     "size_class": "small"},
            {"kg_max": 0.20, "label": "標準",   "size_class": "standard"},
            {"kg_max": 0.35, "label": "良型",   "size_class": "large"},
            {"kg_max": 999,  "label": "尺ハギ", "size_class": "premium"},
        ],
    },
    "hirame": {
        "category": "中級魚", "curve": None,
        "bands": [
            {"kg_max": 0.5, "label": "ソゲ",     "size_class": "small"},
            {"kg_max": 1.5, "label": "標準",     "size_class": "standard"},
            {"kg_max": 3.0, "label": "大ビラメ", "size_class": "large"},
            {"kg_max": 999, "label": "座布団",   "size_class": "premium"},
        ],
    },
    "isaki": {
        "category": "中級魚", "curve": "標準型",
        "bands": [
            {"kg_max": 0.15, "label": "瓜坊",   "size_class": "small"},
            {"kg_max": 0.40, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999,  "label": "良型",   "size_class": "large"},
        ],
    },
    "karei": {
        "category": "中級魚", "curve": "体高型",
        "bands": [
            {"kg_max": 0.15, "label": "小",     "size_class": "small"},
            {"kg_max": 0.40, "label": "標準",   "size_class": "standard"},
            {"kg_max": 0.80, "label": "良型",   "size_class": "large"},
            {"kg_max": 999,  "label": "大型",   "size_class": "premium"},
        ],
    },
    "kasago": {
        "category": "中級魚", "curve": "標準型",
        "bands": [
            {"kg_max": 0.15, "label": "小",     "size_class": "small"},
            {"kg_max": 0.40, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999,  "label": "尺カサゴ","size_class": "large"},
        ],
    },
    "oki-kasago": {
        "category": "中級魚", "curve": "標準型",
        "bands": [
            {"kg_max": 0.30, "label": "小",     "size_class": "small"},
            {"kg_max": 0.80, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999,  "label": "良型",   "size_class": "large"},
        ],
    },
    "mebaru": {
        "category": "中級魚", "curve": "標準型",
        "bands": [
            {"kg_max": 0.10, "label": "小",     "size_class": "small"},
            {"kg_max": 0.25, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999,  "label": "尺メバル","size_class": "large"},
        ],
    },
    "oki-mebaru": {
        "category": "中級魚", "curve": "標準型",
        "bands": [
            {"kg_max": 0.20, "label": "小",     "size_class": "small"},
            {"kg_max": 0.45, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999,  "label": "良型",   "size_class": "large"},
        ],
    },
    "houbou": {
        "category": "中級魚", "curve": "標準型",
        "bands": [
            {"kg_max": 0.30, "label": "小",     "size_class": "small"},
            {"kg_max": 0.80, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999,  "label": "良型",   "size_class": "large"},
        ],
    },
    "magochi": {
        "category": "中級魚", "curve": None,
        "bands": [
            {"kg_max": 0.5, "label": "小",       "size_class": "small"},
            {"kg_max": 1.5, "label": "標準",     "size_class": "standard"},
            {"kg_max": 999, "label": "良型",     "size_class": "large"},
        ],
    },
    "onikasago": {
        "category": "中級魚", "curve": "体高型",
        "bands": [
            {"kg_max": 0.3, "label": "小",       "size_class": "small"},
            {"kg_max": 0.8, "label": "標準",     "size_class": "standard"},
            {"kg_max": 999, "label": "良型",     "size_class": "large"},
        ],
    },
    "anago": {
        "category": "中級魚", "curve": "超細長型",
        "bands": [
            {"kg_max": 0.15, "label": "小",     "size_class": "small"},
            {"kg_max": 0.35, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999,  "label": "メガアナゴ","size_class": "large"},
        ],
    },
    "kamasu": {
        "category": "中級魚", "curve": "細長型",
        "bands": [
            {"kg_max": 0.15, "label": "小",     "size_class": "small"},
            {"kg_max": 0.35, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999,  "label": "尺カマス","size_class": "large"},
        ],
    },
    "ishidai": {
        "category": "中級魚", "curve": None,
        "bands": [
            {"kg_max": 0.5, "label": "サンバソウ","size_class": "small"},
            {"kg_max": 1.5, "label": "標準",     "size_class": "standard"},
            {"kg_max": 999, "label": "大型",     "size_class": "large"},
        ],
    },
    "medai": {
        "category": "中級魚", "curve": None,
        "bands": [
            {"kg_max": 1.0, "label": "小",       "size_class": "small"},
            {"kg_max": 3.0, "label": "標準",     "size_class": "standard"},
            {"kg_max": 999, "label": "大型",     "size_class": "large"},
        ],
    },

    # ───── 青物 ─────
    "katsuo": {
        "category": "青物", "curve": None,
        "bands": [
            {"kg_max": 2.0, "label": "ヒラソウダ級","size_class": "small"},
            {"kg_max": 4.0, "label": "標準",       "size_class": "standard"},
            {"kg_max": 999, "label": "戻りガツオ", "size_class": "large"},
        ],
    },
    "buri": {
        "category": "青物", "curve": None,
        "bands": [
            {"kg_max": 5.0, "label": "標準",     "size_class": "standard"},
            {"kg_max": 999, "label": "寒ブリ大物","size_class": "premium"},
        ],
    },
    "warasa": {
        "category": "青物", "curve": None,
        "bands": [
            {"kg_max": 3.0, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大ワラサ","size_class": "large"},
        ],
    },
    "inada": {
        "category": "青物", "curve": None,
        "bands": [
            {"kg_max": 1.5, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "良型",   "size_class": "large"},
        ],
    },
    "kanpachi": {
        "category": "青物", "curve": None,
        "bands": [
            {"kg_max": 2.0, "label": "小カンパチ","size_class": "small"},
            {"kg_max": 5.0, "label": "標準",     "size_class": "standard"},
            {"kg_max": 999, "label": "大型",     "size_class": "large"},
        ],
    },
    "hiramasa": {
        "category": "青物", "curve": None,
        "bands": [
            {"kg_max": 3.0, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大型",   "size_class": "large"},
        ],
    },
    "sawara": {
        "category": "青物", "curve": None,
        "bands": [
            {"kg_max": 1.5, "label": "サゴシ", "size_class": "small"},
            {"kg_max": 4.0, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大サワラ","size_class": "large"},
        ],
    },
    "kihada": {
        "category": "青物", "curve": None,
        "bands": [
            {"kg_max": 10,  "label": "小",     "size_class": "small"},
            {"kg_max": 30,  "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大型",   "size_class": "large"},
        ],
    },
    "kimeji": {
        "category": "青物", "curve": None,
        "bands": [
            {"kg_max": 5,   "label": "小",     "size_class": "small"},
            {"kg_max": 999, "label": "標準",   "size_class": "standard"},
        ],
    },
    "shimaaji": {
        "category": "青物", "curve": None,
        "bands": [
            {"kg_max": 1.0, "label": "小型",   "size_class": "small"},
            {"kg_max": 3.0, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大シマアジ","size_class": "premium"},
        ],
    },
    "mahata": {
        "category": "青物", "curve": None,
        "bands": [
            {"kg_max": 2.0, "label": "小",     "size_class": "small"},
            {"kg_max": 5.0, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大ハタ", "size_class": "premium"},
        ],
    },
    "hata": {
        "category": "青物", "curve": None,
        "bands": [
            {"kg_max": 2.0, "label": "小",     "size_class": "small"},
            {"kg_max": 5.0, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大ハタ", "size_class": "premium"},
        ],
    },
    "seabass": {
        "category": "青物", "curve": None,
        "bands": [
            {"kg_max": 1.0, "label": "セイゴ", "size_class": "small"},
            {"kg_max": 3.0, "label": "フッコ", "size_class": "standard"},
            {"kg_max": 999, "label": "スズキ", "size_class": "large"},
        ],
    },
    "shiira": {
        "category": "青物", "curve": None,
        "bands": [
            {"kg_max": 3.0, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大シイラ","size_class": "large"},
        ],
    },
    "tachiuo": {
        "category": "青物", "curve": "超細長型",
        "bands": [
            {"kg_max": 0.3, "label": "ベルト",  "size_class": "small"},
            {"kg_max": 0.7, "label": "標準",    "size_class": "standard"},
            {"kg_max": 1.2, "label": "良型",    "size_class": "large"},
            {"kg_max": 999, "label": "ドラゴン","size_class": "premium"},
        ],
    },

    # ───── 高級魚 ─────
    "amadai": {
        "category": "高級魚", "curve": None,
        "bands": [
            {"kg_max": 0.4, "label": "小型",   "size_class": "small"},
            {"kg_max": 1.0, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大アマダイ","size_class": "premium"},
        ],
    },
    "shiro-amadai": {
        "category": "高級魚", "curve": None,
        "bands": [
            {"kg_max": 0.4, "label": "小型",   "size_class": "small"},
            {"kg_max": 1.0, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大型",   "size_class": "premium"},
        ],
        "derived_from": "amadai",
        "derived_ratio_low": 2.0,
        "derived_ratio_high": 3.0,
    },
    "kinmedai": {
        "category": "高級魚", "curve": None,
        "bands": [
            {"kg_max": 0.5, "label": "小",     "size_class": "small"},
            {"kg_max": 1.5, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大金目", "size_class": "premium"},
        ],
    },
    "kuromutsu": {
        "category": "高級魚", "curve": None,
        "bands": [
            {"kg_max": 0.5, "label": "小",     "size_class": "small"},
            {"kg_max": 1.5, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大ムツ", "size_class": "premium"},
        ],
    },
    "akamutsu": {
        "category": "高級魚", "curve": None,
        "bands": [
            {"kg_max": 0.3, "label": "小",     "size_class": "small"},
            {"kg_max": 0.8, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大ノドグロ","size_class": "premium"},
        ],
        "fallback_wholesale_avg": 6000,
        "fallback_wholesale_high": 12000,
        "fallback_wholesale_low": 3500,
        "fallback_note": "月報単独項目なし。市場相場（むつ 2,381円/kg より明確に高く・5,000-10,000円/kg帯）の経験値",
    },
    "abura-bouzu": {
        "category": "高級魚", "curve": None,
        "bands": [
            {"kg_max": 5,   "label": "小",     "size_class": "small"},
            {"kg_max": 15,  "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大型",   "size_class": "large"},
        ],
        "fallback_wholesale_avg": 1500,
        "fallback_wholesale_high": 3500,
        "fallback_wholesale_low": 700,
        "fallback_note": "月報単独項目なし。深海魚で流通少・経験値",
    },
    "ara": {
        "category": "高級魚", "curve": None,
        "bands": [
            {"kg_max": 2,   "label": "小",     "size_class": "small"},
            {"kg_max": 6,   "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大型",   "size_class": "premium"},
        ],
        "fallback_wholesale_avg": 4500,
        "fallback_wholesale_high": 10000,
        "fallback_wholesale_low": 2200,
        "fallback_note": "月報単独項目なし。九州系高級魚・経験値",
    },
    "kaiwari": {
        "category": "高級魚", "curve": "細長型",
        "bands": [
            {"kg_max": 0.3, "label": "小",     "size_class": "small"},
            {"kg_max": 999, "label": "標準",   "size_class": "standard"},
        ],
        "fallback_wholesale_avg": 1800,
        "fallback_wholesale_high": 3500,
        "fallback_wholesale_low": 800,
        "fallback_note": "月報単独項目なし。アジ科高級魚・経験値",
    },
    "kanko": {
        "category": "高級魚", "curve": "標準型",
        "bands": [
            {"kg_max": 0.3, "label": "小",     "size_class": "small"},
            {"kg_max": 999, "label": "標準",   "size_class": "standard"},
        ],
        "fallback_wholesale_avg": 2000,
        "fallback_wholesale_high": 4500,
        "fallback_wholesale_low": 900,
        "fallback_note": "月報単独項目なし。経験値",
    },
    "kintoki": {
        "category": "高級魚", "curve": "標準型",
        "bands": [
            {"kg_max": 0.3, "label": "小",     "size_class": "small"},
            {"kg_max": 0.8, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "良型",   "size_class": "large"},
        ],
        "fallback_wholesale_avg": 1500,
        "fallback_wholesale_high": 3500,
        "fallback_wholesale_low": 700,
        "fallback_note": "月報単独項目なし。経験値",
    },
    "moroko": {
        "category": "高級魚", "curve": "細長型",
        "bands": [
            {"kg_max": 999, "label": "標準",   "size_class": "standard"},
        ],
        "fallback_wholesale_avg": 1200,
        "fallback_wholesale_high": 2800,
        "fallback_wholesale_low": 600,
        "fallback_note": "月報単独項目なし。経験値",
    },
    "menuke": {
        "category": "高級魚", "curve": None,
        "bands": [
            {"kg_max": 1.0, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "良型",   "size_class": "large"},
        ],
    },
    "torafugu": {
        "category": "高級魚", "curve": None,
        "bands": [
            {"kg_max": 1.0, "label": "小",     "size_class": "small"},
            {"kg_max": 2.5, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大型",   "size_class": "premium"},
        ],
    },
    "akamefugu": {
        "category": "高級魚", "curve": None,
        "bands": [
            {"kg_max": 0.5, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "良型",   "size_class": "large"},
        ],
    },
    "fugu": {
        "category": "高級魚", "curve": None,
        "bands": [
            {"kg_max": 0.5, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "良型",   "size_class": "large"},
        ],
    },
    "shousaifugu": {
        "category": "高級魚", "curve": None,
        "bands": [
            {"kg_max": 0.5, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "良型",   "size_class": "large"},
        ],
    },

    # ───── イカタコ ─────
    "surumeika": {
        "category": "イカタコ", "curve": None,
        "bands": [
            {"kg_max": 0.2, "label": "小",     "size_class": "small"},
            {"kg_max": 0.5, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大型",   "size_class": "large"},
        ],
    },
    "mugiika": {
        "category": "イカタコ", "curve": None,
        "bands": [
            {"kg_max": 0.10, "label": "小",   "size_class": "small"},
            {"kg_max": 999,  "label": "標準", "size_class": "standard"},
        ],
    },
    "sujiika": {
        "category": "イカタコ", "curve": None,
        "bands": [
            {"kg_max": 0.20, "label": "小",   "size_class": "small"},
            {"kg_max": 999,  "label": "標準", "size_class": "standard"},
        ],
    },
    "yariika": {
        "category": "イカタコ", "curve": None,
        "bands": [
            {"kg_max": 0.20, "label": "小",   "size_class": "small"},
            {"kg_max": 0.50, "label": "標準", "size_class": "standard"},
            {"kg_max": 999,  "label": "大",   "size_class": "large"},
        ],
    },
    "aoriika": {
        "category": "イカタコ", "curve": None,
        "bands": [
            {"kg_max": 0.5, "label": "小",     "size_class": "small"},
            {"kg_max": 1.5, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "キロアップ","size_class": "premium"},
        ],
    },
    "maruika": {
        "category": "イカタコ", "curve": None,
        "bands": [
            {"kg_max": 0.20, "label": "小",   "size_class": "small"},
            {"kg_max": 999,  "label": "標準", "size_class": "standard"},
        ],
    },
    "sumiika": {
        "category": "イカタコ", "curve": None,
        "bands": [
            {"kg_max": 0.5, "label": "小",     "size_class": "small"},
            {"kg_max": 1.5, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大型",   "size_class": "large"},
        ],
    },
    "mongoika": {
        "category": "イカタコ", "curve": None,
        "bands": [
            {"kg_max": 1.0, "label": "小",     "size_class": "small"},
            {"kg_max": 3.0, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大型",   "size_class": "large"},
        ],
    },
    "madako": {
        "category": "イカタコ", "curve": None,
        "bands": [
            {"kg_max": 1.0, "label": "小",     "size_class": "small"},
            {"kg_max": 3.0, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大ダコ", "size_class": "premium"},
        ],
    },

    # ───── 専用処理（アンコウ・その他） ─────
    "ankou": {
        "category": "高級魚", "curve": None,
        "bands": [
            {"kg_max": 3,   "label": "小",     "size_class": "small"},
            {"kg_max": 8,   "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大物",   "size_class": "large"},
        ],
    },
}


def build_size_bands(design, avg, hi, lo):
    """月報avg/high/lowをベースに size_bands を構築。
    各 size_class でサイズ帯の卸売範囲を絞り、ブースト倍率を適用。

    設計:
      small    → 卸 [lo, avg]            （安い帯）
      standard → 卸 [lo×1.5, avg×1.5]    （平均±50%）
      large    → 卸 [avg, hi×0.8]        （avg〜high寄り）
      premium  → 卸 [avg×1.5, hi]        （high 寄り）
    """
    cat = CATEGORIES[design['category']]

    # 帯別の卸売範囲決定（avg/hi/lo から導出）
    # 上限ガード: high が hi の外れ値で広がりすぎないよう lo×倍率で抑える
    # 下限ガード: 同様に avg×係数で底打ち
    band_ranges = {
        'small':    (lo,
                     min(avg, int(lo * 3.0))),
        'standard': (max(int(lo * 1.5), int(avg * 0.7)),
                     min(int(avg * 1.5), int(lo * 5.0))),
        'large':    (avg,
                     min(int(avg * 2.5), int(hi * 0.8))),
        'premium':  (int(avg * 1.5),
                     hi),
    }

    bands_out = []
    for band in design['bands']:
        sc = band['size_class']
        mult = SIZE_CLASS_MULT[sc]
        wholesale_low, wholesale_high = band_ranges[sc]
        # 安全側: high ≥ low
        if wholesale_high < wholesale_low:
            wholesale_high = wholesale_low

        # 小売倍率: base × size_class_mult
        # size_class=standard は base そのまま、large/premium はブースト
        retail_low  = int(wholesale_low  * cat['base_low']  * mult)
        retail_high = int(wholesale_high * cat['base_high'] * mult)

        bands_out.append({
            'kg_max':         None if band['kg_max'] >= 999 else band['kg_max'],
            'label':          band['label'],
            'size_class':     sc,
            'wholesale_low':  wholesale_low,
            'wholesale_high': wholesale_high,
            'retail_low':     retail_low,
            'retail_high':    retail_high,
        })
    return bands_out


def main():
    # 入力
    with open(os.path.join(BASE, 'fish-species-map.json'), encoding='utf-8') as f:
        spc = json.load(f)
    with open(os.path.join(BASE, 'wholesale-prices.json'), encoding='utf-8') as f:
        wp = json.load(f)

    latest = wp['months'][-1]
    geppo_idx = {p['geppo_item']: p for p in latest['prices'] if p.get('geppo_item')}

    prices = {}
    missing_pfids = []
    for s in spc['species']:
        pfid = s['price_fish_id']
        if pfid in prices:
            continue
        if pfid not in PRICE_DESIGN:
            missing_pfids.append((pfid, s['site_display_name']))
            continue
        design = PRICE_DESIGN[pfid]
        geppo_item = s.get('geppo_item')

        # 月報データ
        if geppo_item and geppo_item in geppo_idx:
            g = geppo_idx[geppo_item]
            avg = g['avg_yen_per_kg']
            hi = g['high_yen_per_kg']
            lo = g['low_yen_per_kg']
            data_basis = ['geppo:' + geppo_item]
            wholesale_source = '月報最新月: ' + latest['yyyymm']
        elif 'fallback_wholesale_avg' in design:
            avg = design['fallback_wholesale_avg']
            hi  = design['fallback_wholesale_high']
            lo  = design['fallback_wholesale_low']
            data_basis = ['experience']
            wholesale_source = design.get('fallback_note', '推測値運用')
        elif 'derived_from' in design:
            # 派生型（シロアマダイ等）: base 魚種の価格×ratio
            base_pfid = design['derived_from']
            if base_pfid in prices:
                base = prices[base_pfid]
                avg = int(base['wholesale_avg'] * (design['derived_ratio_low'] + design['derived_ratio_high']) / 2)
                hi  = int(base['wholesale_high_overall'] * design['derived_ratio_high'])
                lo  = int(base['wholesale_low_overall']  * design['derived_ratio_low'])
                data_basis = ['derived:' + base_pfid]
                wholesale_source = f"派生: {base_pfid} × {design['derived_ratio_low']}〜{design['derived_ratio_high']}倍"
            else:
                continue
        else:
            continue

        bands = build_size_bands(design, avg, hi, lo)
        # 関連 species 名
        related_species = [
            x['site_display_name'] for x in spc['species'] if x['price_fish_id'] == pfid
        ]

        prices[pfid] = {
            'category_tag':            design['category'],
            'input_modes':             s.get('input_modes', []),
            'size_weight_curve':       SIZE_CURVES.get(design['curve']) if design['curve'] else None,
            'size_curve_type':         design['curve'],
            'wholesale_avg':           avg,
            'wholesale_high_overall':  hi,
            'wholesale_low_overall':   lo,
            'wholesale_source':        wholesale_source,
            'size_bands':              bands,
            'related_species':         related_species,
            'data_basis':              data_basis,
        }

    # 出力
    out = {
        'version': 'v1',
        'updated_at': date.today().isoformat(),
        'source': {
            'wholesale': latest['source_file'] + ' (' + latest['yyyymm'] + ')',
            'retail_multiplier': '業界一般値（甲案・大衆魚2.0-3.0/中級1.8-2.5/高級1.6-2.2/青物1.7-2.4/イカタコ1.8-2.6）',
            'size_premium': '大物プレミアム(small 0.95 / standard 1.00 / large 1.20 / premium 1.45)',
            'verification': 'docs/fish-value/tmp_retail_verify.md (小売物価統計 vs 月報 実倍率検証)',
        },
        'category_definitions': CATEGORIES,
        'size_class_multipliers': SIZE_CLASS_MULT,
        'prices': prices,
        'design_notes': {
            'wholesale_basis': '月報最新月単独。季節性・インフレ影響を排除するため過去16か月平均は採用しない。',
            'retail_basis': '丸ごと小売換算のみ。柵・切り身の加工済み価格は Phase 1 では出さない（歩留まり40-50%の追加加算は別観点）。',
            'fallback_strategy': '月報geppo_item=null の9魚種は経験値（fallback_wholesale_*）。月報に出現次第切替可能。',
            'shiro-amadai': 'アマダイ × 2.0-3.0 倍の派生型。月報に独立項目が出れば direct 切替。',
        },
    }

    out_path = os.path.join(BASE, 'fish-price-master.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f'生成完了: {out_path}')
    print(f'  prices: {len(prices)} pfid')
    if missing_pfids:
        print(f'  ⚠ PRICE_DESIGN 未登録: {missing_pfids}')


if __name__ == '__main__':
    main()
