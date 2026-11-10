# brazil_shaded_relief_maps - 09 layout final dos mapas ----------------------
#
# ATENCAO (10/11/2026, log 21): a folha deste script foi substituida pelo
# atlas (scripts 10 e 11). Daqui seguem em uso map_image (recorte,
# leitura do VRT e papel/sombra refeitos alem do canvas) e brazil_frac_480,
# importados pelo 10 e pelo 11; nao mudar a assinatura dessas funcoes
#
# Python 3.13 (numpy, rasterio, Pillow). PowerShell:
#   python "<projeto>\scripts\09_layout_maps.py" --draft     (3 temas a 100 dpi, ~2 min)
#   python "<projeto>\scripts\09_layout_maps.py"             (3 temas, A0 a 300 dpi)
#   python "<projeto>\scripts\09_layout_maps.py" --theme geology
#
# monta a folha de cada tema (log 20) a partir do produto de 30 m do 08
# (data/final/30m/brazil_<tema>_balanced_30m.vrt, lido na overview de
# 240 m e reduzido com Lanczos para o tamanho da folha):
#   folha  A0 deitado (1189 x 841 mm), 300 dpi, papel #eeede9 (o mesmo do
#          fundo do mapa, entao o mapa nao tem moldura)
#   mapa   recorte do Brasil + a sombra projetada, o maior que couber a
#          esquerda; graticula de 5 graus so fora do Brasil, com rotulos na
#          margem
#   painel titulo, legenda (cores de area plana da apresentacao
#          equilibrada = cor^1,3), barra de escala (verdadeira ao longo dos
#          paralelos na policonica), escala nominal na folha impressa,
#          fontes e metodo, autoria
# textos em TEXTS e NOTES abaixo, para editar sem mexer no resto
#
# saida: data/final/layout/brazil_<tema>_a0.png (300 dpi), .pdf e
#   _preview.jpg (2400 px); --draft grava em data/final/layout/draft/
# opcoes: --theme hypsometry|geology|soil_orders|all  --draft  --out <pasta>

import argparse
import csv
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import transform as warp_transform
from rasterio.windows import Window
from PIL import Image, ImageDraw, ImageFont

Image.MAX_IMAGE_PIXELS = None

# caminhos e constantes ------------------------------------------------------------

PROJECT = Path(__file__).resolve().parents[1]
DIR_INT = PROJECT / "data" / "intermediate"
DIR_30M = PROJECT / "data" / "final" / "30m"
DIR_LAYOUT = PROJECT / "data" / "final" / "layout"
DIR_03 = DIR_INT / "03_thematic"
BLOCKS = DIR_INT / "02_prepared_dem" / "tables" / "heightmap_blocks.csv"

BP, NB, RES = 8192, 18, 30.0
XMIN, YMAX = 2744310.0, 10637160.0
PRES = "balanced"                       # = equilibrada (log 24)
BASE_POW = 1.3                         # cor de area plana na equilibrada

PAGE_MM = (1189.0, 841.0)              # A0 deitado
MARGIN_MM = 25.0
GAP_MM = 12.0                          # entre o mapa e o painel
PANEL_MM = 300.0                       # largura do painel da direita
PAD_KM = (60.0, 60.0, 190.0, 190.0)    # recorte alem do Brasil: oeste, norte, leste, sul (sombra a SE)
GRAT_DEG = 5
SCALE_KM = (0, 100, 200, 300, 400, 500)

PAPER = (238, 237, 233)
INK = (43, 43, 43)
MUTED = (95, 93, 88)
GRAT = (178, 175, 166)
EDGE = (150, 147, 140)

FONT_REG = "C:/Windows/Fonts/arial.ttf"
FONT_BOLD = "C:/Windows/Fonts/arialbd.ttf"

Z_BREAKS = [0, 20, 100, 200, 300, 500, 700, 900, 1200, 1600, 3000]

