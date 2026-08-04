# 심사 기준 측정 도구

판정 기준을 바꿀지 정할 때 쓰는 일회성 측정 스크립트다. 골든셋을 돌려 지표를 뽑거나
변경안의 영향을 미리 재본다. **코드는 건드리지 않는다** — 가드레일 결과를 가로채거나
결과 CSV를 읽는 방식이다.

`eval/`의 정규 러너(`run_eval.py` 등)와 달리 CI·머지 게이트 대상이 아니다.

```bash
uv run python scripts/eval_tools/band_check.py       # DB 불필요
uv run python scripts/eval_tools/gate_stats.py       # DB 필요
uv run python scripts/eval_tools/simulate_c_layer.py # DB 필요
```

| 스크립트 | 무엇을 재나 |
|---|---|
| `band_check.py` | 마법사 2단계 구간표가 실제 가드레일과 맞는지. 금액대별로 화면 표기와 실제 판정을 대조한다. 자동승인 토글 on/off 둘 다 본다 |
| `gate_stats.py` | 골든셋에서 사람에게 올라간 건들이 **무엇 때문에** 올라갔는지 집계. 금액 때문에만 올라간 건도 따로 뽑는다 |
| `simulate_c_layer.py` | 자동승인 한도를 넘은 건을 AI 판단에 맡기면 어떻게 되는지. 정확도·오승인·자동 종결 비율을 현행과 비교한다 |

## 읽을 때 주의

**목 모드에서는 LLM 판정이 고정값이다.** 특히 `adjudicate`의 목 응답은 확신도를 항상
0.95로 고정하므로 "확신 없으면 사람에게" 안전장치가 작동하지 않는다. `simulate_c_layer`가
내는 오승인 건수는 **최악값**이고 실모드에서는 더 적을 수 있다.

`gate_stats.py`와 `simulate_c_layer.py`는 `eval/results/golden_run.csv`를 기준선으로
읽는다. 먼저 `uv run python eval/run_eval.py`를 한 번 돌려 최신 결과를 만들어 둘 것.

## 결과

2026-08-03 측정 결과와 결론은 `docs/internal/심사_자동화_경계_검토_2026-08-03.md`에 있다.
