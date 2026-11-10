# brazil_shaded_relief_maps - 12 site estatico para o GitHub Pages --------------
#
# Python 3.13 com numpy, rasterio, Pillow, reportlab e PyMuPDF. PowerShell,
# depois do 10 e do 11 (usa as pranchas, as telas e os mapas deles):
#   python "<projeto>\scripts\12_build_site.py"               (tudo, ~15-20 min)
#   python "<projeto>\scripts\12_build_site.py" --skip-zoom   (so pagina e downloads)
#
# monta em data/final/site/ o site publicado em
# https://moquedace.github.io/brazil_shaded_relief_maps/ (log 25). So
# produtos: nenhum dado bruto (nem os GeoTIFF de 30 m, nem vetores), decisao
# do Cassio em 10/11/2026.
#   index.html   pagina unica com o layout do HTML do 11: as 5
#                pranchas, as conjuntas, um visualizador com zoom, downloads,
#                fontes, referencias, como citar e licenca
#   assets/      mapas da pagina em JPEG (dos PNG digitais do 11), rampa,
#                previas das pranchas e imagem de compartilhamento
#   downloads/   PDFs A0 leves (*_a0_light.pdf: as mesmas imagens a ~300 dpi
#                recomprimidas em JPEG q90, texto vetorial) e as telas PNG/PDF
#   zoom/        piramide Deep Zoom por tema (<tema>.dzi + <tema>_files/),
#                WebP q80 em tiles de 510 px + 1 px de sobreposicao, lida pelo
#                OpenSeadragon 4.1.1 (jsdelivr). Vem da overview de 120 m do 08
#                (36.864 px de lado): com 60 m o site passaria de 1 GB, o
#                limite do GitHub Pages (medido em 10/11/2026: WebP a ~0,8
#                bit/px a 30 m e ~1,1 a 120 m)
# os PDFs A0 originais (60-120 MB; o git barra arquivo acima de 100 MB) vao
# como arquivos da release do GitHub (scripts/tools/publish_site.ps1); a
# pagina aponta para releases/latest/download/<arquivo>
# opcoes: --skip-zoom  --overwrite-zoom  --workers 12
#
# 10/11/2026, depois de publicado (log 25): no celular o endereco longo do
# "Como citar" nao quebrava, passava da caixa e alargava a pagina (436 px
# numa tela de 375); as colunas de fontes tinham minimo de 340 px; a tabela
# de downloads rolava de lado com os botoes cortados; o zoom ocupava 76% da
# altura e prendia a rolagem. Corrigido: quebra de texto longo, colunas com
# min(100%, 340 px), tabela em cartoes abaixo de 760 px, zoom com 62% da
# altura no celular e largura/altura declaradas nas imagens (o conteudo
# pulava enquanto as imagens carregavam e o menu errava a rolagem). Na mesma
# noite o Cassio mandou um print das referencias: o CSS do atlas (11) transforma
# todo <i> dentro de <li> no quadradinho de cor da legenda (caixa com borda,
# altura fixa), e o recuo negativo da lista entrava nessa caixa e jogava o
# titulo em italico por cima do ano. O italico das referencias e da citacao
# voltou a ser texto comum (.refs li i, .cite i)

import argparse
import html
import importlib.util
import math
import os
import shutil
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

PROJECT = Path(__file__).resolve().parents[1]
FINAL = PROJECT / "data" / "final"
PLATES = FINAL / "atlas" / "plates_a0"
MULTI = FINAL / "atlas" / "multiformat"
OVR = FINAL / "30m" / "vrt_overviews"
SITE = FINAL / "site"
TMP = PROJECT / "data" / "intermediate" / "12_site" / "tmp"

SITE_URL = "https://moquedace.github.io/brazil_shaded_relief_maps/"
REPO_URL = "https://github.com/moquedace/brazil_shaded_relief_maps"
RELEASE_URL = REPO_URL + "/releases/latest/download/"
OSD = "https://cdn.jsdelivr.net/npm/openseadragon@4.1.1/build/openseadragon/"

