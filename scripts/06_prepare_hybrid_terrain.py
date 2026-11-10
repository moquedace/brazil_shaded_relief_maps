# brazil_shaded_relief_maps - 06 prepara o terreno hibrido (macro E128 / micro E8) -
#
# roda no Python 3.13 do sistema (numpy, scipy, rasterio, Pillow). PowerShell,
# sem o Blender nem o R abertos (a etapa national usa ~20 GB de RAM):
#   python "<projeto>\scripts\06_prepare_hybrid_terrain.py" --stage national
#   python "<projeto>\scripts\06_prepare_hybrid_terrain.py" --stage test
#   python "<projeto>\scripts\06_prepare_hybrid_terrain.py" --stage blocks
#
# metodo: rodada 2 (09/11/2026), aceita pelo Cassio (log 15); copia em
# docs/round2/METODO_E_RESULTADOS.md. Terreno cartografico em duas
# escalas, nunca distribuido como medida de altitude:
#   z30       DEM de 30 m do 02, mar e sem dado = 0, corte em 0-7000 m
#   z120      media 4 x 4 de z30
#   macro     gaussiana de z120 com sigma de 2000 m (16,67 px de 120 m),
#             bordas "nearest", truncada em 4 sigma (8 km)
#   macro30   bilinear de macro nos centros das celulas de 30 m
#   z_hibrido macro30 + (8 / 128) x (z30 - macro30)
# o 07 aplica E128 ao z_hibrido: E128 nas formas largas, E8 no detalhe.
#
# diferenca para a rodada 2, com o porque: a gaussiana sai uma vez no canvas
# inteiro, nao por janela. Assim todo bloco usa a mesma macroforma e os
# blocos podem emendar; na rodada 2 cada janela tinha a sua (borda "nearest"
# na propria janela).
#
# entradas (somente leitura):
#   data/intermediate/02_prepared_dem/raster/gedtm30_v1_2_brazil_5880_30m.tif
#   data/intermediate/02_prepared_dem/tables/heightmap_blocks.csv
#   config/canvas_5880.csv
#
# saidas: data/intermediate/06_hybrid_terrain/
#   raster/macro_120m.tif           macroforma em m, float32, canvas inteiro
#   raster/hybrid_480m.tif          terreno hibrido a 480 m em m (QGIS)
#   heightmaps/far_hybrid_480m.png  entorno distante do 07, 0-7000 m em 16 bits
#   heightmaps/hybrid_rRR_cCC.png   um por bloco com Brasil, na mesma area dos
#                                   heightmaps do 02 (nucleo 8192 + 1024 px de
#                                   cada lado), 0-7000 m em 16 bits
#   heightmaps/test/<id>.png        testes de contexto e emenda do 07
#   tables/test_jobs.json           renders de teste para o 07 --mode test
#   tables/national_stats.json, tables/blocks_log.csv
#
# etapas:
#   national  z120, macro e entorno de 480 m (le os 48 GB do DEM uma vez)
#   test      heightmaps e lista de renders dos testes de contexto e emenda
#   blocks    heightmaps hibridos dos 183 blocos com Brasil (em paralelo)

import argparse
import csv
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import from_origin
from rasterio.warp import transform as warp_transform
from rasterio.windows import Window
from scipy.ndimage import gaussian_filter

Image.MAX_IMAGE_PIXELS = None

# caminhos e constantes --------------------------------------------------------

PROJECT = Path(__file__).resolve().parents[1]
DIR_02 = PROJECT / "data" / "intermediate" / "02_prepared_dem"
DEM_FILE = DIR_02 / "raster" / "gedtm30_v1_2_brazil_5880_30m.tif"
DIR_06 = PROJECT / "data" / "intermediate" / "06_hybrid_terrain"
DIR_RAS = DIR_06 / "raster"
DIR_HM = DIR_06 / "heightmaps"
DIR_TAB = DIR_06 / "tables"
MACRO_FILE = DIR_RAS / "macro_120m.tif"
FAR_PNG = DIR_HM / "far_hybrid_480m.png"

RES = 30.0             # m, grade do DEM e dos heightmaps
Z_MAX = 7000.0         # m, topo da escala do heightmap (log 8)
SIGMA_M = 2000.0       # m, gaussiana da macroforma (rodada 2)
E_MACRO, E_MICRO = 128.0, 8.0
MICRO = E_MICRO / E_MACRO          # 1/16: peso do residual no z hibrido
COARSE = 4                         # 30 m -> 120 m
FAR_FACTOR = 4                     # 120 m -> 480 m (entorno distante)
BLOCK_MARGIN = 1024                # px de 30 m de cada lado do nucleo (como o 02)

