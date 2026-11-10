# baixa o gedtm30 v1.2 (30 m) do brasil em tiles locais -----------------------
#
# fonte: GEDTM30 v1.2 (OpenLandMap), CC-BY 4.0
#   https://codeberg.org/openlandmap/GEDTM30
#   doi:10.5281/zenodo.18887460
#
# o que faz:
#   1. area: brasil (world bank admin0 10m) com buffer de 0,25 grau, unido ao
#      retangulo do mapa (config/canvas_5880.csv) com 0,05 grau de folga;
#      assim o relevo cobre todo o mapa, inclusive os paises vizinhos nos
#      cantos, e nao cai a zero na borda do que foi baixado
#   2. monta a grade de tiles de 4096 x 4096 px alinhada aos blocos de
#      2048 px do cog global (cada bloco remoto e lido uma vez so)
#   3. baixa em paralelo os tiles que tocam o brasil com buffer
#   4. grava cada tile em geotiff deflate, valor bruto em metros, sem o
#      scale = 0.1 que o cabecalho do cog traz por engano (nota abaixo)
#   5. confere cada tile (% de pixels validos, min, max, media) e grava o
#      indice csv
#   6. monta o vrt do mosaico e confere pontos de controle
#
# unidade: o cog v1.2 e float32 em metros (cog_list.csv do repositorio:
#   scale 1), mas o cabecalho traz scale = 0.1, herdado das versoes int32
#   em decimetros. conferido em 07/11/2026 lendo o valor bruto: piracicaba
#   541 m, pico da bandeira 2874 m. terra e gdal aplicariam o 0.1 e dariam
#   54 m; por isso os tiles saem sem scale/offset.
#
# retomavel: tiles ja gravados sao pulados; rodar de novo completa o que
#   faltou. tiles so de nodata ficam marcados "empty" no indice.
#
# uso (powershell):
#   piloto:   python <caminho>/01_download_gedtm30_brazil.py --max-tiles 32
#   completo: python <caminho>/01_download_gedtm30_brazil.py

import os

# gdal: leitura remota do cog por http, com novas tentativas
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")
os.environ.setdefault("GDAL_HTTP_MULTIRANGE", "YES")
os.environ.setdefault("GDAL_HTTP_MERGE_CONSECUTIVE_RANGES", "YES")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "5")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "5")
os.environ.setdefault("GDAL_HTTP_TIMEOUT", "180")
os.environ.setdefault("VSI_CACHE", "TRUE")

import argparse
import math
import random
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from xml.sax.saxutils import escape

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import shapely
from rasterio.windows import Window
from shapely.geometry import box
from shapely.prepared import prep

# configuracao ---------------------------------------------------------------

SRC_URL = ("https://s3.opengeohub.org/global/dtm/v1.2/"
           "gedtm_rf_m_30m_s_20060101_20151231_go_epsg.4326.3855_v1.2.tif")
SRC = "/vsicurl/" + SRC_URL
VERSION = "v1_2"

TILE_PX = 4096        # 2 x 2 blocos de 2048 px do cog de origem
BUFFER_DEG = 0.25     # ~28 km alem da fronteira
N_WORKERS = 16
SEED = 42             # ordem aleatoria fixa: o piloto pega tiles representativos

CANVAS_BUFFER_DEG = 0.05

# scripts/ -> brazil_shaded_relief_maps/ -> projects/ -> cassio/
PROJECT = Path(__file__).resolve().parents[1]
CANVAS_CSV = PROJECT / "config" / "canvas_5880.csv"
CASSIO = Path(__file__).resolve().parents[3]
BOUNDARY = (CASSIO / "data" / "lac_countries" / "wb_countries_admin0_10m" /
            "WB_countries_Admin0_10m" / "WB_countries_Admin0_10m.shp")
OUT_DIR = CASSIO / "data" / "gedtm30_brazil"
TILE_DIR = OUT_DIR / "tiles"
INDEX_CSV = OUT_DIR / f"gedtm30_{VERSION}_brazil_tile_index.csv"
VRT_PATH = OUT_DIR / f"gedtm30_{VERSION}_brazil_30m.vrt"

# pontos de controle: (lon, lat, altitude de referencia em m)
CONTROL_POINTS = {
    "esalq_piracicaba": (-47.630, -22.711, 540),
    "pico_da_bandeira": (-41.7972, -20.4344, 2892),
    "brasilia_esplanada": (-47.8636, -15.7998, 1170),
    "manaus_centro": (-60.0217, -3.1190, 60),
}

