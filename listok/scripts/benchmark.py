"""Заміри: порівняння двох моделей Gemini (Flash і Pro) за точністю, часом і ціною.

Як користуватися (Windows, з кореня проєкту):
    .venv\\Scripts\\python.exe scripts\\benchmark.py demo_photos

Назва файлу = очікувана латинська назва через дефіс, напр.:
    monstera-deliciosa.jpg, sansevieria-trifasciata.jpg, spathiphyllum-wallisii.jpg
Тоді скрипт сам порахує точність (збіг виду і збіг роду).

УВАГА: кожне фото = 1 запит на кожну модель. Безкоштовна квота невелика,
тому за замовчуванням 1 повтор. Результати: benchmark_results/results.csv і summary.md
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config  # noqa: E402
from gemini_service import _call_model, _classify, estimate_cost_usd  # noqa: E402
from images import prepare_for_gemini  # noqa: E402

EXT = (".jpg", ".jpeg", ".png", ".webp", ".heic")


def expected_from_name(fname: str) -> str:
    stem = os.path.splitext(os.path.basename(fname))[0]
    stem = stem.split("__")[0]  # monstera-deliciosa__2.jpg -> monstera-deliciosa
    parts = [p for p in stem.replace("_", "-").split("-") if p and not p.isdigit()]
    return " ".join(parts[:2]).lower()


def match(expected: str, got: str) -> tuple[bool, bool]:
    e, g = expected.lower().split(), got.lower().replace("×", "").split()
    if len(e) < 2 or not g:
        return False, False
    genus = e[0] == g[0]
    species = genus and len(g) > 1 and e[1] == g[1]
    return species, genus


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="папка з фото")
    ap.add_argument("--models", default=f"{config.GEMINI_MODEL},{config.GEMINI_PRO_MODEL}")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--pause", type=float, default=4.0, help="пауза між запитами, с (щоб не впертися в ліміт/хв)")
    args = ap.parse_args()

    if not config.GEMINI_API_KEY:
        sys.exit("Не задано GEMINI_API_KEY у .env")
    files = sorted(os.path.join(args.folder, f) for f in os.listdir(args.folder) if f.lower().endswith(EXT))
    if not files:
        sys.exit(f"У папці {args.folder} немає фото")
    models = [m.strip() for m in args.models.split(",") if m.strip()]

    out_dir = os.path.join(ROOT, "benchmark_results")
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for path in files:
        with open(path, "rb") as f:
            img, mime, _ = prepare_for_gemini(f.read())
        exp = expected_from_name(path)
        for model in models:
            for rep in range(args.repeats):
                t0 = time.monotonic()
                try:
                    res, usage = _call_model(model, img, mime, config.GEMINI_TIMEOUT_S * 2)
                    ms = int((time.monotonic() - t0) * 1000)
                    sp, ge = match(exp, res.latin_name)
                    cost = estimate_cost_usd(model, usage["input"], usage["output"] + usage["thinking"])
                    row = dict(file=os.path.basename(path), expected=exp, model=model, rep=rep + 1, ok=True,
                               latin_name=res.latin_name, common_name=res.common_name_uk, confidence=res.confidence,
                               species_match=sp, genus_match=ge, problems=len(res.problems), latency_ms=ms,
                               input_tokens=usage["input"], output_tokens=usage["output"],
                               thinking_tokens=usage["thinking"], cost_usd=cost, error="")
                except Exception as exc:  # noqa: BLE001
                    ms = int((time.monotonic() - t0) * 1000)
                    row = dict(file=os.path.basename(path), expected=exp, model=model, rep=rep + 1, ok=False,
                               latin_name="", common_name="", confidence="", species_match=False, genus_match=False,
                               problems="", latency_ms=ms, input_tokens="", output_tokens="", thinking_tokens="",
                               cost_usd="", error=f"{_classify(exc)}: {str(exc)[:120]}")
                rows.append(row)
                mark = "OK " if row["ok"] else "ERR"
                print(f"{mark} {model:24s} {row['file']:32s} {ms:6d} ms  {row['latin_name'] or row['error']}")
                time.sleep(args.pause)

    with open(os.path.join(out_dir, "results.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    lines = [f"# Порівняння моделей Gemini ({datetime.now():%d.%m.%Y %H:%M})", "",
             f"Фото: {len(files)}, повторів: {args.repeats}. Ціна — для платного рівня (на безкоштовному $0).", "",
             "| Модель | Успішних | Точність (вид) | Точність (рід) | Медіана часу, с | Сер. токенів | Ціна 1 запиту, $ | Ціна 1000 запитів, $ |",
             "|---|---|---|---|---|---|---|---|"]
    for model in models:
        ok = [r for r in rows if r["model"] == model and r["ok"]]
        allr = [r for r in rows if r["model"] == model]
        if not ok:
            lines.append(f"| `{model}` | 0/{len(allr)} | — | — | — | — | — | — |")
            continue
        with_exp = [r for r in ok if len(r["expected"].split()) >= 2]
        sp = sum(r["species_match"] for r in with_exp) / len(with_exp) * 100 if with_exp else float("nan")
        ge = sum(r["genus_match"] for r in with_exp) / len(with_exp) * 100 if with_exp else float("nan")
        med = statistics.median(r["latency_ms"] for r in ok) / 1000
        tok = statistics.mean(r["input_tokens"] + r["output_tokens"] + r["thinking_tokens"] for r in ok)
        costs = [r["cost_usd"] for r in ok if isinstance(r["cost_usd"], float)]
        c = statistics.mean(costs) if costs else None
        lines.append(f"| `{model}` | {len(ok)}/{len(allr)} | {sp:.0f}% | {ge:.0f}% | {med:.1f} | {tok:.0f} | "
                     f"{c:.5f} | {c * 1000:.2f} |" if c is not None else
                     f"| `{model}` | {len(ok)}/{len(allr)} | {sp:.0f}% | {ge:.0f}% | {med:.1f} | {tok:.0f} | — | — |")
    summary = "\n".join(lines) + "\n"
    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write(summary)
    print("\n" + summary)
    print(f"Збережено: {out_dir}")


if __name__ == "__main__":
    main()