# testes de contexto (log 15). Centros da rodada 2 (window_metadata.json,
# EPSG:5880, multiplos de 120 m) para comparar com os renders nativos dela, e o
# Acre, o ponto do Brasil mais perto dos Andes, cujas formas em E128 projetam
# sombra a centenas de km
TEST_SITES = [
    ("mantiqueira", "xy", 5960280.0, 7494360.0),
    ("amazonia", "xy", 4379520.0, 9512280.0),
    ("aparados", "xy", 5381280.0, 6765480.0),
    ("acre", "lonlat", -73.0, -7.6),            # Mancio Lima, Serra do Divisor
]
TEST_CORE = 1024                   # nucleo dos testes de contexto (30,72 km)
TEST_REF_MARGIN = 8192             # margem da rodada 2 (17408 px no total)
TEST_MARGINS = [1024, 2048]        # margens de producao a testar
TEST_CONTEXT_KM = [250, 600, 1200] # alcance do anel distante (07)
# emendas: dois nucleos vizinhos de 2048 px renderizados separados e um render
# unico dos dois juntos, como referencia. Linha vertical na divisa c12|c13 do
# canvas perto da Pedra da Mina (a do teste do log 12) e linha horizontal no
# Quadrilatero Ferrifero (o bloco do piloto do 04)
SEAM_CORE = 2048
SEAM_CONTEXT_KM = 600
SEAM_TESTS = [
    ("seam_ew", "x", -44.84, -22.43),   # fronteira leste-oeste (linha vertical)
    ("seam_ns", "y", -43.95, -20.10),   # fronteira norte-sul (linha horizontal)
]


# grade --------------------------------------------------------------------------

def num(s):
    s = str(s).strip()
    return float(s.replace(".", "").replace(",", ".")) if "," in s else float(s)


def read_canvas():
    with open(PROJECT / "config" / "canvas_5880.csv", encoding="utf-8-sig") as f:
        row = next(csv.DictReader(f, delimiter=";"))
    c = {k: (row[k] if k == "crs" else num(row[k])) for k in row}
    for k in ("ncol", "nrow", "block_px", "overlap_px", "nblock_x", "nblock_y"):
        c[k] = int(c[k])
    assert c["res_m"] == RES and c["ncol"] % (COARSE * FAR_FACTOR) == 0
    return c