TEXTS = {
    "hypsometry": dict(
        title="Relevo",
        subtitle="Hipsometria sobre relevo sombreado",
        legend="Altitude (m)",
        source=""),                     # a altitude e o mesmo GEDTM30 da nota do relevo
    "geology": dict(
        title="Geologia",
        subtitle="Grupos de rochas nas cores do Mapa Geológico do Brasil de Lamego (1960)",
        legend="Grupos de rochas",
        source="Geologia: mapa litológico do Brasil harmonizado em 9 grupos de rochas "
               "(brazil_lithology_harmonized, 2026)."),
    "soil_orders": dict(
        title="Solos",
        subtitle="Ordens do Sistema Brasileiro de Classificação de Solos (SiBCS, 6ª edição, 2025)",
        legend="Ordens de solos",
        source="Solos: IBGE, BDiA Pedologia 1:250.000 (2023), classes convertidas para o "
               "SiBCS 2025 (Embrapa)."),
}
NOTES = [
    "Relevo sombreado: GEDTM30 v1.2, 30 m (Ho et al., 2025), renderizado no Blender 4.5 "
    "(Cycles). Terreno em duas escalas: formas largas (filtro gaussiano de 2 km) com "
    "exagero vertical de 128 vezes e detalhe com exagero de 8 vezes; luz de noroeste "
    "(azimute 315°, elevação 45°).",
    "Projeção policônica, SIRGAS 2000 (EPSG:5880). Escala verdadeira ao longo dos paralelos.",
    "Elaboração: Cássio Moquedace, 2026.",
]


def parse_args():
    ap = argparse.ArgumentParser(prog="09_layout_maps.py")
    ap.add_argument("--theme", choices=["hypsometry", "geology", "soil_orders", "all"], default="all")
    ap.add_argument("--draft", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--workers", type=int, default=8)
    return ap.parse_args()


# cores da legenda (mesmas do 08) ----------------------------------------------------

def load_08():
    import importlib.util
    spec = importlib.util.spec_from_file_location("compose08", PROJECT / "scripts" / "08_compose_hybrid.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def flat(rgb8):
    # cor que a area plana tem na apresentacao equilibrada (k = 1 -> cor^1,3)
    return tuple(int(v) for v in np.uint8(np.clip((np.asarray(rgb8, float) / 255) ** BASE_POW, 0, 1) * 255 + .5))


def legend_items(theme, m08):
    if theme == "geology":
        with open(DIR_03 / "tables" / "geology_classes.csv", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f, delimiter=";"))
        items = [(r["label"], flat(m08.hx(r["color"]) * 255)) for r in rows]
        items.append(("Sem classe (rios largos e represas)", flat(m08.hx(m08.NODATA) * 255)))
        return [("", items)]
    if theme == "soil_orders":
        with open(DIR_03 / "tables" / "soil_classes.csv", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f, delimiter=";"))
        soils, other = {}, {}
        for r in rows:
            d = soils if r["is_soil"].upper() == "TRUE" else other
            d.setdefault(r["order_label"], flat(m08.hx(r["color_order"]) * 255))
        return [("", sorted(soils.items())), ("Outras feições", sorted(other.items()))]
    return None


# mascara do Brasil a 480 m ------------------------------------------------------------

def brazil_frac_480(bid):
    with rasterio.open(DIR_03 / "raster" / "country" / f"country_{bid}.tif") as d:
        c = d.read(1) == 1
    return bid, c.reshape(512, 16, 512, 16).mean(axis=(1, 3)).astype(np.float32)


def brazil_mask(workers):
    with open(BLOCKS, encoding="utf-8-sig") as f:
        blocks = [b for b in csv.DictReader(f, delimiter=";") if str(b["has_brazil"]).upper() == "TRUE"]
    frac = np.zeros((NB * 512, NB * 512), np.float32)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for bid, fr in ex.map(brazil_frac_480, [b["block_id"] for b in blocks]):
            r, c = int(bid[1:3]), int(bid[5:7])
            frac[r * 512:(r + 1) * 512, c * 512:(c + 1) * 512] = fr
    return frac


# texto ----------------------------------------------------------------------------------

