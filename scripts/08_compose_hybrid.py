# brazil_shaded_relief_maps - 08 cores sobre o render hibrido ----------------
#
# Python 3.13 (numpy, rasterio, scipy, Pillow). PowerShell, sem o Blender
# rodando:
#   python "<projeto>\scripts\08_compose_hybrid.py" --pilot     (4 blocos, ~1 min)
#   python "<projeto>\scripts\08_compose_hybrid.py"             (Brasil inteiro)
#   python "<projeto>\scripts\08_compose_hybrid.py" --mode full --pilot
#   python "<projeto>\scripts\08_compose_hybrid.py" --mode full (30 m, balanced = equilibrada)
#
# compoe os 3 temas (hipsometria, geologia, ordens de solo) sobre o render
# cinza do 07 nas duas apresentacoes da rodada 2 (docs/round2, log 15):
#   dramatica    cor no Blender + curva RGB^1,6. Aqui a cor entra no pos, que
#                da o mesmo resultado (log 15: MAE 2,7 niveis contra os
#                renders coloridos da rodada 2): RGB = oetf(lin(C) x
#                lin(cinza) / 0,6), 0,6 = cinza do material do 07; depois ^1,6
#   equilibrada  mix(C^1,3, cinza, gama 0,7) da rodada 2: k = (cinza/F)^0,7;
#                k < 1 escurece a cor, k > 1 clareia em direcao ao branco;
#                F = 0,7347676813916229 (sombra do plano, a mesma da rodada 2)
# cores iguais as da rodada 2 e do 05: rampa hipsometrica em Lab (0-3000 m),
#   geologia com as cores do Lamego (geology_classes.csv, color), solos por
#   ordem (soil_classes.csv, color_order), sem classe = #dfe8ee
# fora do Brasil (mar e vizinhos): papel #eeede9 com sombra projetada do
#   Brasil, como os FINAL_* da rodada 2 (deslocamento de 46 x 54 km, sigma
#   38 km, 28%); a borda do Brasil a 480 m e misturada pela fracao de Brasil
#
# --mode preview: cada bloco e composto a 30 m e reduzido a 480 m (media
#   16 x 16 so dos pixels do Brasil), e 4 janelas de 30,72 km a 30 m (as da
#   rodada 2 + Chapada) saem inteiras, para escolher a apresentacao (log 18)
# --mode full: a apresentacao escolhida (equilibrada, Cassio 10/11/2026, log
#   19) a 30 m, um GeoTIFF RGB por bloco e por tema nos 324 blocos do canvas
#   (os sem Brasil saem so com papel e sombra), com overviews internas e um
#   VRT por tema; a sombra projetada e a mesma da previa, calculada a 1920 m
#   e interpolada (bilinear) a 30 m; a borda do Brasil a 30 m e a do raster
#   de paises do 03 (sem mistura). Pula o que ja existe (--overwrite refaz)
#
# saida:
#   data/intermediate/08_compose/preview[_pilot]/        (preview)
#     brazil_<tema>_<apresentacao>_480m.jpg   Brasil inteiro a 480 m
#     compare_<tema>.jpg                      as duas lado a lado (1,9 km)
#     regions_<tema>.jpg                      4 janelas a 30 m, as duas
#     tables/preview_blocks.csv               tempo e cinza por bloco
#   data/final/30m[_pilot]/                               (full)
#     <tema>_<apresentacao>/tile_rRR_cCC.tif  8192 x 8192, RGB, EPSG:5880
#     brazil_<tema>_<apresentacao>_30m.vrt    mosaico (QGIS le as overviews)
#     brazil_<tema>_<apresentacao>_1920m.jpg  conferencia rapida
#     tables/full_blocks.csv
#
# opcoes: --pilot (r11_c12, r11_c13, r12_c12, r12_c13; recorta a saida)
#         --blocks r12_c13 ...   --workers 12
#         --presentation balanced|dramatic (full)   --overwrite (full)
#         --themes soil_diversity lithology_diversity ...  (padrao: todos)
#   nomes de arquivo em ingles (log 24): balanced = equilibrada, dramatic = dramatica
#
# diversidade (log 25, para o site): soil_diversity (componentes por unidade
#   de mapeamento de solos) e lithology_diversity (litologias por unidade
#   litoestratigrafica), rasters e cores do 03 (paletas cobre e Atlantico), sem
#   unidade = cinza #d9d7d0. No full, cada tema so e composto se o tile dele
#   falta (ou --overwrite), entao rodar com todos os temas faz so os novos:
#   python "<projeto>\scripts\08_compose_hybrid.py" --mode full --themes soil_diversity lithology_diversity

import argparse
import csv
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import gaussian_filter, shift as nd_shift

Image.MAX_IMAGE_PIXELS = None

