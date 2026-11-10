# check_07_test.py -----------------------------------------------------------
# confere o 07 --mode test: convergencia do contexto (anel de 250, 600 e
# 1200 km), largura da margem de 30 m (1024 x 2048 px), ref de 30 m com
# 245 km de margem e o mesmo render da rodada 2 (hybrid30_gray), e as
# emendas (dois blocos lado a lado x um render unico das duas areas).
# Saida: tabelas em ;/, e folhas png em 07_hybrid_renders/test_check.
# Unidade das diferencas: niveis de 8 bits (0-255) no png ja com a curva
# de exibicao do Blender.

import csv
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image

PROJ = Path(r"D:\usuario_armazenamento\cassio\projects\brazil_shaded_relief_maps")
TEST = PROJ / "data/intermediate/07_hybrid_renders/test"
OUT = PROJ / "data/intermediate/07_hybrid_renders/test_check"
# pasta da rodada 2 (referencia local, fora do repositorio): variavel de
# ambiente BRAZIL_ROUND2_DIR com as subpastas work/round2 e outputs/round2
ROUND2 = Path(os.environ["BRAZIL_ROUND2_DIR"]) / "work" / "round2"
SITES = ["mantiqueira", "amazonia", "aparados", "acre"]
ROUND2_SITES = ["mantiqueira", "amazonia", "aparados"]


# leitura -------------------------------------------------------------------
def read16(path):
    a = np.asarray(Image.open(path), dtype=np.float64)
    return a / 65535.0 * 255.0


def read_pgw(path):
    v = [float(x) for x in Path(path).read_text().split()]
    return v[4] - v[0] / 2, v[5] - v[3] / 2  # canto superior esquerdo


def stats(a, b, label, site):
    d = a - b
    ad = np.abs(d)
    return {
        "site": site, "comparacao": label,
        "vies": d.mean(), "mae": ad.mean(),
        "p99": np.percentile(ad, 99), "max": ad.max(),
        "pct_gt2": 100 * (ad > 2).mean(), "pct_gt8": 100 * (ad > 8).mean(),
        "media_a": a.mean(), "media_b": b.mean(),
    }


def to8(a):
    return np.clip(np.round(a), 0, 255).astype(np.uint8)


def diff_img(d, scale=8.0):
    # cinza 128 = igual; claro = a mais claro; escuro = a mais escuro
    return to8(128 + d * scale)