VALID_MAX = 1e38      # nodata = maximo do float32 (3.4e38)

# worker: um tile por chamada -------------------------------------------------

_src = None


def _open_src():
    global _src
    if _src is None:
        _src = rasterio.open(SRC)
    return _src


def _stats(a):
    valid = np.isfinite(a) & (a < VALID_MAX)
    n = int(valid.sum())
    if n == 0:
        return dict(valid_pct=0.0, min_m=np.nan, max_m=np.nan, mean_m=np.nan)
    v = a[valid]
    return dict(valid_pct=round(100 * n / a.size, 3),
                min_m=round(float(v.min()), 2),
                max_m=round(float(v.max()), 2),
                mean_m=round(float(v.mean()), 2))


def download_tile(task):
    global _src
    t0 = time.time()
    out = Path(task["path"])
    row = {k: task[k] for k in ("tile_id", "file", "row_tile", "col_tile",
                                "row_off", "col_off", "width", "height",
                                "xmin", "ymin", "xmax", "ymax")}

    if out.exists():
        with rasterio.open(out) as d:
            a = d.read(1)
        row.update(status="exists", **_stats(a),
                   size_mb=round(out.stat().st_size / 1e6, 1),
                   seconds=round(time.time() - t0, 1), error="")
        return row

    win = Window(task["col_off"], task["row_off"], task["width"], task["height"])
    err = ""
    a = None
    for attempt in range(1, 5):
        try:
            src = _open_src()
            a = src.read(1, window=win)
            transform = src.window_transform(win)
            crs, nodata = src.crs, src.nodata
            break
        except Exception as e:  # rede: reabre e tenta de novo
            err = repr(e)
            _src = None
            time.sleep(10 * attempt)
    if a is None:
        row.update(status="failed", valid_pct=np.nan, min_m=np.nan,
                   max_m=np.nan, mean_m=np.nan, size_mb=0.0,
                   seconds=round(time.time() - t0, 1), error=err[:300])
        return row

    st = _stats(a)
    if st["valid_pct"] == 0:
        row.update(status="empty", **st, size_mb=0.0,
                   seconds=round(time.time() - t0, 1), error="")
        return row

    # sem scale/offset: valor bruto em metros (ver cabecalho do script)
    profile = dict(driver="GTiff", dtype="float32", count=1,
                   width=task["width"], height=task["height"],
                   crs=crs, transform=transform, nodata=nodata,
                   tiled=True, blockxsize=512, blockysize=512,
                   compress="deflate", predictor=3, zlevel=6)
    tmp = out.with_name(out.stem + ".part.tif")
    with rasterio.open(tmp, "w", **profile) as d:
        d.write(a, 1)
        d.update_tags(source=SRC_URL, version="GEDTM30 v1.2",
                      units="meter", vertical_datum="EGM2008 (EPSG:3855)",
                      note="written without the scale=0.1 of the source header")
    os.replace(tmp, out)

    row.update(status="ok", **st, size_mb=round(out.stat().st_size / 1e6, 1),
               seconds=round(time.time() - t0, 1), error="")
    return row


# grade de tiles que tocam o brasil -------------------------------------------

def brazil_geometry():
    g = gpd.read_file(BOUNDARY)
    bra = g.loc[g["ISO_A3"] == "BRA"]
    if len(bra) != 1:
        raise RuntimeError(f"esperava 1 poligono do brasil, achei {len(bra)}")
    aoi = shapely.buffer(bra.geometry.union_all(), BUFFER_DEG)

    # retangulo do mapa em epsg:5880, densificado a cada 5 km antes de ir
    # para 4326 (na policonica os lados viram curvas)
    cv = pd.read_csv(CANVAS_CSV, sep=";", encoding="utf-8-sig").iloc[0]
    rect = box(cv["xmin"], cv["ymin"], cv["xmax"], cv["ymax"]).segmentize(5000)
    rect = gpd.GeoSeries([rect], crs=cv["crs"]).to_crs(4326).iloc[0]
    return shapely.union(aoi, shapely.buffer(rect, CANVAS_BUFFER_DEG))