def read_blocks():
    with open(DIR_02 / "tables" / "heightmap_blocks.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    for r in rows:
        for k in ("core_xmin", "core_xmax", "core_ymin", "core_ymax"):
            r[k] = num(r[k])
        r["row"], r["col"] = int(r["row"]), int(r["col"])
        r["has_brazil"] = str(r["has_brazil"]).upper() == "TRUE"
    return rows


def clean(z):
    # mar e sem dado = 0, corte em 0-7000 m (como o 02 e a rodada 2)
    z = z.astype(np.float32, copy=False)
    z[~np.isfinite(z)] = 0
    np.clip(z, 0, Z_MAX, out=z)
    return z


def read_dem(ds, canvas, row0, col0, nrows, ncols):
    # linhas e colunas na grade de 30 m do canvas; fora do arquivo = 0
    dc = (canvas["xmin"] - ds.transform.c) / RES
    dr = (ds.transform.f - canvas["ymax"]) / RES
    assert abs(dc - round(dc)) < 1e-6 and abs(dr - round(dr)) < 1e-6, "DEM fora da grade"
    c0, r0 = col0 + int(round(dc)), row0 + int(round(dr))
    inside = c0 >= 0 and r0 >= 0 and c0 + ncols <= ds.width and r0 + nrows <= ds.height
    w = Window(c0, r0, ncols, nrows)
    if inside:
        z = ds.read(1, window=w)
    else:
        z = ds.read(1, window=w, boundless=True, fill_value=0)
    if ds.nodata is not None and np.isfinite(ds.nodata):
        z = np.where(z == ds.nodata, 0, z)
    return clean(z)


def to_png16(h, path):
    # metros -> 0-65535 (0-7000 m), como os heightmaps do 02
    a = np.round(np.clip(h, 0, Z_MAX) * (65535.0 / Z_MAX)).astype(np.uint16)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(a).save(path, compress_level=3)


def fmt_time(s):
    return f"{s:.0f} s" if s < 120 else (f"{s / 60:.0f} min" if s < 5400 else f"{s / 3600:.1f} h")


# etapa national: z120, macro e entorno de 480 m ----------------------------------

def write_tif(path, a, canvas, res):
    path.parent.mkdir(parents=True, exist_ok=True)
    prof = dict(driver="GTiff", width=a.shape[1], height=a.shape[0], count=1,
                dtype="float32", crs=canvas["crs"],
                transform=from_origin(canvas["xmin"], canvas["ymax"], res, res),
                tiled=True, blockxsize=512, blockysize=512, compress="deflate",
                predictor=3, BIGTIFF="YES")
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(a, 1)


def stage_national(args, canvas):
    n30 = canvas["ncol"]
    n120 = n30 // COARSE
    strip = 4096                       # linhas de 30 m por leitura (~2,4 GB)
    t0 = time.time()
    print(f"\n# 06 national {'-' * 62}")
    print(f"z120: media 4 x 4 do DEM de 30 m ({n30} px -> {n120} px), em faixas de {strip} linhas")
    z120 = np.zeros((n120, n120), np.float32)
    with rasterio.open(DEM_FILE) as ds:
        print(f"DEM: {ds.width} x {ds.height} px, pixel {ds.transform.a:g} m, nodata {ds.nodata}")
        for i, r0 in enumerate(range(0, n30, strip)):
            z = read_dem(ds, canvas, r0, 0, strip, n30)
            z120[r0 // COARSE:(r0 + strip) // COARSE] = \
                z.reshape(strip // COARSE, COARSE, n120, COARSE).mean(axis=(1, 3), dtype=np.float32)
            del z
            done = (i + 1) * strip / n30
            el = time.time() - t0
            print(f"  [{i + 1}/{n30 // strip}] {100 * done:.0f}% em {fmt_time(el)}"
                  f" | falta ~{fmt_time(el / done * (1 - done))}", flush=True)

    t1 = time.time()
    sigma = SIGMA_M / (RES * COARSE)
    print(f"macro: gaussiana sigma {SIGMA_M:g} m = {sigma:.2f} px de 120 m, bordas nearest", flush=True)
    macro = gaussian_filter(z120, sigma=sigma, mode="nearest", truncate=4.0)
    print(f"  pronta em {fmt_time(time.time() - t1)}", flush=True)
    write_tif(MACRO_FILE, macro, canvas, RES * COARSE)
    print(f"gravado: {MACRO_FILE}", flush=True)

    # terreno hibrido a 120 m (no lugar de z120) e entorno distante a 480 m
    z120 -= macro
    z120 *= MICRO
    z120 += macro
    stats = dict(macro_max_m=float(macro.max()), hybrid120_max_m=float(z120.max()))
    del macro
    nf = n120 // FAR_FACTOR
    far = z120.reshape(nf, FAR_FACTOR, nf, FAR_FACTOR).mean(axis=(1, 3), dtype=np.float32)
    del z120
    write_tif(DIR_RAS / "hybrid_480m.tif", far, canvas, RES * COARSE * FAR_FACTOR)
    to_png16(far, FAR_PNG)
    stats.update(far_px=nf, far_max_m=float(far.max()), far_mean_m=float(far.mean()),
                 sigma_m=SIGMA_M, e_macro=E_MACRO, e_micro=E_MICRO,
                 seconds=round(time.time() - t0, 1))
    DIR_TAB.mkdir(parents=True, exist_ok=True)
    (DIR_TAB / "national_stats.json").write_text(json.dumps(stats, indent=2))
    print(f"gravado: {DIR_RAS / 'hybrid_480m.tif'} e {FAR_PNG} ({nf} px)")
    print(f"maximos: macro {stats['macro_max_m']:.0f} m, hibrido 120 m {stats['hybrid120_max_m']:.0f} m,"
          f" entorno 480 m {stats['far_max_m']:.0f} m")
    print(f"fim em {fmt_time(time.time() - t0)}")


# terreno hibrido de uma janela de 30 m ---------------------------------------------

def hybrid_window(dem, macro_ds, canvas, row0, col0, nrows, ncols):
    # janela na grade de 30 m do canvas (pode sair do canvas: DEM = 0 e macro
    # repetida da borda, como o "nearest" da gaussiana)
    z = read_dem(dem, canvas, row0, col0, nrows, ncols)
    n120 = canvas["ncol"] // COARSE
    # posicao de cada centro de celula de 30 m na grade de 120 m (centros)
    rf = (np.arange(row0, row0 + nrows) + 0.5) / COARSE - 0.5
    cf = (np.arange(col0, col0 + ncols) + 0.5) / COARSE - 0.5
    ri, ci = np.floor(rf).astype(np.int64), np.floor(cf).astype(np.int64)
    wr, wc = (rf - ri).astype(np.float32), (cf - ci).astype(np.float32)
    rows = np.clip(np.arange(ri.min(), ri.max() + 2), 0, n120 - 1)
    cols = np.clip(np.arange(ci.min(), ci.max() + 2), 0, n120 - 1)
    w = Window(int(cols.min()), int(rows.min()), int(cols.max() - cols.min() + 1),
               int(rows.max() - rows.min() + 1))
    m = macro_ds.read(1, window=w)
    m = m[np.ix_(rows - rows.min(), cols - cols.min())]
    ri -= ri.min()
    ci -= ci.min()
    a = m[:, ci] * (1 - wc) + m[:, ci + 1] * wc               # linhas de 120 m x colunas de 30 m
    macro30 = a[ri, :] * (1 - wr)[:, None] + a[ri + 1, :] * wr[:, None]
    del a, m
    z -= macro30
    z *= MICRO
    z += macro30
    return z


def check_inputs():
    if not MACRO_FILE.exists():
        sys.exit(f"falta {MACRO_FILE}: rode antes o --stage national")


# etapa test: heightmaps e lista de renders dos testes ------------------------------

def snap(v, origin):
    return origin + round((v - origin) / RES) * RES


def stage_test(args, canvas):
    check_inputs()
    t0 = time.time()
    print(f"\n# 06 test {'-' * 66}")
    out = DIR_HM / "test"
    out.mkdir(parents=True, exist_ok=True)
    jobs, made = [], {}

    def to_xy(kind, a, b):
        if kind == "xy":
            return a, b
        x, y = warp_transform("EPSG:4326", canvas["crs"], [a], [b])
        return x[0], y[0]

    def heightmap(name, cx, cy, wx, wy, dem, mac):
        # plano de perto centrado em (cx, cy), wx x wy px de 30 m
        key = (name, round(cx), round(cy), wx, wy)
        if key in made:
            return made[key]
        f = out / f"{name}_{wx}x{wy}.png"
        if not f.exists() or args.overwrite:
            col0 = int(round((cx - wx * RES / 2 - canvas["xmin"]) / RES))
            row0 = int(round((canvas["ymax"] - (cy + wy * RES / 2)) / RES))
            h = hybrid_window(dem, mac, canvas, row0, col0, wy, wx)
            to_png16(h, f)
            print(f"  heightmap {f.name}: {wx} x {wy} px, max {h.max():.0f} m", flush=True)
            del h
        made[key] = f
        return f

    def job(jid, f, cx, cy, wx, wy, core_x, core_y, ctx_km):
        jobs.append(dict(id=jid, height=str(f), nx=wx, ny=wy, core_x=core_x, core_y=core_y,
                         cx=cx, cy=cy, context_km=ctx_km))

    with rasterio.open(DEM_FILE) as dem, rasterio.open(MACRO_FILE) as mac:
        # contexto: mesmo nucleo, margens e alcances diferentes
        for name, kind, a, b in TEST_SITES:
            x, y = to_xy(kind, a, b)
            # centro do nucleo numa aresta de celula de 30 m (nucleo par)
            cx, cy = snap(x, canvas["xmin"]), snap(y, canvas["ymax"])
            n = TEST_CORE + 2 * TEST_REF_MARGIN
            f = heightmap(name, cx, cy, n, n, dem, mac)
            job(f"{name}_ref_m{TEST_REF_MARGIN}", f, cx, cy, n, n, TEST_CORE, TEST_CORE, 0)
            for m in TEST_MARGINS:
                n = TEST_CORE + 2 * m
                f = heightmap(name, cx, cy, n, n, dem, mac)
                ctxs = TEST_CONTEXT_KM if m == TEST_MARGINS[0] else [TEST_CONTEXT_KM[1]]
                for ctx in ctxs:
                    job(f"{name}_m{m}_c{ctx}", f, cx, cy, n, n, TEST_CORE, TEST_CORE, ctx)

        # emendas: dois nucleos vizinhos e o render unico dos dois
        m = TEST_MARGINS[0]
        half = SEAM_CORE * RES / 2
        for name, axis, lon, lat in SEAM_TESTS:
            x, y = to_xy("lonlat", lon, lat)
            if axis == "x":
                # linha vertical na divisa de blocos c12|c13 do canvas
                xs = canvas["xmin"] + 13 * canvas["block_px"] * RES
                ys = snap(y, canvas["ymax"])
                parts = [("a", xs - half, ys, SEAM_CORE, SEAM_CORE),
                         ("b", xs + half, ys, SEAM_CORE, SEAM_CORE),
                         ("joint", xs, ys, 2 * SEAM_CORE, SEAM_CORE)]
            else:
                xs = snap(x, canvas["xmin"])
                ys = snap(y, canvas["ymax"])
                parts = [("a", xs, ys + half, SEAM_CORE, SEAM_CORE),
                         ("b", xs, ys - half, SEAM_CORE, SEAM_CORE),
                         ("joint", xs, ys, SEAM_CORE, 2 * SEAM_CORE)]
            for part, cx, cy, kx, ky in parts:
                f = heightmap(f"{name}_{part}", cx, cy, kx + 2 * m, ky + 2 * m, dem, mac)
                job(f"{name}_{part}_m{m}_c{SEAM_CONTEXT_KM}", f, cx, cy, kx + 2 * m, ky + 2 * m,
                    kx, ky, SEAM_CONTEXT_KM)

    DIR_TAB.mkdir(parents=True, exist_ok=True)
    (DIR_TAB / "test_jobs.json").write_text(json.dumps(jobs, indent=2))
    print(f"{len(jobs)} renders de teste em {DIR_TAB / 'test_jobs.json'}; {len(made)} heightmaps"
          f" em {fmt_time(time.time() - t0)}")


# etapa blocks: heightmaps hibridos dos blocos com Brasil -------------------------

def one_block(b, canvas, overwrite):
    f = DIR_HM / f"hybrid_{b['block_id']}.png"
    if f.exists() and not overwrite:
        return b["block_id"], "ja existe", 0.0, None
    t = time.time()
    bp = canvas["block_px"]
    n = bp + 2 * BLOCK_MARGIN
    row0, col0 = b["row"] * bp - BLOCK_MARGIN, b["col"] * bp - BLOCK_MARGIN
    with rasterio.open(DEM_FILE) as dem, rasterio.open(MACRO_FILE) as mac:
        h = hybrid_window(dem, mac, canvas, row0, col0, n, n)
    zmax = float(h.max())
    to_png16(h, f)
    return b["block_id"], "ok", time.time() - t, zmax


def stage_blocks(args, canvas):
    check_inputs()
    blocks = [b for b in read_blocks() if b["has_brazil"]]
    if args.blocks:
        blocks = [b for b in blocks if b["block_id"] in set(args.blocks)]
    print(f"\n# 06 blocks {'-' * 64}")
    print(f"{len(blocks)} blocos com Brasil, {args.workers} processos; saida em {DIR_HM}")
    DIR_TAB.mkdir(parents=True, exist_ok=True)
    log = DIR_TAB / "blocks_log.csv"
    new = not log.exists()
    t0, n_done = time.time(), 0
    with open(log, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as flog, \
            ProcessPoolExecutor(max_workers=args.workers) as ex:
        w = csv.writer(flog, delimiter=";")
        if new:
            w.writerow(["block_id", "status", "seconds", "z_max_m"])
        futs = [ex.submit(one_block, b, canvas, args.overwrite) for b in blocks]
        for fu in as_completed(futs):
            bid, status, sec, zmax = fu.result()
            n_done += 1
            w.writerow([bid, status, f"{sec:.1f}".replace(".", ","),
                        "" if zmax is None else f"{zmax:.1f}".replace(".", ",")])
            flog.flush()
            el = time.time() - t0
            print(f"[{n_done}/{len(blocks)}] {bid} {status} {sec:.0f} s"
                  f" | falta ~{fmt_time(el / n_done * (len(blocks) - n_done))}", flush=True)
    print(f"fim em {fmt_time(time.time() - t0)}")


# execucao ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(prog="06_prepare_hybrid_terrain.py")
    ap.add_argument("--stage", choices=["national", "test", "blocks"], required=True)
    ap.add_argument("--blocks", nargs="*", default=None)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    canvas = read_canvas()
    {"national": stage_national, "test": stage_test, "blocks": stage_blocks}[args.stage](args, canvas)


if __name__ == "__main__":
    main()