class Page:
    def __init__(self, dpi):
        self.dpi = dpi
        self.w, self.h = (int(round(v / 25.4 * dpi)) for v in PAGE_MM)
        self.img = Image.new("RGB", (self.w, self.h), PAPER)
        self.d = ImageDraw.Draw(self.img)

    def px(self, mm):
        return int(round(mm / 25.4 * self.dpi))

    def font(self, pt, bold=False):
        return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, max(6, int(round(pt / 72 * self.dpi))))

    def wrap(self, text, font, width):
        lines, cur = [], ""
        for w in text.split():
            t = (cur + " " + w).strip()
            if self.d.textlength(t, font=font) <= width or not cur:
                cur = t
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        return lines

    def para(self, x, y, text, pt, width, bold=False, fill=INK, lead=1.25):
        f = self.font(pt, bold)
        step = int(round(pt / 72 * self.dpi * lead))
        for line in self.wrap(text, f, width):
            self.d.text((x, y), line, font=f, fill=fill)
            y += step
        return y


def fmt_int(v):
    return f"{int(v):,}".replace(",", ".")


# folha ------------------------------------------------------------------------------------

def sample_regular(field, v, u):
    # bilinear de field nas linhas v e colunas u (coordenadas de celula,
    # centros em inteiros), fora do campo = 0; separavel: (len(v), len(u))
    def idx(c, n):
        i = np.floor(c).astype(np.int64)
        w = (c - i).astype(np.float32)
        return i, w, (i >= 0) & (i < n), (i + 1 >= 0) & (i + 1 < n)
    ny, nx = field.shape
    ci, cw, cok0, cok1 = idx(u, nx)
    a0 = np.where(cok0, field[:, np.clip(ci, 0, nx - 1)], 0)
    a1 = np.where(cok1, field[:, np.clip(ci + 1, 0, nx - 1)], 0)
    cols = a0 * (1 - cw) + a1 * cw                          # (ny, len(u))
    ri, rw, rok0, rok1 = idx(v, ny)
    b0 = np.where(rok0[:, None], cols[np.clip(ri, 0, ny - 1)], 0)
    b1 = np.where(rok1[:, None], cols[np.clip(ri + 1, 0, ny - 1)], 0)
    return (b0 * (1 - rw)[:, None] + b1 * rw[:, None]).astype(np.float32)


