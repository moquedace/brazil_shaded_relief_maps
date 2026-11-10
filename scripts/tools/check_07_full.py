# check_07_full.py -----------------------------------------------------------
# confere o 07 --mode full inteiro (183 blocos), so le os renders:
#   - cada PNG: 8192 x 8192, 16 bits, world file no lugar certo do canvas,
#     pixels em 0 ou no maximo (estouro), media e percentis
#   - todas as emendas entre blocos vizinhos com render: salto assinado na
#     linha (um bloco mais claro que o outro) descontado o gradiente medio
#     do terreno, e salto sem sinal x o salto tipico dentro dos blocos
#   - mosaico nacional a 480 m (media 16 x 16) para olhar o pais inteiro
# saida em 07_hybrid_renders/<estilo>_check/ (csv com ; e decimal ,).
# Escrito em 10/11/2026 (log 17). Uso:
#   python check_07_full.py [--workers 8]

import argparse
import csv
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import time

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
PROJ = Path(r"D:\usuario_armazenamento\cassio\projects\brazil_shaded_relief_maps")
STYLE = "h128_8_s2000_az315_el45_ang90_ctx5000_fd1"
DIR = PROJ / "data/intermediate/07_hybrid_renders" / STYLE
OUT = DIR.parent / f"{STYLE}_check"
BLOCKS = PROJ / "data/intermediate/02_prepared_dem/tables/heightmap_blocks.csv"
BP, NB, F = 8192, 18, 16          # px do nucleo, blocos por lado, fator do mosaico
STRIP = 64                        # px de cada lado da emenda para o tom medio


def num(s):
    s = str(s).strip()
    return float(s.replace(",", ".")) if "," in s else float(s)