# caminhos e constantes --------------------------------------------------------

PROJECT = Path(__file__).resolve().parents[1]
DIR_INT = PROJECT / "data" / "intermediate"
STYLE = "h128_8_s2000_az315_el45_ang90_ctx5000_fd1"
DIR_RENDER = DIR_INT / "07_hybrid_renders" / STYLE
DIR_03 = DIR_INT / "03_thematic"
DEM = DIR_INT / "02_prepared_dem" / "raster" / "gedtm30_v1_2_brazil_5880_30m.tif"
BLOCKS = DIR_INT / "02_prepared_dem" / "tables" / "heightmap_blocks.csv"
DIR_OUT = DIR_INT / "08_compose"
DIR_FINAL = PROJECT / "data" / "final"

BP, NB, RES = 8192, 18, 30.0           # px do nucleo, blocos por lado, m
XMIN, YMAX = 2744310.0, 10637160.0     # canto do canvas (EPSG:5880)
RED = 16                               # 30 m -> 480 m
STRIP = 1024                           # linhas por faixa dentro do bloco

F = 0.7347676813916229                 # sombra do plano (rodada 2)
ALBEDO = 0.6                           # cinza do material do 07
CURVE = 1.6                            # dramatica
BASE_POW, K_GAMMA = 1.3, 0.7           # equilibrada

PAPER, NODATA = "eeede9", "dfe8ee"
SHADOW_SHIFT_M = (46080.0, 53760.0)    # (para baixo, para a direita) = 24 x 28 px de 1920 m
SHADOW_SIGMA_M = 38400.0               # 20 px de 1920 m
SHADOW_ALPHA = 0.28

Z_BREAKS = [0, 20, 100, 200, 300, 500, 700, 900, 1200, 1600, 3000]
Z_COLORS = ["1f8fa0", "1e9a5a", "2ea043", "6db34a", "b5b85c", "d9c37a",
            "d39a4f", "b9643a", "93391f", "6e2416", "4c1a10"]

THEMES = ("hypsometry", "geology", "soil_orders", "soil_diversity", "lithology_diversity")
THEME_LABEL = {"hypsometry": "hipsometria", "geology": "geologia (cores do Lamego, 1960)",
               "soil_orders": "solos, ordens do SiBCS 2025",
               "soil_diversity": "diversidade pedológica (componentes por unidade)",
               "lithology_diversity": "diversidade litológica (litologias por unidade)"}
# raster de classe do 03 e coluna de cor da tabela de classes de cada tema
# (a hipsometria sai do DEM)
CLASS_SRC = {"geology": ("geology", "color"), "soil_orders": ("soil", "color_order"),
             "soil_diversity": ("soil_diversity", "color"),
             "lithology_diversity": ("lithology_diversity", "color")}
DIV_NODATA = "d9d7d0"                  # sem unidade nos temas de diversidade (log 25)
PRES = ("dramatic", "balanced")       # nomes de arquivo (log 24); rotulos em portugues
PRES_LABEL = {"dramatic": "dramática: cor × sombreado + curva 1,6",
              "balanced": "equilibrada: cor^1,3, sombreado com gama 0,7"}

# janelas de 30,72 km a 30 m (centros da rodada 2; Chapada nao teve 30 m la)
WINDOWS = [("mantiqueira", "Itatiaia / Mantiqueira", 5960280.0, 7494360.0),
           ("amazonia", "Amazônia central (Borba)", 4379520.0, 9512280.0),
           ("aparados", "Aparados da Serra", 5381280.0, 6765480.0),
           ("chapada", "Chapada Diamantina", 6368520.0, 8573760.0)]
WIN_PX = 1024
PILOT_BLOCKS = ["r11_c12", "r11_c13", "r12_c12", "r12_c13"]


def parse_args():
    ap = argparse.ArgumentParser(prog="08_compose_hybrid.py")
    ap.add_argument("--mode", choices=["preview", "full"], default="preview")
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--blocks", nargs="*", default=None)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--presentation", choices=list(PRES), default="balanced")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--themes", nargs="+", choices=list(THEMES), default=list(THEMES))
    a = ap.parse_args()
    a.themes = tuple(t for t in THEMES if t in a.themes)   # ordem fixa
    return a


# cores --------------------------------------------------------------------------

def hx(s):
    return np.array(tuple(bytes.fromhex(s.lstrip("#"))), dtype=np.float64) / 255


_M = np.array([[.4124564, .3575761, .1804375], [.2126729, .7151522, .072175],
               [.0193339, .119192, .9503041]])
_WHITE, _DELTA = np.array([.95047, 1, 1.08883]), 6 / 29