def build_tasks(src, geom):
    T, W, H = src.transform, src.width, src.height
    minx, miny, maxx, maxy = geom.bounds
    c0 = max(0, int((minx - T.c) / T.a))
    c1 = min(W, int(math.ceil((maxx - T.c) / T.a)))
    r0 = max(0, int((maxy - T.f) / T.e))
    r1 = min(H, int(math.ceil((miny - T.f) / T.e)))
    pg = prep(geom)
    tasks = []
    for tr in range(r0 // TILE_PX, (r1 - 1) // TILE_PX + 1):
        for tc in range(c0 // TILE_PX, (c1 - 1) // TILE_PX + 1):
            col_off, row_off = tc * TILE_PX, tr * TILE_PX
            w = min(TILE_PX, W - col_off)
            h = min(TILE_PX, H - row_off)
            x0, y0 = T.c + col_off * T.a, T.f + row_off * T.e
            x1, y1 = x0 + w * T.a, y0 + h * T.e
            if not pg.intersects(box(x0, y1, x1, y0)):
                continue
            tile_id = f"r{tr:03d}_c{tc:04d}"
            name = f"gedtm30_{VERSION}_30m_{tile_id}.tif"
            tasks.append(dict(tile_id=tile_id, file=name, row_tile=tr,
                              col_tile=tc, row_off=row_off, col_off=col_off,
                              width=w, height=h, xmin=x0, ymin=y1, xmax=x1,
                              ymax=y0, path=str(TILE_DIR / name)))
    return tasks


# indice csv e vrt ------------------------------------------------------------

def write_index(rows):
    df = pd.DataFrame(rows).sort_values(["row_tile", "col_tile"])
    df.to_csv(INDEX_CSV, sep=";", decimal=",", index=False,
              encoding="utf-8-sig")


def previous_empty():
    # tiles so de nodata de rodadas anteriores: nao baixa de novo e mantem no indice
    if not INDEX_CSV.exists():
        return []
    df = pd.read_csv(INDEX_CSV, sep=";", decimal=",", encoding="utf-8-sig")
    return df.loc[df["status"] == "empty"].to_dict("records")


def write_vrt(rows, src):
    ok = [r for r in rows if r["status"] in ("ok", "exists")]
    if not ok:
        return False
    T = src.transform
    cmin = min(r["col_off"] for r in ok)
    rmin = min(r["row_off"] for r in ok)
    cmax = max(r["col_off"] + r["width"] for r in ok)
    rmax = max(r["row_off"] + r["height"] for r in ok)
    x0, y0 = T.c + cmin * T.a, T.f + rmin * T.e
    lines = [
        f'<VRTDataset rasterXSize="{cmax - cmin}" rasterYSize="{rmax - rmin}">',
        f'  <SRS dataAxisToSRSAxisMapping="2,1">{escape(src.crs.to_wkt())}</SRS>',
        f'  <GeoTransform>{x0!r}, {T.a!r}, 0.0, {y0!r}, 0.0, {T.e!r}</GeoTransform>',
        '  <VRTRasterBand dataType="Float32" band="1">',
        f'    <NoDataValue>{src.nodata!r}</NoDataValue>',
    ]
    for r in sorted(ok, key=lambda r: (r["row_off"], r["col_off"])):
        w, h = r["width"], r["height"]
        lines += [
            '    <SimpleSource>',
            f'      <SourceFilename relativeToVRT="1">tiles/{r["file"]}</SourceFilename>',
            '      <SourceBand>1</SourceBand>',
            f'      <SourceProperties RasterXSize="{w}" RasterYSize="{h}" '
            'DataType="Float32" BlockXSize="512" BlockYSize="512" />',
            f'      <SrcRect xOff="0" yOff="0" xSize="{w}" ySize="{h}" />',
            f'      <DstRect xOff="{r["col_off"] - cmin}" yOff="{r["row_off"] - rmin}" '
            f'xSize="{w}" ySize="{h}" />',
            '    </SimpleSource>',
        ]
    lines += ['  </VRTRasterBand>', '</VRTDataset>', '']
    VRT_PATH.write_text("\n".join(lines), encoding="utf-8")
    return True


def check_control_points():
    print("\nconferencia no vrt (valor bruto, m):")
    with rasterio.open(VRT_PATH) as v:
        print(f"  vrt: {v.width} x {v.height} px, {v.dtypes[0]}, "
              f"nodata {v.nodata}, scale {v.scales[0]}, crs {v.crs}")
        for k, (x, y, ref) in CONTROL_POINTS.items():
            b = v.bounds
            if not (b.left <= x <= b.right and b.bottom <= y <= b.top):
                print(f"  {k:20s} fora do vrt")
                continue
            val = float(next(v.sample([(x, y)]))[0])
            txt = "nodata (tile ainda nao baixado)" if val > VALID_MAX else f"{val:8.1f}"
            print(f"  {k:20s} {txt}   (referencia ~{ref} m)")


# execucao --------------------------------------------------------------------

def fmt_min(s):
    return f"{s / 60:.0f} min" if s < 5400 else f"{s / 3600:.1f} h"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-tiles", type=int, default=None,
                    help="piloto: baixa so os N primeiros tiles da ordem aleatoria")
    ap.add_argument("--workers", type=int, default=N_WORKERS)
    args = ap.parse_args()

    TILE_DIR.mkdir(parents=True, exist_ok=True)

    print(f"origem: {SRC_URL}")
    with rasterio.open(SRC) as src:
        print(f"cog: {src.width} x {src.height} px, {src.dtypes[0]}, "
              f"bloco {src.block_shapes[0]}, scale no cabecalho {src.scales[0]}")
        geom = brazil_geometry()
        tasks = build_tasks(src, geom)

        empty_rows = previous_empty()
        empty = {r["tile_id"] for r in empty_rows}
        tasks = [t for t in tasks if t["tile_id"] not in empty]
        random.Random(SEED).shuffle(tasks)
        n_all = len(tasks)
        if args.max_tiles:
            tasks = tasks[:args.max_tiles]

        n_done = sum(Path(t["path"]).exists() for t in tasks)
        gpx = sum(t["width"] * t["height"] for t in tasks) / 1e9
        print(f"tiles na area (brasil + {BUFFER_DEG} grau, retangulo do mapa"
              f" + {CANVAS_BUFFER_DEG} grau): {n_all}"
              f" (+{len(empty)} vazios ja conhecidos)")
        print(f"nesta rodada: {len(tasks)} tiles, {gpx:.1f} Gpx, "
              f"{gpx * 4:.0f} GB sem compressao; {n_done} ja gravados; "
              f"{args.workers} workers")

        rows, t0, n = [], time.time(), len(tasks)
        n_new, mb_new = 0, 0.0
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(download_tile, t) for t in tasks]
            for i, f in enumerate(as_completed(futs), 1):
                r = f.result()
                rows.append(r)
                if r["status"] == "ok":
                    n_new += 1
                    mb_new += r["size_mb"]
                el = time.time() - t0
                rate = n_new / el * 60 if n_new else 0
                left = n - i
                eta = fmt_min(left / (i / el)) if i else "?"
                print(f"[{i:4d}/{n}] {r['tile_id']} {r['status']:7s} "
                      f"{r['seconds']:6.1f} s  valido {r['valid_pct']:5.1f}%  "
                      f"| {rate:5.1f} tiles/min  {mb_new / el:5.1f} MB/s gravados"
                      f"  | falta ~{eta}", flush=True)
                if i % 25 == 0:
                    write_index(rows + empty_rows)

        write_index(rows + empty_rows)
        el = time.time() - t0
        by = pd.Series([r["status"] for r in rows]).value_counts().to_dict()
        print(f"\nfim em {fmt_min(el)}: {by}")
        print(f"gravado nesta rodada: {n_new} tiles, {mb_new / 1e3:.1f} GB")
        if n_new:
            sec_tile = el / n_new
            print(f"taxa: {sec_tile:.1f} s por tile (parede, {args.workers} workers)"
                  f" -> {n_all} tiles levariam ~{fmt_min(sec_tile * n_all)}")
        fails = [r for r in rows if r["status"] == "failed"]
        if fails:
            print(f"ATENCAO: {len(fails)} tiles falharam; rode o script de novo."
                  f" Primeiro erro: {fails[0]['error']}")

        # vrt so com o que esta gravado: no piloto ele cobre os tiles do piloto
        if args.max_tiles:
            print("piloto: indice e vrt cobrem so os tiles desta rodada")
        if write_vrt(rows, src):
            print(f"vrt: {VRT_PATH}")
            check_control_points()


if __name__ == "__main__":
    main()