def map_image(theme, frac, m08, src_factor, max_w, max_h):
    # recorte do Brasil + folga (a sombra cai a sudeste). O canvas do 08 vai
    # so ~50 km alem do Brasil, entao a sombra dos tiles acaba na borda do
    # canvas (litoral NE e Chui): aqui o papel e a sombra fora do Brasil sao
    # refeitos com o campo de sombra estendido alem do canvas, e dentro dele
    # o tile e corrigido pela diferenca (tile + (1 - f) x papel x (S_canvas -
    # S_estendido)), que e exata porque o 08 compos fundo e Brasil por pixel
    rows = np.where(frac.max(axis=1) > 0)[0]
    cols = np.where(frac.max(axis=0) > 0)[0]
    pw, pn, pe, ps = (int(round(k * 1000 / 480)) for k in PAD_KM)
    al = lambda v, up: int(4 * (np.ceil(v / 4) if up else np.floor(v / 4)))   # multiplos de 4 (1920 m)
    r0, r1 = al(rows[0] - pn, False), al(rows[-1] + 1 + ps, True)
    c0, c1 = al(cols[0] - pw, False), al(cols[-1] + 1 + pe, True)
    crop_w_m, crop_h_m = (c1 - c0) * 480.0, (r1 - r0) * 480.0
    m_px = max(crop_w_m / max_w, crop_h_m / max_h)          # metros por pixel da folha
    tw, th = int(round(crop_w_m / m_px)), int(round(crop_h_m / m_px))

    # tiles do 08 (VRT de 30 m na overview de 30 x src_factor m), so a parte no canvas
    n480 = frac.shape[0]
    rr0, rr1, cc0, cc1 = max(r0, 0), min(r1, n480), max(c0, 0), min(c1, n480)
    k = 16 / src_factor                                     # px da leitura por px de 480 m
    H, W = int((r1 - r0) * k), int((c1 - c0) * k)
    win = Window(cc0 * 16, rr0 * 16, (cc1 - cc0) * 16, (rr1 - rr0) * 16)
    with rasterio.open(DIR_30M / f"brazil_{theme}_{PRES}_30m.vrt") as d:
        a = np.moveaxis(d.read(window=win, out_shape=(3, int((rr1 - rr0) * k), int((cc1 - cc0) * k)),
                               resampling=Resampling.average), 0, -1)
    oy, ox = int((rr0 - r0) * k), int((cc0 - c0) * k)
    # fora do canvas: repete a borda (zeros ali escureciam a borda no Lanczos)
    src = np.pad(a, ((oy, H - oy - a.shape[0]), (ox, W - ox - a.shape[1]), (0, 0)), mode="edge")
    # sem a ultima linha/coluna de cada lado do canvas (a overview media a
    # borda do tile e deixava um fio de 1 px no rascunho)
    inside = np.zeros((H, W), np.uint8)
    inside[oy + 1:oy + a.shape[0] - 1, ox + 1:ox + a.shape[1] - 1] = 255
    del a
    tile = np.asarray(Image.fromarray(src).resize((tw, th), Image.LANCZOS), np.float32) / 255
    ins = (np.asarray(Image.fromarray(inside).resize((tw, th), Image.NEAREST)) > 127).astype(np.float32)
    del src, inside

    # campos de sombra a 1920 m: o do 08 (so o canvas) e o estendido
    f1920 = frac.reshape(n480 // 4, 4, n480 // 4, 4).mean(axis=(1, 3))
    pad = 160                                                # 307 km de cada lado
    s_can = m08.shadow_field(f1920, 1920.0)
    s_ext = m08.shadow_field(np.pad(f1920, pad), 1920.0)
    # centros dos pixels da folha em coordenadas de celula de 1920 m e de 480 m
    x30 = c0 * 16 + (np.arange(tw) + 0.5) * (m_px / 30)
    y30 = r0 * 16 + (np.arange(th) + 0.5) * (m_px / 30)
    sc = sample_regular(s_can, y30 / 64 - 0.5, x30 / 64 - 0.5)
    se = sample_regular(s_ext, y30 / 64 - 0.5 + pad, x30 / 64 - 0.5 + pad)
    fb = sample_regular(frac, y30 / 16 - 0.5, x30 / 16 - 0.5)
    paper = np.array(PAPER, np.float32) / 255
    corr = tile + ((1 - fb) * (sc - se))[..., None] * paper
    bg = paper * (1 - se)[..., None]
    out = ins[..., None] * corr + (1 - ins[..., None]) * bg
    img = Image.fromarray(np.uint8(np.clip(out, 0, 1) * 255 + .5))
    return img, m_px, (r0, c0), fb


def make_sheet(theme, frac, m08, dpi, src_factor, out_dir):
    t0 = time.time()
    pg = Page(dpi)
    margin, gap, panel_w = pg.px(MARGIN_MM), pg.px(GAP_MM), pg.px(PANEL_MM)
    max_w, max_h = pg.w - 2 * margin - gap - panel_w, pg.h - 2 * margin
    mp, m_px, (r0, c0), fb = map_image(theme, frac, m08, src_factor, max_w, max_h)
    tw, th = mp.size
    mx, my = margin, margin + (max_h - th) // 2

    # graticula de 5 graus, so fora do Brasil ----------------------------------------
    X0, Y0 = XMIN + c0 * 480.0, YMAX - r0 * 480.0
    ov = Image.new("L", (tw, th), 0)
    od = ImageDraw.Draw(ov)
    lw = max(1, pg.px(0.25))
    lbl_f = pg.font(16)
    labels = []

    def to_px(lons, lats):
        xs, ys = warp_transform("EPSG:4326", "EPSG:5880", list(lons), list(lats))
        return (np.array(xs) - X0) / m_px, (Y0 - np.array(ys)) / m_px

    for lon in range(-80, -25, GRAT_DEG):
        lats = np.arange(15, -45.01, -0.1)
        px, py = to_px(np.full(lats.size, lon), lats)
        od.line(list(zip(px, py)), fill=255, width=lw)
        k = np.where((py[:-1] < 0) & (py[1:] >= 0))[0]
        if k.size and 0 <= px[k[0]] <= tw:
            labels.append(("top", px[k[0]], f"{abs(lon)}° O"))
    for lat in range(-40, 15, GRAT_DEG):
        lons = np.arange(-85, -25.01, 0.1)
        px, py = to_px(lons, np.full(lons.size, lat))
        od.line(list(zip(px, py)), fill=255, width=lw)
        k = np.where((px[:-1] < 0) & (px[1:] >= 0))[0]
        if k.size and 0 <= py[k[0]] <= th:
            lab = "0°" if lat == 0 else f"{abs(lat)}° {'S' if lat < 0 else 'N'}"
            labels.append(("left", py[k[0]], lab))
    alpha = Image.fromarray((np.asarray(ov, np.float32) * (1 - np.clip(fb, 0, 1))).astype(np.uint8))
    mp.paste(Image.new("RGB", (tw, th), GRAT), (0, 0), alpha)
    pg.img.paste(mp, (mx, my))
    for side, v, text in labels:
        tw_ = pg.d.textlength(text, font=lbl_f)
        if side == "top":
            pg.d.text((mx + v - tw_ / 2, my - pg.px(7)), text, font=lbl_f, fill=MUTED)
        else:
            pg.d.text((mx - tw_ - pg.px(2.5), my + v - pg.px(2.5)), text, font=lbl_f, fill=MUTED)

    # painel -------------------------------------------------------------------------
    px0 = pg.w - margin - panel_w
    y = margin
    tx = TEXTS[theme]
    pg.d.text((px0, y), "BRASIL", font=pg.font(64, True), fill=INK)
    y += pg.px(26)
    pg.d.text((px0, y), tx["title"], font=pg.font(44, True), fill=INK)
    y += pg.px(19)
    y = pg.para(px0, y, tx["subtitle"], 22, panel_w, fill=MUTED) + pg.px(10)

    pg.d.text((px0, y), tx["legend"], font=pg.font(22, True), fill=INK)
    y += pg.px(13)
    sw_w, sw_h = pg.px(17), pg.px(10)
    lab_f = pg.font(21)
    if theme == "hypsometry":
        seg_h = pg.px(17)
        lut = m08.hypso_lut()
        n_seg = len(Z_BREAKS) - 1
        bar = np.zeros((seg_h * n_seg, sw_w, 3), np.uint8)
        for i in range(n_seg):
            # de cima para baixo: mais alto em cima
            za, zb = Z_BREAKS[n_seg - i], Z_BREAKS[n_seg - i - 1]
            z = np.linspace(za, zb, seg_h)
            c = np.uint8(np.clip((lut[np.clip(np.round(z), 0, 3000).astype(int)] / 255.0) ** BASE_POW, 0, 1) * 255 + .5)
            bar[i * seg_h:(i + 1) * seg_h] = c[:, None, :]
        pg.img.paste(Image.fromarray(bar), (px0, y))
        pg.d.rectangle([px0, y, px0 + sw_w, y + seg_h * n_seg], outline=EDGE, width=max(1, pg.px(0.2)))
        for i, z in enumerate(reversed(Z_BREAKS)):
            yy = y + i * seg_h
            pg.d.line([px0 + sw_w, yy, px0 + sw_w + pg.px(3), yy], fill=EDGE, width=max(1, pg.px(0.2)))
            t = fmt_int(z) + (" m" if z in (0, 3000) else "")
            pg.d.text((px0 + sw_w + pg.px(5), yy - pg.px(3.7)), t, font=lab_f, fill=INK)
        y += seg_h * n_seg + pg.px(14)
    else:
        for head, items in legend_items(theme, m08):
            if head:
                y += pg.px(3)
                pg.d.text((px0, y), head, font=pg.font(19, True), fill=MUTED)
                y += pg.px(10)
            for label, rgb in items:
                pg.d.rectangle([px0, y, px0 + sw_w, y + sw_h], fill=rgb, outline=EDGE, width=max(1, pg.px(0.2)))
                pg.d.text((px0 + sw_w + pg.px(5), y + (sw_h - pg.px(7.4)) / 2), label, font=lab_f, fill=INK)
                y += sw_h + pg.px(4)
        y += pg.px(10)

    # barra de escala ----------------------------------------------------------------
    pg.d.text((px0, y), "Escala", font=pg.font(19, True), fill=INK)
    y += pg.px(10)
    bh = pg.px(3.5)
    km_px = 1000.0 / m_px
    for i in range(len(SCALE_KM) - 1):
        xa, xb = px0 + SCALE_KM[i] * km_px, px0 + SCALE_KM[i + 1] * km_px
        pg.d.rectangle([xa, y, xb, y + bh], fill=INK if i % 2 == 0 else (255, 255, 255), outline=INK,
                       width=max(1, pg.px(0.2)))
    sf = pg.font(16)
    for k in SCALE_KM:
        t = f"{k}" + (" km" if k == SCALE_KM[-1] else "")
        tl = pg.d.textlength(str(k), font=sf)
        pg.d.text((px0 + k * km_px - tl / 2, y + bh + pg.px(1.5)), t, font=sf, fill=INK)
    y += bh + pg.px(10)
    # escala nominal da folha impressa em A0 (independe do dpi do arquivo)
    den = m_px * dpi / 0.0254
    pg.d.text((px0, y), f"1:{fmt_int(round(den, -5))} impresso em A0 ({PAGE_MM[0]:.0f} x {PAGE_MM[1]:.0f} mm)",
              font=pg.font(16), fill=MUTED)
    y += pg.px(14)

    # fontes e metodo, de baixo para cima ----------------------------------------------
    notes = [n for n in [tx["source"]] + NOTES if n]
    nf = pg.font(15)
    step = int(round(15 / 72 * dpi * 1.3))
    blocks_ = [pg.wrap(n, nf, panel_w) for n in notes]
    total = sum(len(b) * step for b in blocks_) + pg.px(3) * (len(blocks_) - 1)
    yn = max(y, pg.h - margin - total)
    for b in blocks_:
        for line in b:
            pg.d.text((px0, yn), line, font=nf, fill=MUTED)
            yn += step
        yn += pg.px(3)

    # saida --------------------------------------------------------------------------------
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / f"brazil_{theme}_a0"
    pg.img.save(base.with_suffix(".png"), dpi=(dpi, dpi), optimize=False, compress_level=6)
    pg.img.save(base.with_suffix(".pdf"), "PDF", resolution=dpi, quality=95)
    prev_w = 2400
    pg.img.resize((prev_w, int(pg.h * prev_w / pg.w)), Image.LANCZOS).save(
        out_dir / f"brazil_{theme}_a0_preview.jpg", quality=90)
    print(f"{theme}: folha {pg.w} x {pg.h} px ({dpi} dpi), mapa {tw} x {th} px a {m_px:.0f} m/px, "
          f"escala 1:{fmt_int(round(den, -5))}, {len(labels)} rotulos de graticula, {time.time() - t0:.0f} s")


def main():
    args = parse_args()
    dpi, src_factor = (100, 32) if args.draft else (300, 8)       # overview de 960 m ou 240 m
    out_dir = Path(args.out) if args.out else (DIR_LAYOUT / "draft" if args.draft else DIR_LAYOUT)
    themes = ["hypsometry", "geology", "soil_orders"] if args.theme == "all" else [args.theme]
    print(f"\n# 09 layout {'-' * 64}")
    print(f"{len(themes)} tema(s), {dpi} dpi, mapa lido a {30 * src_factor:.0f} m; saida em {out_dir}")
    t0 = time.time()
    frac = brazil_mask(args.workers)
    print(f"mascara do Brasil a 480 m em {time.time() - t0:.0f} s")
    m08 = load_08()
    for th in themes:
        make_sheet(th, frac, m08, dpi, src_factor, out_dir)
    print(f"fim em {(time.time() - t0) / 60:.1f} min")


if __name__ == "__main__":
    main()