TILE, OVERLAP, WEBP_Q = 510, 1, 80
ZOOM_RES = 120                          # m por pixel no nivel mais fundo
PAGES_LIMIT = 1024 ** 3                 # 1 GB do GitHub Pages


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def mb(path):
    return f"{path.stat().st_size / 1e6:.0f} MB".replace(".", ",")


# downloads ---------------------------------------------------------------------

def light_pdf(job):
    # mesma pagina e mesma resolucao, imagens recomprimidas em JPEG q90
    import fitz
    src, dst = job
    if dst.exists() and dst.stat().st_mtime > src.stat().st_mtime:
        return dst.name, "ja_existe"
    tmp = dst.with_suffix(".tmp.pdf")
    doc = fitz.open(src)
    doc.rewrite_images(quality=90, lossy=True, lossless=True)
    doc.save(tmp, garbage=3, deflate=True)
    doc.close()
    tmp.replace(dst)
    return dst.name, "ok"


def build_downloads(themes, workers):
    d = SITE / "downloads"
    d.mkdir(parents=True, exist_ok=True)
    jobs = [(PLATES / f"brazil_{t}_a0.pdf", d / f"brazil_{t}_a0_light.pdf") for t in themes]
    jobs.append((MULTI / "brazil_three_maps_a0.pdf", d / "brazil_three_maps_a0_light.pdf"))
    for src, _ in jobs:
        if not src.exists():
            raise SystemExit(f"falta {src}: rode o 10 e o 11 antes")
    with ProcessPoolExecutor(max_workers=min(workers, 3)) as ex:
        for name, status in ex.map(light_pdf, jobs):
            print(f"  {name}: {status}", flush=True)
    for t in list(themes) + ["three_maps"]:
        for ext in ("png", "pdf"):
            shutil.copy2(MULTI / f"brazil_{t}_screen.{ext}", d / f"brazil_{t}_screen.{ext}")


def build_assets(themes):
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    a = SITE / "assets"
    a.mkdir(parents=True, exist_ok=True)
    for t in themes:
        with Image.open(MULTI / "assets" / f"map_{t}_digital.png") as im:
            im.convert("RGB").save(a / f"map_{t}.jpg", quality=88, optimize=True, progressive=True)
        with Image.open(PLATES / f"brazil_{t}_a0_preview.jpg") as im:
            im.thumbnail((900, 1300))
            im.save(a / f"plate_{t}.jpg", quality=85, optimize=True)
    shutil.copy2(MULTI / "assets" / "ramp_h_7.png", a / "ramp_h_7.png")
    with Image.open(MULTI / "brazil_three_maps_screen.png") as im:
        im.convert("RGB").resize((1920, 1080), Image.LANCZOS).save(a / "three_maps_screen.jpg", quality=88, optimize=True)
        im.convert("RGB").resize((1200, 675), Image.LANCZOS).save(a / "og.jpg", quality=85, optimize=True)
    with Image.open(MULTI / "brazil_three_maps_a0_preview.jpg") as im:
        im.thumbnail((1800, 1800))
        im.save(a / "three_maps_a0.jpg", quality=86, optimize=True)


# zoom (Deep Zoom) ---------------------------------------------------------------------

def level_dims(w, h):
    max_l = math.ceil(math.log2(max(w, h)))
    return max_l, [(math.ceil(w / 2 ** (max_l - L)), math.ceil(h / 2 ** (max_l - L))) for L in range(max_l + 1)]


def tile_row(job):
    # uma linha de tiles de um nivel; le o nivel de um .npy em memmap
    from PIL import Image
    npy, out_dir, row, w, h = job
    a = np.load(npy, mmap_mode="r")
    y0 = max(0, row * TILE - OVERLAP)
    y1 = min(h, (row + 1) * TILE + OVERLAP)
    n = 0
    for col in range(math.ceil(w / TILE)):
        x0 = max(0, col * TILE - OVERLAP)
        x1 = min(w, (col + 1) * TILE + OVERLAP)
        Image.fromarray(np.ascontiguousarray(a[y0:y1, x0:x1])).save(
            out_dir / f"{col}_{row}.webp", "WEBP", quality=WEBP_Q, method=4)
        n += 1
    return n