# convergencia por janela ---------------------------------------------------
rows = []
OUT.mkdir(parents=True, exist_ok=True)
for s in SITES:
    r = {k: read16(TEST / f"{s}_{k}.png") for k in
         ["ref_m8192", "m1024_c250", "m1024_c600", "m1024_c1200", "m2048_c600"]}
    rows.append(stats(r["m1024_c250"], r["m1024_c1200"], "c250 - c1200", s))
    rows.append(stats(r["m1024_c600"], r["m1024_c1200"], "c600 - c1200", s))
    rows.append(stats(r["m2048_c600"], r["m1024_c600"], "m2048 - m1024 (c600)", s))
    rows.append(stats(r["m1024_c600"], r["ref_m8192"], "c600 - ref", s))
    rows.append(stats(r["m1024_c1200"], r["ref_m8192"], "c1200 - ref", s))
    # teste extra do anel ate a borda do canvas (07 --mode test --context-km 5000)
    if (TEST / f"{s}_m1024_c5000.png").exists():
        r["m1024_c5000"] = read16(TEST / f"{s}_m1024_c5000.png")
        r["m2048_c5000"] = read16(TEST / f"{s}_m2048_c5000.png")
        rows.append(stats(r["m1024_c1200"], r["m1024_c5000"], "c1200 - c5000", s))
        rows.append(stats(r["m1024_c600"], r["m1024_c5000"], "c600 - c5000", s))
        rows.append(stats(r["m2048_c5000"], r["m1024_c5000"], "m2048 - m1024 (c5000)", s))
        rows.append(stats(r["m1024_c5000"], r["ref_m8192"], "c5000 - ref", s))
    if s in ROUND2_SITES:
        r2 = read16(ROUND2 / f"{s}_hybrid30_gray.png")
        rows.append(stats(r["ref_m8192"], r2, "ref - rodada2", s))
        rows.append(stats(r["m1024_c600"], r2, "c600 - rodada2", s))
    # folha: ref | c250 | c600 | c1200 / dif x8 c250-c1200 | c600-c1200 | c1200-ref | m2048-m1024
    top = np.hstack([to8(r[k]) for k in ["ref_m8192", "m1024_c250", "m1024_c600", "m1024_c1200"]])
    bot = np.hstack([
        diff_img(r["m1024_c250"] - r["m1024_c1200"]),
        diff_img(r["m1024_c600"] - r["m1024_c1200"]),
        diff_img(r["m1024_c1200"] - r["ref_m8192"]),
        diff_img(r["m2048_c600"] - r["m1024_c600"]),
    ])
    sheet = np.vstack([top, bot])
    Image.fromarray(sheet).resize((sheet.shape[1] // 2, sheet.shape[0] // 2),
                                  Image.LANCZOS).save(OUT / f"context_{s}.png")


# emendas -------------------------------------------------------------------
seam_rows = []
seam_cases = [(n, ax, c) for c in ["c600", "c5000"] for n, ax in [("seam_ew", 1), ("seam_ns", 0)]
              if (TEST / f"{n}_joint_m1024_{c}.png").exists()]
for name, axis, ctx in seam_cases:
    a = read16(TEST / f"{name}_a_m1024_{ctx}.png")
    b = read16(TEST / f"{name}_b_m1024_{ctx}.png")
    j = read16(TEST / f"{name}_joint_m1024_{ctx}.png")
    xa, ya = read_pgw(TEST / f"{name}_a_m1024_{ctx}.pgw")
    xb, yb = read_pgw(TEST / f"{name}_b_m1024_{ctx}.pgw")
    xj, yj = read_pgw(TEST / f"{name}_joint_m1024_{ctx}.pgw")
    # posicao de a e b dentro do joint pelos world files
    oa = (int(round((yj - ya) / 30)), int(round((xa - xj) / 30)))
    ob = (int(round((yj - yb) / 30)), int(round((xb - xj) / 30)))
    mos = np.full_like(j, np.nan)
    mos[oa[0]:oa[0] + a.shape[0], oa[1]:oa[1] + a.shape[1]] = a
    mos[ob[0]:ob[0] + b.shape[0], ob[1]:ob[1] + b.shape[1]] = b
    assert not np.isnan(mos).any(), f"{name}: a e b nao cobrem o joint"
    seam = a.shape[axis]  # indice da 1a linha/coluna de b
    seam_rows.append(stats(mos, j, "mosaico - junto (tudo)", f"{name}_{ctx}"))
    # faixa de 64 px de cada lado da emenda
    sl = [slice(None), slice(None)]
    sl[axis] = slice(seam - 64, seam + 64)
    seam_rows.append(stats(mos[tuple(sl)], j[tuple(sl)], "mosaico - junto (128 px na emenda)", f"{name}_{ctx}"))
    # salto na emenda: |px antes - px depois| no mosaico e no junto,
    # comparado ao salto entre vizinhos tipico longe da emenda
    def step(img, k):
        return np.abs(np.take(img, k, axis=axis) - np.take(img, k - 1, axis=axis))
    far = [k for k in range(256, j.shape[axis] - 256, 97) if abs(k - seam) > 256]
    typ = np.mean([step(j, k).mean() for k in far])
    seam_rows.append({
        "site": f"{name}_{ctx}", "comparacao": "salto medio entre vizinhos",
        "mosaico_emenda": step(mos, seam).mean(),
        "junto_emenda": step(j, seam).mean(),
        "junto_tipico": typ,
        "salto_assinado_mosaico": (np.take(mos, seam, axis=axis) - np.take(mos, seam - 1, axis=axis)).mean(),
        "salto_assinado_junto": (np.take(j, seam, axis=axis) - np.take(j, seam - 1, axis=axis)).mean(),
    })
    # folha: recorte 512 px de cada lado da emenda, mosaico | junto | dif x8
    sl = [slice(None), slice(None)]
    sl[axis] = slice(seam - 512, seam + 512)
    other = 1 - axis
    mid = j.shape[other] // 2
    sl[other] = slice(mid - 512, mid + 512)
    m_c, j_c = mos[tuple(sl)], j[tuple(sl)]
    sheet = np.hstack([to8(m_c), to8(j_c), diff_img(m_c - j_c)])
    Image.fromarray(sheet).save(OUT / f"{name}_{ctx}_mosaico_junto_dif.png")


# saida ---------------------------------------------------------------------
def write_csv(path, rows):
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(keys)
        for r in rows:
            w.writerow([("" if r.get(k) is None else
                         (f"{r[k]:.3f}".replace(".", ",") if isinstance(r[k], float) else r[k]))
                        for k in keys])


write_csv(OUT / "context_stats.csv", rows)
write_csv(OUT / "seam_stats.csv", seam_rows)
for r in rows + seam_rows:
    print(";".join(f"{k}={v:.2f}" if isinstance(v, float) else f"{k}={v}" for k, v in r.items()))
print("saidas em", OUT)