# um bloco ------------------------------------------------------------------
def one_block(b):
    png = DIR / f"relief_{b['block_id']}.png"
    im = Image.open(png)
    size, mode = im.size, im.mode
    a16 = np.asarray(im)
    a = a16.astype(np.float32) * (255.0 / 65535.0)
    v = [float(x) for x in png.with_suffix(".pgw").read_text().split()]
    dx = v[4] - (b["core_xmin"] + 15.0)
    dy = v[5] - (b["core_ymax"] - 15.0)
    small = a.reshape(BP // F, F, BP // F, F).mean(axis=(1, 3))
    p1, p50, p99 = np.percentile(a[::4, ::4], [1, 50, 99])
    # linhas 0 e 1 da borda e, para o salto sem as 3 linhas da borda (log 17:
    # a ultima linha de baixo sai ~0,6 nivel mais clara e as de cima ~0,2
    # mais escuras em media, efeito de 1-3 px do render), as linhas 3 e 10
    edges = {
        "left0": a[:, 0].copy(), "left1": a[:, 1].copy(), "left_s": a[:, :STRIP].mean(axis=1),
        "left3": a[:, 3].copy(), "left10": a[:, 10].copy(),
        "right0": a[:, -1].copy(), "right1": a[:, -2].copy(), "right_s": a[:, -STRIP:].mean(axis=1),
        "right3": a[:, -4].copy(), "right10": a[:, -11].copy(),
        "top0": a[0, :].copy(), "top1": a[1, :].copy(), "top_s": a[:STRIP, :].mean(axis=0),
        "top3": a[3, :].copy(), "top10": a[10, :].copy(),
        "bottom0": a[-1, :].copy(), "bottom1": a[-2, :].copy(), "bottom_s": a[-STRIP:, :].mean(axis=0),
        "bottom3": a[-4, :].copy(), "bottom10": a[-11, :].copy(),
    }
    stats = {
        "block_id": b["block_id"], "largura": size[0], "altura": size[1], "modo": mode,
        "pgw_dx_m": dx, "pgw_dy_m": dy, "pgw_pixel": v[0],
        "media": float(a.mean()), "p1": float(p1), "p50": float(p50), "p99": float(p99),
        "n_zero": int((a16 == 0).sum()), "n_max": int((a16 == 65535).sum()),
    }
    return b, stats, small, edges


# emenda entre dois blocos ----------------------------------------------------
def seam(ea, eb, kind):
    # kind "lo": a a oeste, b a leste; "ns": a ao norte, b ao sul
    sa, sb = ("right", "left") if kind == "lo" else ("bottom", "top")
    a0, a1, as_, a3, a10 = (ea[f"{sa}{k}"] for k in ("0", "1", "_s", "3", "10"))
    b0, b1, bs, b3, b10 = (eb[f"{sb}{k}"] for k in ("0", "1", "_s", "3", "10"))
    step = b0 - a0                                  # atravessando a emenda
    grad = ((a0 - a1) + (b1 - b0)) / 2              # gradiente medio de 1 px dos dois lados
    typ = (np.abs(a0 - a1).mean() + np.abs(b1 - b0).mean()) / 2
    # sem as 3 linhas da borda: de a[-4] a b[3] sao 7 px; o esperado e o
    # gradiente de 7 px de dentro de cada bloco (a[-11] -> a[-4], b[3] -> b[10])
    step7 = b3 - a3
    grad7 = ((a3 - a10) + (b10 - b3)) / 2
    return {
        "excesso_sem_borda": float(step7.mean() - grad7.mean()),
        "salto_assinado": float(step.mean()),
        "gradiente_dentro": float(grad.mean()),
        "excesso_assinado": float(step.mean() - grad.mean()),
        "salto_sem_sinal": float(np.abs(step).mean()),
        "salto_tipico_dentro": float(typ),
        "razao_sem_sinal": float(np.abs(step).mean() / typ) if typ > 0 else float("nan"),
        "tom_faixa64_b_menos_a": float(bs.mean() - as_.mean()),
    }


def write_csv(path, rows):
    keys = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(keys)
        for r in rows:
            w.writerow([f"{r[k]:.3f}".replace(".", ",") if isinstance(r[k], float) else r[k] for k in keys])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    with open(BLOCKS, encoding="utf-8-sig") as f:
        blocks = list(csv.DictReader(f, delimiter=";"))
    todo = []
    for b in blocks:
        b["row"], b["col"] = int(b["row"]), int(b["col"])
        for k in ("core_xmin", "core_ymax"):
            b[k] = num(b[k])
        if str(b["has_brazil"]).upper() == "TRUE":
            todo.append(b)
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"# check 07 full {'-' * 58}\n{len(todo)} blocos em {DIR}, {args.workers} processos")

    mosaic = np.full((NB * BP // F, NB * BP // F), np.nan, dtype=np.float32)
    stats, edges = [], {}
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(one_block, b) for b in todo]
        for i, fu in enumerate(as_completed(futs), 1):
            b, st, small, ed = fu.result()
            r, c = b["row"], b["col"]
            mosaic[r * BP // F:(r + 1) * BP // F, c * BP // F:(c + 1) * BP // F] = small
            stats.append(st)
            edges[(r, c)] = ed
            if i % 20 == 0 or i == len(todo):
                el = time.time() - t0
                print(f"[{i}/{len(todo)}] {el / 60:.1f} min | falta ~{el / i * (len(todo) - i) / 60:.1f} min", flush=True)

    stats.sort(key=lambda s: s["block_id"])
    write_csv(OUT / "blocks_stats.csv", stats)

    seams = []
    for (r, c), ea in edges.items():
        for kind, (rr, cc) in (("lo", (r, c + 1)), ("ns", (r + 1, c))):
            if (rr, cc) in edges:
                s = seam(ea, edges[(rr, cc)], kind)
                seams.append({"a": f"r{r:02d}_c{c:02d}", "b": f"r{rr:02d}_c{cc:02d}", "tipo": kind, **s})
    seams.sort(key=lambda s: -abs(s["excesso_sem_borda"]))
    write_csv(OUT / "seams.csv", seams)

    # mosaico: sem render = branco
    m8 = np.where(np.isnan(mosaic), 255, np.clip(np.round(mosaic), 0, 255)).astype(np.uint8)
    Image.fromarray(m8).save(OUT / "mosaic_480m.png")
    xmin, ymax = 2744310.0, 10637160.0
    (OUT / "mosaic_480m.pgw").write_text(f"480.000000\n0\n0\n-480.000000\n{xmin + 240:.6f}\n{ymax - 240:.6f}\n",
                                         encoding="ascii")
    Image.fromarray(m8).resize((2304, 2304), Image.LANCZOS).save(OUT / "mosaic_1920m_preview.png")

    # resumo ---------------------------------------------------------------
    bad = [s for s in stats if (s["largura"], s["altura"], s["modo"]) != (BP, BP, "I;16")
           or abs(s["pgw_dx_m"]) > 0.01 or abs(s["pgw_dy_m"]) > 0.01 or s["pgw_pixel"] != 30.0]
    print(f"\nblocos: {len(stats)} | formato/world file fora do esperado: {len(bad)}")
    print(f"pixels em 0: {sum(s['n_zero'] for s in stats)} | no maximo: {sum(s['n_max'] for s in stats)}")
    ex = np.array([s["excesso_assinado"] for s in seams])
    ra = np.array([s["razao_sem_sinal"] for s in seams])
    e7 = np.array([s["excesso_sem_borda"] for s in seams])
    tp = np.array([s["tipo"] for s in seams])
    print(f"emendas: {len(seams)} | |excesso assinado| mediana {np.median(np.abs(ex)):.2f}, "
          f"p95 {np.percentile(np.abs(ex), 95):.2f}, max {np.abs(ex).max():.2f} | > 1 nivel: {(np.abs(ex) > 1).sum()}")
    print(f"sem as 3 linhas da borda: |excesso| mediana {np.median(np.abs(e7)):.2f}, "
          f"p95 {np.percentile(np.abs(e7), 95):.2f}, max {np.abs(e7).max():.2f} | > 1 nivel: {(np.abs(e7) > 1).sum()} | "
          f"media L-O {e7[tp == 'lo'].mean():+.2f}, N-S {e7[tp == 'ns'].mean():+.2f}")
    print(f"razao salto sem sinal / tipico: mediana {np.median(ra):.2f}, max {np.nanmax(ra):.2f}")
    for s in seams[:8]:
        print(f"  {s['a']} | {s['b']} ({s['tipo']}): sem borda {s['excesso_sem_borda']:+.2f}, "
              f"com borda {s['excesso_assinado']:+.2f}, "
              f"salto {s['salto_sem_sinal']:.2f} x tipico {s['salto_tipico_dentro']:.2f}, "
              f"tom 64 px b-a {s['tom_faixa64_b_menos_a']:+.2f}")
    print(f"saidas em {OUT} | {(time.time() - t0) / 60:.1f} min")


if __name__ == "__main__":
    main()