def safe_unlink(f):
    # no Windows o memmap pode segurar o arquivo por um instante
    try:
        f.unlink()
    except PermissionError:
        print(f"  aviso: nao apaguei {f} (em uso); apagar depois", flush=True)


def downsample(src, dst, w, h):
    # media 2 x 2 (a borda impar repete a ultima linha/coluna)
    a = np.load(src, mmap_mode="r")
    b = np.lib.format.open_memmap(dst, "w+", np.uint8, ((h + 1) // 2, (w + 1) // 2, 3))
    for r0 in range(0, h, 4096):
        s = np.asarray(a[r0:min(h, r0 + 4096)])
        if s.shape[0] % 2:
            s = np.concatenate([s, s[-1:]], 0)
        if s.shape[1] % 2:
            s = np.concatenate([s, s[:, -1:]], 1)
        t = s.reshape(s.shape[0] // 2, 2, s.shape[1] // 2, 2, 3).astype(np.uint16).sum((1, 3))
        b[r0 // 2:r0 // 2 + t.shape[0]] = ((t + 2) // 4).astype(np.uint8)
    b.flush()
    del a, b


def build_zoom(theme, workers, overwrite):
    import rasterio
    from rasterio.windows import Window
    zdir = SITE / "zoom"
    dzi = zdir / f"{theme}.dzi"
    files = zdir / f"{theme}_files"
    if dzi.exists() and not overwrite:
        print(f"  {theme}: ja existe", flush=True)
        return
    t0 = time.time()
    shutil.rmtree(files, ignore_errors=True)
    TMP.mkdir(parents=True, exist_ok=True)
    vrt = OVR / f"brazil_{theme}_balanced_{ZOOM_RES}m.vrt"
    with rasterio.open(vrt) as d:
        w, h = d.width, d.height
        max_l, dims = level_dims(w, h)
        cur = TMP / f"{theme}_L{max_l}.npy"
        a = np.lib.format.open_memmap(cur, "w+", np.uint8, (h, w, 3))
        for r0 in range(0, h, 2048):
            n = min(2048, h - r0)
            a[r0:r0 + n] = np.moveaxis(d.read(window=Window(0, r0, w, n)), 0, -1)
        a.flush()
        del a
    print(f"  {theme}: {w} x {h} px a {ZOOM_RES} m lidos em {time.time() - t0:.0f} s", flush=True)
    n_tiles = 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for L in range(max_l, -1, -1):
            lw, lh = dims[L]
            out = files / str(L)
            out.mkdir(parents=True, exist_ok=True)
            n_tiles += sum(ex.map(tile_row, [(cur, out, r, lw, lh) for r in range(math.ceil(lh / TILE))]))
            if L > 0:
                nxt = TMP / f"{theme}_L{L - 1}.npy"
                downsample(cur, nxt, lw, lh)
                safe_unlink(cur)
                cur = nxt
    safe_unlink(cur)
    dzi.write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                   '<Image xmlns="http://schemas.microsoft.com/deepzoom/2008" '
                   f'Format="webp" Overlap="{OVERLAP}" TileSize="{TILE}"><Size Width="{w}" Height="{h}"/></Image>\n',
                   encoding="utf-8")
    size = sum(f.stat().st_size for f in files.rglob("*.webp"))
    print(f"  {theme}: {n_tiles} tiles em {max_l + 1} niveis, {size / 1e6:.0f} MB, {time.time() - t0:.0f} s", flush=True)


# pagina ---------------------------------------------------------------------------

EXTRA_CSS = """
#viewer{width:100%;height:76vh;min-height:420px;background:var(--paper);border:1px solid var(--rule)}
.themes{display:flex;gap:10px;flex-wrap:wrap;margin:22px 0 16px}
.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:16px;min-width:720px}
th,td{border-bottom:1px solid var(--rule);padding:12px 8px;text-align:left;vertical-align:middle}
th{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:600}
td a{padding:6px 11px;font-size:14px;display:inline-block;margin:2px 4px 2px 0}
td img{width:64px;height:auto;display:block;border:1px solid var(--rule)}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));gap:40px}
.refs{display:block}.refs li{display:block;font-size:16px;line-height:1.55;color:var(--muted);margin:0 0 10px;padding-left:1.4em;text-indent:-1.4em}
.refs li i,.cite i{display:inline;flex:none;width:auto;height:auto;border:0;padding:0;text-indent:0;font-style:italic}
.refs li a,a.plain,.cite a{border:0;padding:0;text-decoration:underline}.refs li a:hover,a.plain:hover,.cite a:hover{background:none;color:var(--ink)}
.cite{font-size:16px;background:rgba(255,255,255,.35);border:1px solid var(--rule);padding:16px 18px;color:var(--ink)}
.plate footer small{color:var(--muted)}
.cite,.end p,.refs li{overflow-wrap:anywhere}
@media(max-width:760px){
#viewer{height:62vh;min-height:360px}
.table-wrap{overflow-x:visible}table{min-width:0}thead{display:none}
table,tbody,tr,td{display:block}
tr{display:grid;grid-template-columns:72px minmax(0,1fr);column-gap:14px;padding:16px 0;border-bottom:1px solid var(--rule)}
td{border:0;padding:2px 0}td:first-child{grid-row:1/span 4}td:not(:first-child){grid-column:2}
td img{width:72px}
td[data-label]::before{content:attr(data-label);display:block;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:8px 0 2px}
}
"""


def wh(rel):
    # largura e altura da imagem do site, para o navegador reservar o espaco
    # antes de carregar (sem isso o conteudo pula e o menu erra a rolagem)
    from PIL import Image
    with Image.open(SITE / rel) as im:
        return f' width="{im.width}" height="{im.height}"'


def plate_card(t, b10, b11):
    inf = b10.THEMES[t]
    light = SITE / "downloads" / f"brazil_{t}_a0_light.pdf"
    orig = PLATES / f"brazil_{t}_a0.pdf"
    return (f'<article id="{t}" class="plate"><header><span class="index">{inf["index"]}</span>'
            f'<h2>{html.escape(inf["title"])}</h2><p>{html.escape(inf["subtitle"])}</p></header>'
            f'<div class="body"><div class="map"><img src="assets/map_{t}.jpg"{wh(f"assets/map_{t}.jpg")} loading="lazy" '
            f'alt="Mapa do Brasil: {html.escape(inf["title"].lower())}'
            f'{" (cores hipsométricas sobre o relevo sombreado)" if t == "hypsometry" else " sobre relevo sombreado"}"></div>'
            f'<aside>{b11.html_legend(t)}</aside></div>'
            f'<footer><p>{html.escape(" ".join(inf["sources"]))}</p>'
            f'<a href="downloads/brazil_{t}_a0_light.pdf">Prancha A0 · PDF ({mb(light)})</a>'
            f'<a href="{RELEASE_URL}brazil_{t}_a0.pdf">A0 original para gráfica ({mb(orig)})</a>'
            f'<a download href="downloads/brazil_{t}_screen.png">PNG · 1920 × 1440</a>'
            f'<a href="downloads/brazil_{t}_screen.pdf">PDF de tela</a></footer></article>')


def downloads_table(themes, b10):
    rows = []
    for t in themes:
        inf = b10.THEMES[t]
        d = SITE / "downloads"
        rows.append(
            f'<tr><td><img src="assets/plate_{t}.jpg"{wh(f"assets/plate_{t}.jpg")} alt="" loading="lazy"></td>'
            f'<td>{inf["index"]} · {html.escape(inf["title"])}</td>'
            f'<td data-label="Prancha A0"><a href="downloads/brazil_{t}_a0_light.pdf">PDF ({mb(d / f"brazil_{t}_a0_light.pdf")})</a></td>'
            f'<td data-label="A0 original (gráfica)"><a href="{RELEASE_URL}brazil_{t}_a0.pdf">PDF ({mb(PLATES / f"brazil_{t}_a0.pdf")})</a></td>'
            f'<td data-label="Versão de tela"><a download href="downloads/brazil_{t}_screen.png">PNG</a>'
            f'<a href="downloads/brazil_{t}_screen.pdf">PDF</a></td></tr>')
    d = SITE / "downloads"
    rows.append(
        f'<tr><td><img src="assets/three_maps_a0.jpg"{wh("assets/three_maps_a0.jpg")} alt="" loading="lazy"></td><td>Relevo, geologia e solos · conjunto</td>'
        f'<td data-label="Prancha A0"><a href="downloads/brazil_three_maps_a0_light.pdf">PDF A0 deitado ({mb(d / "brazil_three_maps_a0_light.pdf")})</a></td>'
        f'<td data-label="A0 original (gráfica)"><a href="{RELEASE_URL}brazil_three_maps_a0.pdf">PDF ({mb(MULTI / "brazil_three_maps_a0.pdf")})</a></td>'
        '<td data-label="Versão de tela"><a download href="downloads/brazil_three_maps_screen.png">PNG 3840 × 2160</a>'
        '<a href="downloads/brazil_three_maps_screen.pdf">PDF</a></td></tr>')
    return ('<div class="table-wrap"><table><thead><tr><th></th><th>Mapa</th><th>Prancha A0 (tela e impressão comum)</th>'
            '<th>A0 original (gráfica)</th><th>Versão de tela</th></tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>')


REFS = [
    'Fettes, D.; Desmons, J. (Ed.) (2007). <i>Metamorphic rocks: a classification and glossary of terms</i>. Cambridge: Cambridge University Press.',
    'Ho, Y.-F.; Grohmann, C. H.; Lindsay, J.; Reuter, H. I.; Parente, L.; Witjes, M.; Hengl, T. (2025). GEDTM30: global ensemble digital terrain model at 30 m and derived multiscale terrain variables. <i>PeerJ</i>, 13, e19673. <a href="https://doi.org/10.7717/peerj.19673">doi:10.7717/peerj.19673</a>',
    'Huffman, D. (2017, versão 2.4 de 2023). <i>Creating shaded relief in Blender</i>. <a href="https://somethingaboutmaps.wordpress.com/2017/11/16/creating-shaded-relief-in-blender/">somethingaboutmaps.wordpress.com</a>',
    'IBGE (2023). <i>Banco de Dados e Informações Ambientais (BDiA): Pedologia, 1:250.000</i>. Rio de Janeiro: Instituto Brasileiro de Geografia e Estatística. <a href="https://bdiaweb.ibge.gov.br">bdiaweb.ibge.gov.br</a>',
    'Lamego, A. R. (1960). <i>Mapa geológico do Brasil</i>, 1:5.000.000. Rio de Janeiro: Departamento Nacional da Produção Mineral.',
    'Le Maitre, R. W. (Ed.) (2002). <i>Igneous rocks: a classification and glossary of terms</i>. 2. ed. Cambridge: Cambridge University Press.',
    'Santos, H. G. et al. (2025). <i>Sistema Brasileiro de Classificação de Solos</i>. 6. ed. Brasília, DF: Embrapa.',
    'Serviço Geológico do Brasil (SGB/CPRM). <i>Mapa litoestratigráfico do Brasil</i>, 1:250.000.',
    'Souza, A. (2020). Mapas em representação tridimensional. <i>Confins</i>, 47. <a href="https://doi.org/10.4000/confins.31886">doi:10.4000/confins.31886</a>',
    'Winge, M. et al. (2001). <i>Glossário geológico ilustrado</i>.',
    'World Bank. <i>World Bank Official Boundaries</i> (Admin 0). Licença CC BY 4.0. <a href="https://datacatalog.worldbank.org/search/dataset/0038272">datacatalog.worldbank.org</a>',
]


def write_page(themes, b10, b11):
    cards = "".join(plate_card(t, b10, b11) for t in themes)
    nav = "".join(f'<a href="#{t}">{html.escape(b10.THEMES[t]["title"])}</a>' for t in themes)
    zoom_btn = "".join(f'<button data-k="{i}"' + (' class="active"' if i == 0 else '') + f'>{html.escape(b10.THEMES[t]["title"])}</button>'
                       for i, t in enumerate(themes))
    refs = "".join(f"<li>{r}</li>" for r in REFS)
    plain = 'class="plain"'
    year, author, affil = b10.YEAR, b10.AUTHOR, b10.AFFIL
    cite = (f'Moquedace, C. M. ({year}). <i>Brasil: relevo, geologia, solos e diversidade</i>. Série cartográfica com relevo '
            f'sombreado a 30 m. {html.escape(affil)}. <a href="{SITE_URL}">{SITE_URL}</a>')
    page = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Brasil — relevo, geologia, solos e diversidade</title>
<meta name="description" content="Série cartográfica do Brasil sobre relevo sombreado a 30 m: relevo, geologia, solos (SiBCS 2025), diversidade pedológica e diversidade litológica. Pranchas A0, versões de tela e visualizador com zoom.">
<meta name="author" content="{html.escape(author)}">
<meta property="og:type" content="website"><meta property="og:title" content="Brasil — relevo, geologia, solos e diversidade">
<meta property="og:description" content="Cinco mapas do Brasil sobre o mesmo relevo sombreado a 30 m, renderizado no Blender.">
<meta property="og:image" content="{SITE_URL}assets/og.jpg"><meta property="og:url" content="{SITE_URL}">
<style>{b11.CSS}{EXTRA_CSS}</style></head><body><main>
<div class="kicker">Série cartográfica · Brasil · {year}</div><h1>Brasil</h1>
<p>Relevo, geologia, solos e diversidade sobre o mesmo relevo sombreado, renderizado no Blender a partir de um modelo digital de terreno de 30 m. Cinco leituras do território, com pranchas A0 para impressão, versões para tela e um visualizador com zoom.</p>
<nav>{nav}<a href="#conjunto">Pranchas conjuntas</a><a href="#explorar">Explorar com zoom</a><a href="#downloads">Downloads</a><a href="#fontes">Fontes e citação</a></nav>
<div class="links"><button id="single" class="active" onclick="view(false)">Leitura individual</button><button id="joint" onclick="view(true)">Comparar os mapas</button></div>
<p class="note">As legendas desta página são texto e se reorganizam conforme a largura da tela. Para norte, escala gráfica e composição cartográfica completa, use as pranchas em PDF ou PNG.</p>
<section id="plates">{cards}</section>
<section class="section" id="conjunto"><div class="kicker">Composições conjuntas</div><h2>Três mapas, lado a lado</h2><p>Relevo, geologia e solos no mesmo enquadramento e na mesma escala.</p>
<div class="links"><a href="downloads/brazil_three_maps_screen.png" download>PNG · 3840 × 2160</a><a href="downloads/brazil_three_maps_screen.pdf">PDF de tela</a><a href="downloads/brazil_three_maps_a0_light.pdf">A0 deitado · PDF ({mb(SITE / "downloads" / "brazil_three_maps_a0_light.pdf")})</a><a href="{RELEASE_URL}brazil_three_maps_a0.pdf">A0 original para gráfica ({mb(MULTI / "brazil_three_maps_a0.pdf")})</a></div>
<img class="preview" src="assets/three_maps_screen.jpg"{wh("assets/three_maps_screen.jpg")} loading="lazy" alt="Prancha digital com relevo, geologia e solos lado a lado">
<h3 style="margin-top:36px">Prancha A0 · 1189 × 841 mm</h3><a style="padding:0;border:0;display:block" href="downloads/brazil_three_maps_a0_light.pdf"><img class="preview" src="assets/three_maps_a0.jpg"{wh("assets/three_maps_a0.jpg")} loading="lazy" alt="Prévia da prancha A0 conjunta"></a></section>
<section class="section" id="explorar"><div class="kicker">Visualizador</div><h2>Explorar com zoom</h2>
<p>Arraste para mover e use a roda do mouse ou o gesto de pinça para aproximar. O zoom vai até 120 m por pixel; os mapas foram compostos a 30 m, e as pranchas usam essa base reduzida ao tamanho de impressão.</p>
<div class="themes" id="zoomthemes">{zoom_btn}</div><div id="viewer"></div></section>
<section class="section" id="downloads"><div class="kicker">Arquivos</div><h2>Downloads</h2>
<p>A prancha A0 em PDF tem a imagem do mapa a cerca de 300 dpi no tamanho impresso, com títulos e legendas vetoriais. A versão original, para gráfica, é a mesma prancha sem recompressão da imagem. Imprima em 100%, sem ajustar à página, para manter a escala indicada.</p>
{downloads_table(themes, b10)}</section>
<section class="section" id="fontes"><div class="kicker">Créditos</div><h2>Fontes e citação</h2><div class="cols">
<div><h3>Autoria</h3><p>Elaboração: {html.escape(author)}, {html.escape(affil)}, {year}.</p>
<h3>Como citar</h3><p class="cite">{cite}</p>
<h3>Licença</h3><p>Mapas e textos sob <a {plain} href="https://creativecommons.org/licenses/by/4.0/deed.pt-br">Creative Commons Atribuição 4.0 (CC BY 4.0)</a>: livre uso com citação da autoria e das fontes dos dados. Código sob licença MIT, no <a {plain} href="{REPO_URL}">repositório do projeto</a>.</p></div>
<div><h3>Dados de origem</h3><ul class="refs">
<li>Relevo: GEDTM30 v1.2, 30 m (Ho et al., 2025), renderizado no Blender 4.5 (Cycles), luz a noroeste (azimute 315°, elevação 45°), exagero vertical em duas escalas: 128× nas formas amplas e 8× no detalhe; método de sombreado de Huffman (2017), na linha de Souza (2020).</li>
<li>Geologia: Serviço Geológico do Brasil (SGB/CPRM), mapa litoestratigráfico, 1:250.000. Unidades agrupadas em nove classes de rocha no Departamento de Solos da UFV (Edgar Batista de Medeiros Júnior, Gabriel Palucci Rosa, Alex Pinheiro, Cássio Moquedace e Clara Baldi), com nomenclatura segundo a IUGS (Le Maitre, 2002; Fettes e Desmons, 2007) e o glossário de Winge et al. (2001). Paleta inspirada em Lamego (1960).</li>
<li>Solos: IBGE, BDiA Pedologia, 1:250.000 (2023). Classes harmonizadas até o 3º nível categórico e atualizadas para o SiBCS, 6ª edição (Santos et al., 2025).</li>
<li>Diversidade pedológica: número de componentes (classe dominante, subdominantes e inclusões) de cada unidade de mapeamento do IBGE/BDiA. Diversidade litológica: número de litologias descritas em cada unidade do mapa litoestratigráfico do SGB/CPRM, na base harmonizada no DPS/UFV.</li>
<li>Contorno do Brasil: World Bank Official Boundaries (Banco Mundial, CC BY 4.0).</li>
<li>Sistema de referência SIRGAS 2000; projeção policônica (EPSG:5880).</li></ul></div></div>
<h3 style="margin-top:34px">Referências</h3><ul class="refs">{refs}</ul></section>
<div class="end"><p>{html.escape(b10.CREDIT)}</p><p>Os dados de origem não são redistribuídos aqui: consulte as fontes acima. Código e documentação em <a {plain} href="{REPO_URL}">{REPO_URL.replace("https://", "")}</a>.</p></div>
</main>
<script src="{OSD}openseadragon.min.js"></script>
<script>
function view(j){{document.getElementById('plates').classList.toggle('joint',j);document.getElementById('single').classList.toggle('active',!j);document.getElementById('joint').classList.toggle('active',j);document.getElementById('single').setAttribute('aria-pressed',!j);document.getElementById('joint').setAttribute('aria-pressed',j)}}
// o OpenSeadragon 4.1.1 so aceita WebP no Deep Zoom depois desta chamada
OpenSeadragon.setImageFormatsSupported({{webp:true}});
var THEMES={list(themes)!r};
var viewer=OpenSeadragon({{id:'viewer',prefixUrl:'{OSD}images/',tileSources:THEMES.map(function(t,i){{return {{tileSource:'zoom/'+t+'.dzi',opacity:i===0?1:0}}}}),
  showNavigator:true,navigatorPosition:'BOTTOM_RIGHT',maxZoomPixelRatio:2,visibilityRatio:1,constrainDuringPan:true,gestureSettingsMouse:{{clickToZoom:false}}}});
var items={{}};viewer.world.addHandler('add-item',function(e){{var u=e.item.source.tilesUrl||'';THEMES.forEach(function(t){{if(u.indexOf('/'+t+'_files/')>=0)items[t]=e.item}})}});
document.querySelectorAll('#zoomthemes button').forEach(function(b){{b.addEventListener('click',function(){{var k=+b.dataset.k;THEMES.forEach(function(t,i){{if(items[t])items[t].setOpacity(i===k?1:0)}});
  document.querySelectorAll('#zoomthemes button').forEach(function(x){{x.classList.toggle('active',x===b)}})}})}});
</script></body></html>"""
    (SITE / "index.html").write_text(page, encoding="utf-8")
    (SITE / ".nojekyll").write_text("", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(prog="12_build_site.py")
    ap.add_argument("--skip-zoom", action="store_true")
    ap.add_argument("--overwrite-zoom", action="store_true")
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()
    t0 = time.time()
    b11 = load("atlas11", PROJECT / "scripts" / "11_atlas_multiformat.py")
    b10 = b11.base
    b10.fonts()
    b11.m09, b11.m08 = b10.helpers()
    themes = list(b10.THEMES)
    print(f"\n# 12 site {'-' * 66}\nsaida em {SITE}", flush=True)
    SITE.mkdir(parents=True, exist_ok=True)
    print("downloads (PDFs A0 leves e telas)", flush=True)
    build_downloads(themes, args.workers)
    build_assets(themes)
    if not args.skip_zoom:
        print(f"zoom: piramides Deep Zoom a partir de {ZOOM_RES} m", flush=True)
        for t in themes:
            build_zoom(t, args.workers, args.overwrite_zoom)
    write_page(themes, b10, b11)
    files = [f for f in SITE.rglob("*") if f.is_file()]
    total = sum(f.stat().st_size for f in files)
    parts = {}
    for f in files:
        k = f.relative_to(SITE).parts[0] if len(f.relative_to(SITE).parts) > 1 else "(raiz)"
        parts[k] = parts.get(k, 0) + f.stat().st_size
    print("\ntamanho do site: " + ", ".join(f"{k} {v / 1e6:.0f} MB" for k, v in sorted(parts.items())))
    print(f"total {total / 1024 ** 3:.2f} GB em {len(files)} arquivos (limite do GitHub Pages: 1 GB)")
    big = [f for f in files if f.stat().st_size > 100 * 1024 ** 2]
    if big:
        raise SystemExit(f"arquivo acima de 100 MB no site (o git barra): {big}")
    if total > PAGES_LIMIT * .95:
        raise SystemExit("site acima de 95% do limite de 1 GB do GitHub Pages")
    print(f"fim em {(time.time() - t0) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
