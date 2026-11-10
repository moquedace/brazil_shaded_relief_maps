# check_08_formulas.py -------------------------------------------------------
# confere o 08 contra os arquivos da rodada 2 nas 3 janelas de 30 m dela
# (Mantiqueira, Amazonia, Aparados), so le:
#   1. cores: as do 08 (DEM + classes do 03) x {janela}_core_{tema}30.png
#   2. dramatica: formula do 08 sobre o cinza e as cores da rodada 2 x render
#      colorido do Blender da rodada 2 (hybrid30_{tema}_direct) ^1,6
#   3. equilibrada: formula do 08 x NATIVO30_{janela}_{tema}.png da rodada 2
#   4. as contas por tabela do 08 (present_fast) x as funcoes de referencia
# niveis de 8 bits. Escrito em 10/11/2026 (log 18); so os 3 temas da rodada 2
# (o 08 ganhou os de diversidade no log 25)

import importlib.util
import json
import os
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import from_bounds
from PIL import Image

PROJ = Path(r"D:\usuario_armazenamento\cassio\projects\brazil_shaded_relief_maps")
# pasta da rodada 2 (referencia local, fora do repositorio): BRAZIL_ROUND2_DIR
R2 = Path(os.environ["BRAZIL_ROUND2_DIR"])
W, O = R2 / "work" / "round2", R2 / "outputs" / "round2"

spec = importlib.util.spec_from_file_location("compose08", PROJ / "scripts" / "08_compose_hybrid.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
R2_THEMES = ("hypsometry", "geology", "soil_orders")   # os da rodada 2
lut = m.luts(R2_THEMES)


def read01(p):
    with rasterio.open(p) as d:
        a = d.read().transpose(1, 2, 0).astype(np.float32)
        return a / (65535 if d.dtypes[0] == "uint16" else 255)


meta = json.loads((W / "window_metadata.json").read_text())
I = PROJ / "data" / "intermediate"
for site in ["mantiqueira", "amazonia", "aparados"]:
    x, y = meta[site]["center"]
    b = [x - 15360, y - 15360, x + 15360, y + 15360]
    with rasterio.open(I / "02_prepared_dem/raster/gedtm30_v1_2_brazil_5880_30m.tif") as d:
        z = d.read(1, window=from_bounds(*b, d.transform), out_shape=(1024, 1024))
    cls = {}
    for f in ("geology", "soil"):
        with rasterio.open(I / f"03_thematic/raster/{f}.vrt") as d:
            cls[f] = d.read(1, window=from_bounds(*b, d.transform), out_shape=(1024, 1024))
    mine = m.theme_colors(lut, m.clean_z(z), cls, R2_THEMES)
    g = read01(W / f"{site}_hybrid30_gray.png")[..., 0]
    t = m.shade_terms(g)
    for th in R2_THEMES:
        c8 = np.asarray(Image.open(W / f"{site}_core_{th}30.png").convert("RGB"))
        dc = np.abs(mine[th].astype(int) - c8.astype(int))
        c = c8.astype(np.float32) / 255
        d_ref = m.dramatic(c, g)
        d_r2 = read01(W / f"{site}_hybrid30_{th}_direct.png")[..., :3] ** 1.6
        b_ref = m.balanced(c, g)
        b_r2 = read01(O / f"NATIVO30_{site}_{th}.png")[..., :3]
        fd = np.abs(m.present_fast(c8, t, "dramatic") - d_ref).max() * 255
        fb = np.abs(m.present_fast(c8, t, "balanced") - b_ref).max() * 255
        print(f"{site:11s} {th:11s} cor: MAE {dc.mean():.2f}, iguais {100 * (dc.max(-1) == 0).mean():.1f}% | "
              f"dramatica x Blender^1,6: MAE {np.abs(d_ref - d_r2).mean() * 255:.2f} vies {(d_ref - d_r2).mean() * 255:+.2f} | "
              f"equilibrada x NATIVO30: MAE {np.abs(b_ref - b_r2).mean() * 255:.2f} | tabela x ref: {fd:.3f} / {fb:.3f}")
