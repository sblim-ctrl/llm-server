"""golden_v2_report.md용 유형별 정확도 막대차트 2장 생성 — 목 모드 실측값만 사용
(실모드는 이 세션에서 API 키 접근 불가로 미실행 — 보고서 §실행 현황 참조).

색·스타일은 eval/analysis_realmode.ipynb의 기존 관례(검증 팔레트·값 라벨·이중 축 금지)를
그대로 따른다 — 새 팔레트를 만들지 않는다.
"""

import platform
import warnings
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")
_korean_font = {"Darwin": "AppleGothic", "Windows": "Malgun Gothic"}.get(
    platform.system(), "NanumGothic"
)
mpl.rc("font", family=_korean_font)
mpl.rc("axes", unicode_minus=False)

S1, S2 = "#2a78d6", "#eb6834"
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#1a1a19", "#6b6b68", "#e6e6e3"
mpl.rc("figure", facecolor=SURFACE)
mpl.rc("axes", facecolor=SURFACE)

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "eval" / "results"


def style(ax, title=None, ylabel=None):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=MUTED, length=0, labelsize=9)
    ax.yaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    if title:
        ax.set_title(title, color=INK, fontsize=12, pad=12, loc="left", fontweight="bold")
    ax.set_ylabel(ylabel or "", color=MUTED, fontsize=9)


def label_bars(ax, fmt="{:.0%}"):
    for p in ax.patches:
        ax.annotate(
            fmt.format(p.get_height()),
            (p.get_x() + p.get_width() / 2, p.get_height()),
            textcoords="offset points",
            xytext=(0, 4),
            ha="center",
            fontsize=9,
            color=INK,
            fontweight="bold",
        )


# 목 모드 실측(eval/run_eval_v2.py 실행 결과, 2026-09-08) — 리포트 본문 표와 동일 수치
VERDICT_ACC = {
    "clear_approve": 1.00,
    "clear_reject": 1.00,
    "boundary": 1.00,
    "missing_info": 1.00,
    "receipt_mismatch": 1.00,
    "notation_variant": 1.00,
    "rule_conflict": 0.69,
    "circumvention": 0.00,
}
CATEGORY_ACC = {
    "clear_approve": 1.00,
    "clear_reject": 1.00,
    "boundary": 1.00,
    "missing_info": 1.00,
    "receipt_mismatch": 1.00,
    "notation_variant": 0.10,
    "rule_conflict": 1.00,
    "circumvention": 1.00,
}
REAL_MODE_REQUIRED = {"rule_conflict", "circumvention"}


def _bar(ax, data: dict, title: str):
    labels = list(data.keys())
    values = list(data.values())
    colors = [S2 if k in REAL_MODE_REQUIRED else S1 for k in labels]
    ax.bar(labels, values, color=colors, width=0.6)
    style(ax, title, "정확도")
    ax.set_ylim(0, 1.12)
    label_bars(ax)
    ax.tick_params(axis="x", rotation=30, labelsize=8.5)


def main() -> None:
    fig, ax = plt.subplots(figsize=(9, 4.2))
    _bar(ax, VERDICT_ACC, "유형별 판정 정확도 (목 모드) — 주황=실모드 전용 축")
    plt.tight_layout()
    fig.savefig(OUT_DIR / "golden_v2_verdict_accuracy_mock.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 4.2))
    _bar(ax, CATEGORY_ACC, "유형별 분류 정확도 (목 모드) — 주황=실모드 전용 축")
    plt.tight_layout()
    fig.savefig(OUT_DIR / "golden_v2_category_accuracy_mock.png", dpi=150)
    plt.close(fig)

    print("생성 완료:")
    print(f"  {OUT_DIR / 'golden_v2_verdict_accuracy_mock.png'}")
    print(f"  {OUT_DIR / 'golden_v2_category_accuracy_mock.png'}")


if __name__ == "__main__":
    main()
