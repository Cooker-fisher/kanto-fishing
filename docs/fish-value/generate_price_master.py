"""
fish-price-master.json 生成スクリプト

- 月報最新月（wholesale-prices.json の months[-1]）のみを採用
- 業界一般値カテゴリ × 大物プレミアム倍率 で size_bands を構築
- size_weight_curve は cm 入力魚種のみ・体型別の経験値カーブを採用
- seasonal ブロック: 蓄積全月報から暦月別の季節指数を算出（app.js が
  「データ月→利用月」のラグ補正に使用。水準は最新月のまま・平均化はしない）

実行: python docs/fish-value/generate_price_master.py
出力: docs/fish-value/fish-price-master.json
"""

import json
import os
import statistics
from collections import defaultdict
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
    "中型魚型": [  # マダイ・スズキ系・イシダイ・メダイ・シマアジ
        {"cm": 20, "kg": 0.15},
        {"cm": 30, "kg": 0.50},
        {"cm": 40, "kg": 1.20},
        {"cm": 50, "kg": 2.30},
        {"cm": 60, "kg": 3.80},
        {"cm": 70, "kg": 5.50},
        {"cm": 80, "kg": 7.50},
    ],
    "青物大型型": [  # ブリ系・カンパチ・ヒラマサ・サワラ・シーバス・シイラ・カツオ
        {"cm": 30, "kg": 0.40},
        {"cm": 40, "kg": 0.80},
        {"cm": 50, "kg": 1.50},
        {"cm": 60, "kg": 2.80},
        {"cm": 70, "kg": 4.50},
        {"cm": 80, "kg": 6.50},
        {"cm": 90, "kg": 9.00},
        {"cm": 100, "kg": 12.0},
        {"cm": 120, "kg": 18.0},
    ],
    "マグロ型": [  # キハダ・キメジ
        {"cm": 40, "kg": 0.80},
        {"cm": 60, "kg": 3.00},
        {"cm": 80, "kg": 8.00},
        {"cm": 100, "kg": 18.0},
        {"cm": 120, "kg": 35.0},
        {"cm": 150, "kg": 70.0},
    ],
    "深海魚型": [  # キンメ・クロムツ・アカムツ・メヌケ
        {"cm": 20, "kg": 0.15},
        {"cm": 30, "kg": 0.50},
        {"cm": 40, "kg": 1.20},
        {"cm": 50, "kg": 2.20},
        {"cm": 60, "kg": 3.50},
    ],
    "アマダイ型": [
        {"cm": 20, "kg": 0.12},
        {"cm": 30, "kg": 0.40},
        {"cm": 40, "kg": 0.90},
        {"cm": 50, "kg": 1.60},
        {"cm": 60, "kg": 2.80},
    ],
    "ハタ型": [  # ハタ・マハタ・アラ
        {"cm": 30, "kg": 0.50},
        {"cm": 40, "kg": 1.20},
        {"cm": 50, "kg": 2.50},
        {"cm": 60, "kg": 4.50},
        {"cm": 70, "kg": 7.00},
        {"cm": 80, "kg": 10.0},
    ],
    "アンコウ型": [
        {"cm": 30, "kg": 0.80},
        {"cm": 40, "kg": 1.50},
        {"cm": 60, "kg": 4.00},
        {"cm": 80, "kg": 8.00},
        {"cm": 100, "kg": 14.0},
    ],
    "フグ型": [  # トラフグ・他フグ
        {"cm": 20, "kg": 0.20},
        {"cm": 30, "kg": 0.50},
        {"cm": 40, "kg": 1.20},
        {"cm": 50, "kg": 2.50},
        {"cm": 60, "kg": 4.00},
    ],
    "タコ型": [  # マダコ・全長(腕長)基準
        {"cm": 30, "kg": 0.80},
        {"cm": 50, "kg": 2.00},
        {"cm": 70, "kg": 4.50},
        {"cm": 90, "kg": 8.00},
        {"cm": 120, "kg": 15.0},
    ],
    "イカ型_大": [  # アオリイカ・胴長基準
        {"cm": 10, "kg": 0.15},
        {"cm": 15, "kg": 0.30},
        {"cm": 20, "kg": 0.60},
        {"cm": 25, "kg": 1.00},
        {"cm": 30, "kg": 1.50},
        {"cm": 35, "kg": 2.50},
    ],
    "イカ型_中": [  # スルメイカ・ヤリイカ・モンゴウイカ・コウイカ系胴長
        {"cm": 10, "kg": 0.08},
        {"cm": 15, "kg": 0.20},
        {"cm": 20, "kg": 0.40},
        {"cm": 25, "kg": 0.65},
        {"cm": 30, "kg": 1.00},
        {"cm": 35, "kg": 1.50},
    ],
    "イカ型_小": [  # ムギイカ・マルイカ・スジイカ
        {"cm": 8,  "kg": 0.05},
        {"cm": 12, "kg": 0.12},
        {"cm": 15, "kg": 0.20},
        {"cm": 20, "kg": 0.40},
        {"cm": 25, "kg": 0.65},
    ],
    "大物型": [  # アブラボウズ・超大型魚
        {"cm": 40, "kg": 1.5},
        {"cm": 60, "kg": 5.0},
        {"cm": 80, "kg": 12.0},
        {"cm": 100, "kg": 22.0},
        {"cm": 120, "kg": 35.0},
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
    "premium":  1.25,  # 卸値が既に最高値を反映しているため大物プレミアムの二重計上を緩和（旧1.45・2026-07-21）
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
        # 日報検証 2026/05/28: 月報avg=2,678の全銘柄平均では釣果対象の天然キスを過小評価。日報下限864/上限8,424
        "override_wholesale_low":  850,
        "override_wholesale_high": 6500,
        "override_note": "verify_daily:2026-05-28 / 江戸前天然キスの実勢に合わせて low 583→850, high 4,655→6,500 へ調整",
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
        "category": "大衆魚", "curve": "青物大型型",
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
        "category": "中級魚", "curve": "中型魚型",
        "bands": [
            {"kg_max": 0.5, "label": "小ダイ",   "size_class": "small"},
            {"kg_max": 1.5, "label": "標準",     "size_class": "standard"},
            {"kg_max": 3.0, "label": "大ダイ",   "size_class": "large"},
            {"kg_max": 999, "label": "特大",     "size_class": "premium"},
        ],
        # 日報検証 2026/05/28: 月報high=2,183に対し日報で5,400/kg観測。特大プレミアム帯を実勢に上方修正
        "override_wholesale_high": 4500,
        "override_note": "verify_daily:2026-05-28 / 日報で5,400/kg観測のため high を 2,183→4,500 へ調整",
    },
    "kurodai": {
        "category": "中級魚", "curve": "中型魚型",
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
        "category": "中級魚", "curve": "平体型",
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
        # 日報検証 2026/05/28: 月報low=323は地方産含む全国平均。関東釣果は日報下限540で取引
        "override_wholesale_low": 500,
        "override_note": "verify_daily:2026-05-28 / 関東釣果メバルの実勢に合わせて low 323→500 へ調整",
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
        "category": "中級魚", "curve": "平体型",
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
        "category": "中級魚", "curve": "中型魚型",
        "bands": [
            {"kg_max": 0.5, "label": "サンバソウ","size_class": "small"},
            {"kg_max": 1.5, "label": "標準",     "size_class": "standard"},
            {"kg_max": 999, "label": "大型",     "size_class": "large"},
        ],
    },
    "medai": {
        "category": "中級魚", "curve": "中型魚型",
        "bands": [
            {"kg_max": 1.0, "label": "小",       "size_class": "small"},
            {"kg_max": 3.0, "label": "標準",     "size_class": "standard"},
            {"kg_max": 999, "label": "大型",     "size_class": "large"},
        ],
    },

    # ───── 青物 ─────
    "katsuo": {
        "category": "青物", "curve": "青物大型型",
        "bands": [
            {"kg_max": 2.0, "label": "ヒラソウダ級","size_class": "small"},
            {"kg_max": 4.0, "label": "標準",       "size_class": "standard"},
            {"kg_max": 999, "label": "戻りガツオ", "size_class": "large"},
        ],
    },
    "buri": {
        "category": "青物", "curve": "青物大型型",
        "bands": [
            {"kg_max": 5.0, "label": "標準",     "size_class": "standard"},
            {"kg_max": 999, "label": "寒ブリ大物","size_class": "premium"},
        ],
    },
    "warasa": {
        "category": "青物", "curve": "青物大型型",
        "bands": [
            {"kg_max": 3.0, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大ワラサ","size_class": "large"},
        ],
    },
    "inada": {
        "category": "青物", "curve": "青物大型型",
        "bands": [
            {"kg_max": 1.5, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "良型",   "size_class": "large"},
        ],
    },
    "kanpachi": {
        "category": "青物", "curve": "青物大型型",
        "bands": [
            {"kg_max": 2.0, "label": "小カンパチ","size_class": "small"},
            {"kg_max": 5.0, "label": "標準",     "size_class": "standard"},
            {"kg_max": 999, "label": "大型",     "size_class": "large"},
        ],
    },
    "hiramasa": {
        "category": "青物", "curve": "青物大型型",
        "bands": [
            {"kg_max": 3.0, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大型",   "size_class": "large"},
        ],
    },
    "sawara": {
        "category": "青物", "curve": "青物大型型",
        "bands": [
            {"kg_max": 1.5, "label": "サゴシ", "size_class": "small"},
            {"kg_max": 4.0, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大サワラ","size_class": "large"},
        ],
    },
    "kihada": {
        "category": "青物", "curve": "マグロ型",
        "bands": [
            {"kg_max": 10,  "label": "小",     "size_class": "small"},
            {"kg_max": 30,  "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大型",   "size_class": "large"},
        ],
    },
    "kimeji": {
        "category": "青物", "curve": "マグロ型",
        "bands": [
            {"kg_max": 5,   "label": "小",     "size_class": "small"},
            {"kg_max": 999, "label": "標準",   "size_class": "standard"},
        ],
    },
    "shimaaji": {
        "category": "青物", "curve": "中型魚型",
        "bands": [
            {"kg_max": 1.0, "label": "小型",   "size_class": "small"},
            {"kg_max": 3.0, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大シマアジ","size_class": "premium"},
        ],
    },
    "mahata": {
        "category": "青物", "curve": "ハタ型",
        "bands": [
            {"kg_max": 2.0, "label": "小",     "size_class": "small"},
            {"kg_max": 5.0, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大ハタ", "size_class": "premium"},
        ],
    },
    "hata": {
        "category": "青物", "curve": "ハタ型",
        "bands": [
            {"kg_max": 2.0, "label": "小",     "size_class": "small"},
            {"kg_max": 5.0, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大ハタ", "size_class": "premium"},
        ],
    },
    "seabass": {
        "category": "青物", "curve": "青物大型型",
        "bands": [
            {"kg_max": 1.0, "label": "セイゴ", "size_class": "small"},
            {"kg_max": 3.0, "label": "フッコ", "size_class": "standard"},
            {"kg_max": 999, "label": "スズキ", "size_class": "large"},
        ],
    },
    "shiira": {
        "category": "青物", "curve": "青物大型型",
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
        "category": "高級魚", "curve": "アマダイ型",
        "bands": [
            {"kg_max": 0.4, "label": "小型",   "size_class": "small"},
            {"kg_max": 1.0, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大アマダイ","size_class": "premium"},
        ],
    },
    "shiro-amadai": {
        "category": "高級魚", "curve": "アマダイ型",
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
        "category": "高級魚", "curve": "深海魚型",
        "bands": [
            {"kg_max": 0.5, "label": "小",     "size_class": "small"},
            {"kg_max": 1.5, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大金目", "size_class": "premium"},
        ],
    },
    "kuromutsu": {
        "category": "高級魚", "curve": "深海魚型",
        "bands": [
            {"kg_max": 0.5, "label": "小",     "size_class": "small"},
            {"kg_max": 1.5, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大ムツ", "size_class": "premium"},
        ],
    },
    "akamutsu": {
        "category": "高級魚", "curve": "深海魚型",
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
        "category": "高級魚", "curve": "大物型",
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
        "category": "高級魚", "curve": "ハタ型",
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
        "category": "高級魚", "curve": "深海魚型",
        "bands": [
            {"kg_max": 1.0, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "良型",   "size_class": "large"},
        ],
    },
    "torafugu": {
        "category": "高級魚", "curve": "フグ型",
        "bands": [
            {"kg_max": 1.0, "label": "小",     "size_class": "small"},
            {"kg_max": 2.5, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大型",   "size_class": "premium"},
        ],
    },
    "akamefugu": {
        "category": "高級魚", "curve": "フグ型",
        "bands": [
            {"kg_max": 0.5, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "良型",   "size_class": "large"},
        ],
    },
    "fugu": {
        "category": "高級魚", "curve": "フグ型",
        "bands": [
            {"kg_max": 0.5, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "良型",   "size_class": "large"},
        ],
    },
    "shousaifugu": {
        "category": "高級魚", "curve": "フグ型",
        "bands": [
            {"kg_max": 0.5, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "良型",   "size_class": "large"},
        ],
    },

    # ───── イカタコ ─────
    "surumeika": {
        "category": "イカタコ", "curve": "イカ型_中",
        "bands": [
            {"kg_max": 0.2, "label": "小",     "size_class": "small"},
            {"kg_max": 0.5, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大型",   "size_class": "large"},
        ],
    },
    "mugiika": {
        "category": "イカタコ", "curve": "イカ型_小",
        "bands": [
            {"kg_max": 0.10, "label": "小",   "size_class": "small"},
            {"kg_max": 999,  "label": "標準", "size_class": "standard"},
        ],
    },
    "sujiika": {
        "category": "イカタコ", "curve": "イカ型_小",
        "bands": [
            {"kg_max": 0.20, "label": "小",   "size_class": "small"},
            {"kg_max": 999,  "label": "標準", "size_class": "standard"},
        ],
    },
    "yariika": {
        "category": "イカタコ", "curve": "イカ型_中",
        "bands": [
            {"kg_max": 0.20, "label": "小",   "size_class": "small"},
            {"kg_max": 0.50, "label": "標準", "size_class": "standard"},
            {"kg_max": 999,  "label": "大",   "size_class": "large"},
        ],
    },
    "aoriika": {
        "category": "イカタコ", "curve": "イカ型_大",
        "bands": [
            {"kg_max": 0.5, "label": "小",     "size_class": "small"},
            {"kg_max": 1.5, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "キロアップ","size_class": "premium"},
        ],
    },
    "maruika": {
        "category": "イカタコ", "curve": "イカ型_小",
        "bands": [
            {"kg_max": 0.20, "label": "小",   "size_class": "small"},
            {"kg_max": 999,  "label": "標準", "size_class": "standard"},
        ],
    },
    "sumiika": {
        "category": "イカタコ", "curve": "イカ型_中",
        "bands": [
            {"kg_max": 0.5, "label": "小",     "size_class": "small"},
            {"kg_max": 1.5, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大型",   "size_class": "large"},
        ],
    },
    "mongoika": {
        "category": "イカタコ", "curve": "イカ型_中",
        "bands": [
            {"kg_max": 1.0, "label": "小",     "size_class": "small"},
            {"kg_max": 3.0, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大型",   "size_class": "large"},
        ],
    },
    "madako": {
        "category": "イカタコ", "curve": "タコ型",
        "bands": [
            {"kg_max": 1.0, "label": "小",     "size_class": "small"},
            {"kg_max": 3.0, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大ダコ", "size_class": "premium"},
        ],
    },

    # ───── 専用処理（アンコウ・その他） ─────
    "ankou": {
        "category": "高級魚", "curve": "アンコウ型",
        "bands": [
            {"kg_max": 3,   "label": "小",     "size_class": "small"},
            {"kg_max": 8,   "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大物",   "size_class": "large"},
        ],
    },

    # ───── おかっぱり追加（2026-07-05・豊洲に卸値あり） ─────
    "ainame": {
        "category": "中級魚", "curve": "標準型",
        "bands": [
            {"kg_max": 0.3, "label": "小",     "size_class": "small"},
            {"kg_max": 0.7, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大型",   "size_class": "large"},
        ],
    },
    "sayori": {
        "category": "中級魚", "curve": "超細長型",
        "bands": [
            {"kg_max": 0.05, "label": "エンピツ", "size_class": "small"},
            {"kg_max": 0.09, "label": "標準",     "size_class": "standard"},
            {"kg_max": 999,  "label": "カンヌキ", "size_class": "large"},
        ],
    },
    "takabe": {
        "category": "中級魚", "curve": "標準型",
        "bands": [
            {"kg_max": 0.1, "label": "小",     "size_class": "small"},
            {"kg_max": 999, "label": "良型",   "size_class": "standard"},
        ],
        # 月報 low=132 は外れ値（小口の投げ売り）。磯の高級小魚の実勢に合わせ床上げ
        "override_wholesale_low": 1200,
        "override_note": "月報low外れ値(132)対策・タカベ実勢に床上げ",
    },
    "kijihata": {
        "category": "高級魚", "curve": "ハタ型",
        "bands": [
            {"kg_max": 0.4, "label": "小",     "size_class": "small"},
            {"kg_max": 1.0, "label": "標準",   "size_class": "standard"},
            {"kg_max": 999, "label": "大型",   "size_class": "large"},
        ],
    },
    "megochi": {
        "category": "中級魚", "curve": "細長型",
        "bands": [
            {"kg_max": 0.03, "label": "小",     "size_class": "small"},
            {"kg_max": 999,  "label": "標準",   "size_class": "standard"},
        ],
        # 月報 low=142 は外れ値。天ぷらネタで高単価な実勢に床上げ
        "override_wholesale_low": 1200,
        "override_note": "月報low外れ値(142)対策・メゴチ実勢に床上げ",
    },
    "hokke": {
        "category": "大衆魚", "curve": "標準型",
        "bands": [
            {"kg_max": 0.4, "label": "小",       "size_class": "small"},
            {"kg_max": 999, "label": "真ホッケ", "size_class": "standard"},
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


# ---- 季節指数（暦月別・ラグ補正用） --------------------------------
# 蓄積した全月報から「魚種ごとの暦月別 相場指数」を作る。
# 用途: 価格水準は月報最新月のまま、app.js が idx[利用月]/idx[データ月] を
#       掛けて公開ラグ（約1.5〜2か月）の季節ズレだけを補正する。
# 統計設計:
#  ① 年レベル補正: 両年に存在する暦月の価格比中央値で 2025年分を 2026年水準へ
#     スケール（タチウオ等の年間インフレ/資源変動が指数を汚染するのを防ぐ）
#  ② 暦月別平均 → 魚種の年間中央値で正規化 → 円環3か月中央値平滑
#  ③ 12暦月すべて埋まらない魚種は除外（カテゴリ指数へフォールバック）
# 検証: 2026-07-05 ドメイン照合済み（寒ブリ1月2.05/6月0.80・カツオ冬1.58・
#       タチウオ夏1.34・アジ平坦0.91-1.14）
SEASONAL_MIN_MONTHS = 12


def _species_month_index(mp: dict) -> list | None:
    """{yyyymm: avg円/kg} → 暦月12指数（1月始まり）。データ不足なら None"""
    if len(mp) < SEASONAL_MIN_MONTHS:
        return None
    years = sorted({ym[:4] for ym in mp})
    by_year = {y: {ym[4:]: v for ym, v in mp.items() if ym.startswith(y)} for y in years}
    latest_year = years[-1]
    # ① 年レベル補正（最新年水準へ）
    adj = defaultdict(list)
    for y in years:
        if y == latest_year:
            lvl = 1.0
        else:
            common = [cm for cm in by_year[y] if cm in by_year[latest_year]]
            lvl = statistics.median(
                [by_year[latest_year][cm] / by_year[y][cm] for cm in common]
            ) if common else 1.0
        for cm, v in by_year[y].items():
            adj[cm].append(v * lvl)
    if len(adj) < 12:
        return None
    # ② 暦月平均 → 正規化
    monthly = {cm: statistics.mean(vs) for cm, vs in adj.items()}
    base = statistics.median(monthly.values())
    raw = [monthly[f'{i:02d}'] / base for i in range(1, 13)]
    # 円環3か月中央値平滑
    return [round(statistics.median([raw[(i - 1) % 12], raw[i], raw[(i + 1) % 12]]), 3)
            for i in range(12)]


def compute_seasonal(wp: dict, spc: dict, prices: dict) -> dict:
    """wholesale-prices.json 全月 → seasonal ブロック"""
    pfid_geppo = {}
    for s in spc['species']:
        if s.get('geppo_item') and s['price_fish_id'] not in pfid_geppo:
            pfid_geppo[s['price_fish_id']] = s['geppo_item']

    series = defaultdict(dict)  # pfid -> {yyyymm: avg}
    for m in wp['months']:
        idx = {p['geppo_item']: p for p in m['prices'] if p.get('geppo_item')}
        for pfid, gi in pfid_geppo.items():
            g = idx.get(gi)
            if g and g.get('avg_yen_per_kg'):
                series[pfid][m['yyyymm']] = g['avg_yen_per_kg']

    by_pfid = {}
    for pfid, mp in series.items():
        r = _species_month_index(mp)
        if r:
            by_pfid[pfid] = r

    # カテゴリ指数 = メンバー魚種指数の暦月別中央値（geppo 非連動魚種のフォールバック）
    cat_members = defaultdict(list)
    for pfid, arr in by_pfid.items():
        cat = prices.get(pfid, {}).get('category_tag')
        if cat:
            cat_members[cat].append(arr)
    by_category = {
        cat: [round(statistics.median([a[i] for a in arrs]), 3) for i in range(12)]
        for cat, arrs in cat_members.items()
    }

    return {
        'data_month': wp['months'][-1]['yyyymm'],
        'months_used': len(wp['months']),
        'method': ('魚種別 暦月指数（年レベル補正＋円環3か月中央値平滑・12暦月完備魚種のみ）。'
                   '非連動魚種は by_category へフォールバック。'
                   'app.js が idx[利用月]/idx[データ月] を 0.5〜2.0 でクランプして適用'),
        'by_pfid': by_pfid,
        'by_category': by_category,
    }


# ---- 日報補正（当月の実勢レベル・ハイブリッド） --------------------
# crawl_daily.py が出力する daily-prices.json（日報中値 median）を読み、
# df = clamp(日報中値 median / 月報最新月 avg, 0.5, 2.0) を魚種別に算出。
# 中値が十分に取れる魚のみ（相対取引で高安しか出ない魚は季節補正へフォールバック）。
# 中値だけを使う理由: 月報 high/low は月内の外れ値で日報 median と粒度が合わず比が割れるため
# （crawl_daily.py の docstring 参照・実測較正 2026-07-05）。
# 日報の窓は当月を直接反映するので、この係数は季節補正を「置換」する（app.js 側 effectiveFactor）。
DAILY_PRICES = 'daily-prices.json'
DAILY_MIN_MID_OBS = 8   # 中値観測がこれ未満の魚は補正しない（median 安定性）
DAILY_MIN_DAYS = 5      # 単日スパイク防止
DAILY_CLAMP = (0.5, 2.0)


def compute_daily_correction(wp: dict, spc: dict) -> dict | None:
    """daily-prices.json → daily_correction ブロック（無ければ None）"""
    path = os.path.join(BASE, DAILY_PRICES)
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        daily = json.load(f)

    pfid_geppo = {}
    for s in spc['species']:
        if s.get('geppo_item') and s['price_fish_id'] not in pfid_geppo:
            pfid_geppo[s['price_fish_id']] = s['geppo_item']
    gidx = {p['geppo_item']: p for p in wp['months'][-1]['prices'] if p.get('geppo_item')}

    lo, hi = DAILY_CLAMP
    by_pfid = {}
    for pfid, d in daily.get('by_pfid', {}).items():
        if d['n_mid'] < DAILY_MIN_MID_OBS or d['n_days'] < DAILY_MIN_DAYS:
            continue
        g = gidx.get(pfid_geppo.get(pfid, ''))
        if not g or not g.get('avg_yen_per_kg'):
            continue
        m_avg = g['avg_yen_per_kg']
        raw = d['mid_median_yen_per_kg'] / m_avg
        by_pfid[pfid] = {
            'factor': round(max(lo, min(hi, raw)), 3),
            'raw_ratio': round(raw, 3),
            'n_mid': d['n_mid'],
            'n_days': d['n_days'],
            'daily_mid': d['mid_median_yen_per_kg'],
            'monthly_avg': m_avg,
        }

    return {
        'asof': daily.get('asof'),
        'window_business_days': daily.get('window_business_days'),
        'data_month': wp['months'][-1]['yyyymm'],
        'min_mid_obs': DAILY_MIN_MID_OBS,
        'clamp': list(DAILY_CLAMP),
        'method': ('df = clamp(日報中値 median / 月報avg, 0.5, 2.0)。中値≥{}観測の魚のみ。'
                   '当月実勢を直接測るため季節補正を置換（app.js effectiveFactor）。'
                   '中値の取れない魚（相対取引）は季節補正へフォールバック').format(DAILY_MIN_MID_OBS),
        'by_pfid': dict(sorted(by_pfid.items())),
    }


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
            # 日報検証ベースの override（PRICE_DESIGN に override_wholesale_* がある場合）
            if 'override_wholesale_low' in design:
                lo = design['override_wholesale_low']
                data_basis.append('verify_daily:2026-05-28')
            if 'override_wholesale_high' in design:
                hi = design['override_wholesale_high']
                if 'verify_daily:2026-05-28' not in data_basis:
                    data_basis.append('verify_daily:2026-05-28')
            if 'override_wholesale_avg' in design:
                avg = design['override_wholesale_avg']
                if 'verify_daily:2026-05-28' not in data_basis:
                    data_basis.append('verify_daily:2026-05-28')
            if 'override_note' in design:
                wholesale_source += ' / ' + design['override_note']
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
        'seasonal': compute_seasonal(wp, spc, prices),
        'daily_correction': compute_daily_correction(wp, spc),
        'design_notes': {
            'wholesale_basis': ('月報最新月単独（過去平均は採用しない）。'
                                '公開ラグ約1.5〜2か月の季節ズレは seasonal ブロックの暦月指数で'
                                'app.js がデータ月→利用月に補正する（水準は最新月のまま）。'),
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