def _tolab(rgb):
    lin = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
    x = lin @ _M.T / _WHITE
    f = np.where(x > _DELTA ** 3, np.cbrt(x), x / (3 * _DELTA ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def _fromlab(lab):
    fy = (lab[..., 0] + 16) / 116
    f = np.stack([fy + lab[..., 1] / 500, fy, fy - lab[..., 2] / 200], -1)
    x = np.where(f > _DELTA, f ** 3, 3 * _DELTA ** 2 * (f - 4 / 29)) * _WHITE
    lin = x @ np.linalg.inv(_M).T
    return np.clip(np.where(lin <= .0031308, 12.92 * lin, 1.055 * np.maximum(lin, 0) ** (1 / 2.4) - .055), 0, 1)


def hypso_lut():
    # rampa da rodada 2 e do 05, interpolada em Lab, 1 entrada por metro (0-3000)
    lab0 = _tolab(np.array([hx(c) for c in Z_COLORS]))
    z = np.arange(3001, dtype=np.float64)
    lab = np.stack([np.interp(z, Z_BREAKS, lab0[:, j]) for j in range(3)], -1)
    return np.uint8(_fromlab(lab) * 255 + .5)


def class_lut(file, field, nodata=NODATA):
    lut = np.tile(np.uint8(hx(nodata) * 255 + .5), (256, 1))
    with open(DIR_03 / "tables" / f"{file}_classes.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f, delimiter=";"):
            lut[int(r["class_id"])] = np.uint8(hx(r[field]) * 255 + .5)
    return lut


def luts(themes=THEMES):
    out = {}
    for th in themes:
        if th == "hypsometry":
            out[th] = hypso_lut()
        else:
            file, field = CLASS_SRC[th]
            out[th] = class_lut(file, field, DIV_NODATA if th.endswith("_diversity") else NODATA)
    return out


def srgb_to_lin(c):
    return np.where(c <= .04045, c / 12.92, ((c + .055) / 1.055) ** 2.4)


def lin_to_srgb(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= .0031308, 12.92 * x, 1.055 * x ** (1 / 2.4) - .055)


def dramatic(c, g):
    # c: cor (..., 3) em 0-1 (sRGB); g: cinza do 07 (...) em 0-1 (saida Standard)
    return lin_to_srgb(srgb_to_lin(c) * (srgb_to_lin(g) / ALBEDO)[..., None]) ** CURVE


def balanced(c, g):
    base = c ** BASE_POW
    k = (g / F) ** K_GAMMA
    return np.clip(base * np.minimum(k, 1)[..., None]
                   + (1 - base) * (np.maximum(k - 1, 0) / ((1 / F) ** K_GAMMA - 1))[..., None], 0, 1)


PRES_FUN = {"dramatic": dramatic, "balanced": balanced}

# as mesmas contas por tabela (o bloco tem 67 Mpx x 3 temas x 2): cor de 8
# bits -> linear e -> ^1,3 em 256 entradas; o cinza entra uma vez por faixa;
# a saida da dramatica (oetf e ^1,6) numa tabela de 65.536 valores lineares
# (erro < 0,05 nivel). tools/check_08_formulas.py confere contra as funcoes
# de referencia acima
_I8 = np.arange(256, dtype=np.float64) / 255
LIN8 = srgb_to_lin(_I8).astype(np.float32)
POW8 = (_I8 ** BASE_POW).astype(np.float32)
DRAM_OUT = (lin_to_srgb(np.arange(65536, dtype=np.float64) / 65535) ** CURVE).astype(np.float32)
K_DEN = (1 / F) ** K_GAMMA - 1


def shade_terms(g):
    return {"glin": (srgb_to_lin(g) / ALBEDO).astype(np.float32),
            "k": ((g / F) ** K_GAMMA).astype(np.float32)}


def present_fast(c8, t, p):
    # c8: cor uint8 (..., 3); t: shade_terms do cinza; p: apresentacao
    if p == "dramatic":
        x = LIN8[c8] * t["glin"][..., None]
        return DRAM_OUT[(np.clip(x, 0, 1) * 65535 + .5).astype(np.int32)]
    base, k = POW8[c8], t["k"][..., None]
    return np.clip(base * np.minimum(k, 1) + (1 - base) * (np.maximum(k - 1, 0) / K_DEN), 0, 1)


def clean_z(z):
    return np.where(np.isfinite(z) & (z >= 0) & (z <= 7000), z, 0)


def theme_colors(lut, z, cls, themes):
    # cls: raster de classe do 03 por nome (geology, soil, ...); z: DEM limpo
    out = {}
    for th in themes:
        if th == "hypsometry":
            out[th] = lut[th][np.clip(np.round(z), 0, 3000).astype(np.int32)]
        else:
            out[th] = lut[th][cls[CLASS_SRC[th][0]]]
    return out


# um bloco -----------------------------------------------------------------------

def read_tif(path):
    with rasterio.open(path) as d:
        return d.read(1)


def read_classes(bid, themes):
    # so os rasters de classe que os temas pedidos usam
    names = {CLASS_SRC[th][0] for th in themes if th in CLASS_SRC}
    return {n: read_tif(DIR_03 / "raster" / n / f"{n}_{bid}.tif") for n in names}


def slice_cls(cls, sl):
    return {k: v[sl] for k, v in cls.items()}


def compose_block(b, lut, themes=THEMES):
    t0 = time.time()
    bid, row, col = b["block_id"], b["row"], b["col"]
    g16 = np.asarray(Image.open(DIR_RENDER / f"relief_{bid}.png"))
    with rasterio.open(DEM) as d:
        z = d.read(1, window=Window(col * BP, row * BP, BP, BP))
    cls = read_classes(bid, themes)
    ctry = read_tif(DIR_03 / "raster" / "country" / f"country_{bid}.tif")

    n = BP // RED
    out = {(th, p): np.zeros((n, n, 3), np.float32) for th in themes for p in PRES}
    frac = np.zeros((n, n), np.float32)
    hist_br = np.zeros(256, np.int64)       # cinza dentro do Brasil
    hist_sea = np.zeros(256, np.int64)      # cinza no mar (plano em 0 m)
    for r0 in range(0, BP, STRIP):
        r1 = r0 + STRIP
        g = g16[r0:r1].astype(np.float32) / 65535
        zz = clean_z(z[r0:r1])
        br = (ctry[r0:r1] == 1)
        sea = (ctry[r0:r1] == 0) & (zz == 0)
        g8 = np.round(g * 255).astype(np.int64)
        hist_br += np.bincount(g8[br], minlength=256)
        hist_sea += np.bincount(g8[sea], minlength=256)
        w = br.astype(np.float32)
        den = w.reshape(STRIP // RED, RED, n, RED).sum(axis=(1, 3))
        frac[r0 // RED:r1 // RED] = den / RED ** 2
        cols = theme_colors(lut, zz, slice_cls(cls, slice(r0, r1)), themes)
        t = shade_terms(g)
        for th in themes:
            for p in PRES:
                rgb = present_fast(cols[th], t, p) * w[..., None]
                num = rgb.reshape(STRIP // RED, RED, n, RED, 3).sum(axis=(1, 3))
                out[(th, p)][r0 // RED:r1 // RED] = np.where(den[..., None] > 0, num / np.maximum(den, 1)[..., None], 0)

    # janelas de 30 m dentro deste bloco
    wins = {}
    bx0, by1 = XMIN + col * BP * RES, YMAX - row * BP * RES
    for wid, _, cx, cy in WINDOWS:
        c0 = int(round((cx - WIN_PX * RES / 2 - bx0) / RES))
        r0 = int(round((by1 - (cy + WIN_PX * RES / 2)) / RES))
        if 0 <= c0 and c0 + WIN_PX <= BP and 0 <= r0 and r0 + WIN_PX <= BP:
            sl = (slice(r0, r0 + WIN_PX), slice(c0, c0 + WIN_PX))
            t = shade_terms(g16[sl].astype(np.float32) / 65535)
            cols = theme_colors(lut, clean_z(z[sl]), slice_cls(cls, sl), themes)
            br = ctry[sl] == 1
            for th in themes:
                for p in PRES:
                    rgb = present_fast(cols[th], t, p)
                    rgb[~br] = hx(PAPER)
                    wins[(wid, th, p)] = np.uint8(np.clip(rgb, 0, 1) * 255 + .5)
    res = {k: np.uint8(np.clip(v, 0, 1) * 255 + .5) for k, v in out.items()}
    return dict(block=b, out=res, frac=frac, wins=wins, hist_br=hist_br, hist_sea=hist_sea,
                seconds=time.time() - t0)


# saida -------------------------------------------------------------------------------

def font(n):
    try:
        return ImageFont.truetype("C:/Windows/Fonts/arial.ttf", n)
    except OSError:
        return ImageFont.load_default()


def hist_median(h):
    if h.sum() == 0:
        return float("nan")
    c = np.cumsum(h)
    return float(np.searchsorted(c, c[-1] / 2)) / 255


def shadow_field(m, px):
    # sombra projetada do Brasil (0-SHADOW_ALPHA) a partir da fracao de Brasil
    # m numa grade de px metros; a rodada 2 fez a 1920 m
    sh = nd_shift(m, (SHADOW_SHIFT_M[0] / px, SHADOW_SHIFT_M[1] / px), order=1, mode="constant", cval=0)
    return (gaussian_filter(sh, SHADOW_SIGMA_M / px) * SHADOW_ALPHA).astype(np.float32)


def shadow_background(mask_frac):
    # papel com a sombra, calculada a 1920 m como na rodada 2 e ampliada
    n = mask_frac.shape[0]
    k = 4 if n % 4 == 0 else 1
    m = mask_frac.reshape(n // k, k, n // k, k).mean(axis=(1, 3))
    sh = shadow_field(m, RES * RED * k)
    sh = np.asarray(Image.fromarray(sh).resize((n, n), Image.BILINEAR))
    return (hx(PAPER)[None, None, :] * (1 - sh[..., None])).astype(np.float32)


# producao a 30 m (--mode full) --------------------------------------------------------

SH_PX = 64                              # 30 m -> 1920 m (grade da sombra)


def brazil_frac_1920(b):
    # fracao de Brasil de um bloco na grade de 1920 m (128 x 128)
    c = read_tif(DIR_03 / "raster" / "country" / f"country_{b['block_id']}.tif") == 1
    n = BP // SH_PX
    return b, c.reshape(n, SH_PX, n, SH_PX).mean(axis=(1, 3)).astype(np.float32)


def _lin_idx(start, n, size):
    # pesos da interpolacao bilinear de pixels de 30 m numa grade 64x mais grossa
    f = (np.arange(start, start + n) + 0.5) / SH_PX - 0.5
    i = np.floor(f).astype(np.int64)
    w = (f - i).astype(np.float32)
    return np.clip(i, 0, size - 1), np.clip(i + 1, 0, size - 1), w


def shadow_strip(field, row0, col0, nrows, ncols):
    # sombra a 30 m (bilinear) para linhas row0.. e colunas col0.. do canvas
    n = field.shape[0]
    r0, r1, wr = _lin_idx(row0, nrows, n)
    c0, c1, wc = _lin_idx(col0, ncols, n)
    a = field[r0][:, c0] * (1 - wc) + field[r0][:, c1] * wc
    b = field[r1][:, c0] * (1 - wc) + field[r1][:, c1] * wc
    return a * (1 - wr)[:, None] + b * wr[:, None]


def full_paths(out_dir, th, pres, bid):
    return out_dir / f"{th}_{pres}" / f"tile_{bid}.tif"


def write_tile(path, rgb, bid, row, col):
    from rasterio.crs import CRS
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.tif")
    prof = dict(driver="GTiff", width=BP, height=BP, count=3, dtype="uint8",
                crs=CRS.from_epsg(5880), transform=from_origin(XMIN + col * BP * RES, YMAX - row * BP * RES, RES, RES),
                tiled=True, blockxsize=512, blockysize=512, compress="deflate", predictor=2,
                photometric="RGB", interleave="pixel")
    with rasterio.open(tmp, "w", **prof) as d:
        d.write(np.moveaxis(rgb, -1, 0))
        d.build_overviews([2, 4, 8, 16, 32, 64], Resampling.average)
        d.update_tags(block_id=bid, source="08_compose_hybrid.py")
    tmp.replace(path)                    # so aparece inteiro


def compose_block_full(b, lut, field, pres, out_dir, overwrite, themes=THEMES):
    t0 = time.time()
    bid, row, col = b["block_id"], b["row"], b["col"]
    paths = {th: full_paths(out_dir, th, pres, bid) for th in themes}
    # so os temas cujo tile falta (log 25: os de diversidade entraram depois)
    todo = [th for th in themes if overwrite or not paths[th].exists()]
    if not todo:
        return dict(block_id=bid, status="ja_existe", seconds=0.0, frac_brasil=float("nan"))
    paper = hx(PAPER).astype(np.float32)
    tiles = {th: np.empty((BP, BP, 3), np.uint8) for th in todo}
    n_br = 0
    if b["has_brazil"]:
        g16 = np.asarray(Image.open(DIR_RENDER / f"relief_{bid}.png"))
        with rasterio.open(DEM) as d:
            z = d.read(1, window=Window(col * BP, row * BP, BP, BP))
        cls = read_classes(bid, todo)
        ctry = read_tif(DIR_03 / "raster" / "country" / f"country_{bid}.tif")
    for r0 in range(0, BP, STRIP):
        r1 = r0 + STRIP
        sh = shadow_strip(field, row * BP + r0, col * BP, STRIP, BP)
        bg = paper[None, None, :] * (1 - sh[..., None])
        if not b["has_brazil"]:
            bg8 = np.uint8(np.clip(bg, 0, 1) * 255 + .5)
            for th in todo:
                tiles[th][r0:r1] = bg8
            continue
        br = ctry[r0:r1] == 1
        n_br += int(br.sum())
        t = shade_terms(g16[r0:r1].astype(np.float32) / 65535)
        cols = theme_colors(lut, clean_z(z[r0:r1]), slice_cls(cls, slice(r0, r1)), todo)
        for th in todo:
            rgb = np.where(br[..., None], present_fast(cols[th], t, pres), bg)
            tiles[th][r0:r1] = np.uint8(np.clip(rgb, 0, 1) * 255 + .5)
    for th in todo:
        write_tile(paths[th], tiles[th], bid, row, col)
    return dict(block_id=bid, status="ok " + "+".join(todo), seconds=time.time() - t0,
                frac_brasil=n_br / BP ** 2)


OV_FACTORS = (2, 4, 8, 16, 32, 64)      # overviews internas dos tiles


def write_vrt(path, tile_dir, rows, cols, level=None, overviews=()):
    # mosaico dos blocos. level = i le a overview interna i dos tiles (opcao de
    # abertura OVERVIEW_LEVEL, GDAL >= 2.1); overviews = VRTs de overview que
    # o VRT principal declara (sem isso o GDAL/QGIS le os 30 m em todo zoom).
    # Caminhos relativos ao proprio VRT
    import os
    from rasterio.crs import CRS
    from xml.sax.saxutils import escape
    f = 1 if level is None else OV_FACTORS[level]
    t = BP // f
    r_min, r_max, c_min, c_max = min(rows), max(rows), min(cols), max(cols)
    nx, ny = (c_max - c_min + 1) * t, (r_max - r_min + 1) * t
    x0, y0 = XMIN + c_min * BP * RES, YMAX - r_min * BP * RES
    rel = Path(os.path.relpath(tile_dir, path.parent)).as_posix()
    lines = [f'<VRTDataset rasterXSize="{nx}" rasterYSize="{ny}">',
             f"  <SRS>{escape(CRS.from_epsg(5880).to_wkt())}</SRS>",
             f"  <GeoTransform>{x0:.1f}, {RES * f:.1f}, 0.0, {y0:.1f}, 0.0, {-RES * f:.1f}</GeoTransform>"]
    for band, ci in enumerate(("Red", "Green", "Blue"), 1):
        lines.append(f'  <VRTRasterBand dataType="Byte" band="{band}">')
        lines.append(f"    <ColorInterp>{ci}</ColorInterp>")
        for ov in overviews:
            orel = Path(os.path.relpath(ov, path.parent)).as_posix()
            lines.append(f'    <Overview><SourceFilename relativeToVRT="1">{orel}</SourceFilename>'
                         f"<SourceBand>{band}</SourceBand></Overview>")
        for r in range(r_min, r_max + 1):
            for c in range(c_min, c_max + 1):
                tif = tile_dir / f"tile_r{r:02d}_c{c:02d}.tif"
                if not tif.exists():
                    continue
                lines += ["    <SimpleSource>",
                          f'      <SourceFilename relativeToVRT="1">{rel}/{tif.name}</SourceFilename>']
                if level is not None:
                    lines.append(f'      <OpenOptions><OOI key="OVERVIEW_LEVEL">{level}</OOI></OpenOptions>')
                lines += [f"      <SourceBand>{band}</SourceBand>",
                          f'      <SourceProperties RasterXSize="{t}" RasterYSize="{t}" DataType="Byte" BlockXSize="512" BlockYSize="512"/>',
                          f'      <SrcRect xOff="0" yOff="0" xSize="{t}" ySize="{t}"/>',
                          f'      <DstRect xOff="{(c - c_min) * t}" yOff="{(r - r_min) * t}" xSize="{t}" ySize="{t}"/>',
                          "    </SimpleSource>"]
        lines.append("  </VRTRasterBand>")
    lines.append("</VRTDataset>")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_vrt_set(out_dir, th, pres, rows, cols):
    # VRT de 30 m + um VRT por overview (vrt_overviews/), declarados no principal
    tile_dir = out_dir / f"{th}_{pres}"
    ov_dir = out_dir / "vrt_overviews"
    ov_dir.mkdir(exist_ok=True)
    ovs = []
    for i, f in enumerate(OV_FACTORS):
        p = ov_dir / f"brazil_{th}_{pres}_{int(RES * f)}m.vrt"
        write_vrt(p, tile_dir, rows, cols, level=i)
        ovs.append(p)
    write_vrt(out_dir / f"brazil_{th}_{pres}_30m.vrt", tile_dir, rows, cols, overviews=ovs)


def main_full(args, blocks):
    want = PILOT_BLOCKS if args.pilot else args.blocks
    todo = [b for b in blocks if not want or b["block_id"] in set(want)]
    missing = [b["block_id"] for b in todo if b["has_brazil"]
               and not (DIR_RENDER / f"relief_{b['block_id']}.png").exists()]
    if missing:
        raise SystemExit(f"faltam renders do 07: {missing[:5]} ... ({len(missing)})")
    out_dir = DIR_FINAL / ("30m_pilot" if args.pilot else "30m")
    (out_dir / "tables").mkdir(parents=True, exist_ok=True)
    themes = args.themes
    lut, pres = luts(themes), args.presentation
    print(f"\n# 08 compose full {'-' * 58}")
    print(f"apresentacao {pres}; temas {', '.join(themes)}; {len(todo)} blocos "
          f"({sum(b['has_brazil'] for b in todo)} com Brasil), {args.workers} processos; saida em {out_dir}")

    # sombra projetada: fracao de Brasil de todos os blocos a 1920 m -------------
    t0 = time.time()
    n = NB * BP // SH_PX
    frac = np.zeros((n, n), np.float32)
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for b, fr in ex.map(brazil_frac_1920, [b for b in blocks if b["has_brazil"]]):
            k = BP // SH_PX
            frac[b["row"] * k:(b["row"] + 1) * k, b["col"] * k:(b["col"] + 1) * k] = fr
    field = shadow_field(frac, RES * SH_PX)
    print(f"sombra projetada a 1920 m pronta em {time.time() - t0:.0f} s (max {field.max():.3f})")

    rows_tab = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(compose_block_full, b, lut, field, pres, out_dir, args.overwrite, themes)
                for b in todo]
        for i, fu in enumerate(as_completed(futs), 1):
            r = fu.result()
            rows_tab.append(r)
            el = time.time() - t0
            print(f"[{i}/{len(todo)}] {r['block_id']}: {r['status']} {r['seconds']:.0f} s | "
                  f"falta ~{el / i * (len(todo) - i) / 60:.1f} min", flush=True)
    rows_tab.sort(key=lambda x: x["block_id"])
    write_csv(out_dir / "tables" / "full_blocks.csv", rows_tab)

    rr, cc = [b["row"] for b in todo], [b["col"] for b in todo]
    for th in themes:
        write_vrt_set(out_dir, th, pres, rr, cc)
        # conferencia rapida: a overview de 1/64 de cada bloco (1920 m)
        k = BP // 64
        img = np.zeros(((max(rr) - min(rr) + 1) * k, (max(cc) - min(cc) + 1) * k, 3), np.uint8)
        for b in todo:
            with rasterio.open(full_paths(out_dir, th, pres, b["block_id"]), overview_level=5) as d:
                ov = np.moveaxis(d.read(), 0, -1)
            img[(b["row"] - min(rr)) * k:(b["row"] - min(rr) + 1) * k,
                (b["col"] - min(cc)) * k:(b["col"] - min(cc) + 1) * k] = ov
        Image.fromarray(img).save(out_dir / f"brazil_{th}_{pres}_1920m.jpg", quality=92)
    n_ok = sum(r["status"].startswith("ok") for r in rows_tab)
    print(f"\nblocos gravados: {n_ok}, ja existiam: {len(rows_tab) - n_ok}; VRT e conferencia de 1920 m por tema")
    print(f"fim em {(time.time() - t0) / 60:.1f} min; saida em {out_dir}")


def write_csv(path, rows):
    keys = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(keys)
        for r in rows:
            w.writerow([f"{r[k]:.4f}".replace(".", ",") if isinstance(r[k], float) else r[k] for k in keys])


def main():
    args = parse_args()
    with open(BLOCKS, encoding="utf-8-sig") as f:
        blocks = list(csv.DictReader(f, delimiter=";"))
    for b in blocks:
        b["row"], b["col"] = int(b["row"]), int(b["col"])
        b["has_brazil"] = str(b["has_brazil"]).upper() == "TRUE"
    if args.mode == "full":
        return main_full(args, blocks)
    want = PILOT_BLOCKS if args.pilot else args.blocks
    todo = [b for b in blocks if b["has_brazil"] and (not want or b["block_id"] in set(want))]
    missing = [b["block_id"] for b in todo if not (DIR_RENDER / f"relief_{b['block_id']}.png").exists()]
    if missing:
        raise SystemExit(f"faltam renders do 07: {missing[:5]} ... ({len(missing)})")
    out_dir = DIR_OUT / ("preview_pilot" if args.pilot else "preview")
    (out_dir / "tables").mkdir(parents=True, exist_ok=True)
    themes = args.themes
    lut = luts(themes)

    print(f"\n# 08 compose {'-' * 63}")
    print(f"modo {args.mode}: {len(todo)} blocos, {args.workers} processos; saida em {out_dir}")
    print(f"dramatica: oetf(lin(C) x lin(cinza) / {ALBEDO:g})^{CURVE:g} | "
          f"equilibrada: C^{BASE_POW:g}, (cinza/F)^{K_GAMMA:g}, F = {F:.4f}")

    n = NB * BP // RED
    mos = {k: np.zeros((n, n, 3), np.uint8) for k in [(th, p) for th in themes for p in PRES]}
    frac = np.zeros((n, n), np.float32)
    wins, rows_tab = {}, []
    hist_br, hist_sea = np.zeros(256, np.int64), np.zeros(256, np.int64)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(compose_block, b, lut, themes) for b in todo]
        for i, fu in enumerate(as_completed(futs), 1):
            r = fu.result()
            b = r["block"]
            sl = (slice(b["row"] * BP // RED, (b["row"] + 1) * BP // RED),
                  slice(b["col"] * BP // RED, (b["col"] + 1) * BP // RED))
            for k, v in r["out"].items():
                mos[k][sl] = v
            frac[sl] = r["frac"]
            wins.update(r["wins"])
            hist_br += r["hist_br"]
            hist_sea += r["hist_sea"]
            rows_tab.append({"block_id": b["block_id"], "seconds": r["seconds"],
                             "frac_brasil": float(r["frac"].mean()),
                             "cinza_mediano_brasil": hist_median(r["hist_br"]),
                             "cinza_mediano_mar": hist_median(r["hist_sea"])})
            el = time.time() - t0
            print(f"[{i}/{len(todo)}] {b['block_id']}: {r['seconds']:.0f} s | "
                  f"falta ~{el / i * (len(todo) - i) / 60:.1f} min", flush=True)

    rows_tab.sort(key=lambda x: x["block_id"])
    write_csv(out_dir / "tables" / "preview_blocks.csv", rows_tab)

    # recorte (piloto ou --blocks) ou Brasil inteiro
    rr = [b["row"] for b in todo]
    cc = [b["col"] for b in todo]
    crop = (slice(min(rr) * BP // RED, (max(rr) + 1) * BP // RED),
            slice(min(cc) * BP // RED, (max(cc) + 1) * BP // RED)) if want else (slice(None), slice(None))
    fr = frac[crop]
    if fr.shape[0] != fr.shape[1]:
        raise SystemExit("recorte nao quadrado: use blocos que formem um quadrado")
    bg = shadow_background(fr)
    alpha = fr[..., None]
    finals = {}
    for (th, p), m in mos.items():
        rgb = m[crop].astype(np.float32) / 255
        img = np.uint8(np.clip(alpha * rgb + (1 - alpha) * bg, 0, 1) * 255 + .5)
        finals[(th, p)] = Image.fromarray(img)
        finals[(th, p)].save(out_dir / f"brazil_{th}_{p}_480m.jpg", quality=92)

    # folhas -------------------------------------------------------------------
    side = 1800
    for th in themes:
        sheet = Image.new("RGB", (2 * side + 60, side + 130), "#eeede9")
        d = ImageDraw.Draw(sheet)
        d.text((20, 12), f"Brasil | {THEME_LABEL[th]} | terreno híbrido 30 m (macro E128, detalhe E8), reduzido para a tela",
               font=font(30), fill="#222222")
        for j, p in enumerate(PRES):
            sheet.paste(finals[(th, p)].resize((side, side), Image.LANCZOS), (20 + j * (side + 20), 110))
            d.text((20 + j * (side + 20), 66), PRES_LABEL[p], font=font(28), fill="#222222")
        sheet.save(out_dir / f"compare_{th}.jpg", quality=93)

    got = [w for w in WINDOWS if all((w[0], th, p) in wins for th in themes for p in PRES)]
    for th in themes:
        if not got:
            break
        sheet = Image.new("RGB", (2 * WIN_PX + 60, len(got) * (WIN_PX + 60) + 110), "#eeede9")
        d = ImageDraw.Draw(sheet)
        d.text((20, 12), f"{THEME_LABEL[th]} | janelas de 30,72 km a 30 m (1 px = 30 m)", font=font(30), fill="#222222")
        for j, p in enumerate(PRES):
            d.text((20 + j * (WIN_PX + 20), 60), PRES_LABEL[p], font=font(26), fill="#222222")
        for i, (wid, wlabel, _, _) in enumerate(got):
            y = 110 + i * (WIN_PX + 60)
            d.text((20, y), wlabel, font=font(26), fill="#222222")
            for j, p in enumerate(PRES):
                sheet.paste(Image.fromarray(wins[(wid, th, p)]), (20 + j * (WIN_PX + 20), y + 40))
        sheet.save(out_dir / f"regions_{th}.jpg", quality=93)

    gm_br, gm_sea = hist_median(hist_br), hist_median(hist_sea)
    print(f"\ncinza mediano: Brasil {gm_br:.3f} | mar (plano em 0 m) {gm_sea:.3f} | F da equilibrada {F:.3f}")
    print(f"janelas a 30 m: {', '.join(w[0] for w in got) if got else 'nenhuma neste recorte'}")
    print(f"fim em {(time.time() - t0) / 60:.1f} min; saida em {out_dir}")


if __name__ == "__main__":
    main()
