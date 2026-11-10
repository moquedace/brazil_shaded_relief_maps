# brazil_shaded_relief_maps - 04 renderiza o relevo sombreado no blender -----
#
# roda dentro do Blender 4.5 LTS (bpy), sem abrir a interface. PowerShell:
#   & "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" -b `
#     -P "<projeto>\scripts\04_render_relief.py" -- --mode pilot
#
# entrada: heightmaps PNG 16 bits e tabela de blocos do 02
#   data/intermediate/02_prepared_dem/heightmaps[/pilot]/heightmap_rRR_cCC.png
#   data/intermediate/02_prepared_dem/tables[/pilot]/heightmap_blocks.csv
#
# saida: data/intermediate/04_relief_renders[/pilot]/<estilo>/relief_rRR_cCC.png
#   png 16 bits em tons de cinza, so o nucleo do bloco (8192 px a 100%),
#   com world file (.pgw) para abrir georreferenciado no QGIS (EPSG:5880)
#   render_log.csv: tempo de cada render
#
# metodo: Huffman (2017, rev. 2023), "Creating Shaded Relief in Blender".
# diferencas em relacao ao tutorial:
#   - cena montada por script, a mesma para todos os blocos e os 3 mapas
#   - escala vertical em metros reais: o heightmap vai de z_min a z_max
#     (lidos da tabela de blocos do 02; 0 a 7000 m desde 08/11/2026, 0 a
#     3000 m no piloto) e o plano tem 1 unidade = 1000 px = 30 km; logo a
#     escala do no Displacement = (z_max - z_min) / 30000 x E, com E o
#     exagero vertical em vezes reais (no tutorial a escala e escolhida no olho)
#   - sol dado por azimute e elevacao (315 graus = noroeste, 45 graus acima
#     do horizonte = rotacao 0/45/135 do tutorial)
#   - renderiza so o nucleo do bloco: a borda de 1024 px fica fora do
#     quadro, mas continua na cena e projeta sombra para dentro, entao os
#     blocos emendam sem costura
#   - transformacao de cor "Standard" (o padrao AgX do Blender 4 lava o cinza)
#
# opcoes (depois do --):
#   --mode pilot|test|full   piloto: so o bloco do 02 piloto (heightmap antigo,
#                            0 a 3000 m); teste: os blocos de TEST_BLOCKS com
#                            os heightmaps da rodada inteira, saida em
#                            04_relief_renders/test/ (escolha do exagero)
#   --exaggeration 1 2 4     um render por valor de exagero vertical (padrao:
#                            2; no modo test, 1 2 4 8)
#   --percent 25             resolucao em % (25 = previa rapida, 100 = 30 m)
#   --samples 32             amostras do Cycles (com denoise)
#   --sun-azimuth 315 --sun-elevation 45 --sun-angle 90 --sun-strength 5
#   --exposure -0.5          stops antes do Standard. Com 0 (o piloto) o chao
#                            plano sai em 0,86 e a encosta de frente para o
#                            sol estoura no branco: 1% dos pixels do
#                            Quadrilatero com E 2 e 4 (log 11). -0,5 deixa o
#                            plano em ~0,72 e folga para as encostas
#   --dicing-rate 1          malha da subdivisao em px (2 = 1/4 da RAM)
#   --blocks r11_c13 ...     so esses blocos
#   --all-blocks             inclui blocos sem Brasil (mar e vizinhos)
#   --out-dir <pasta>        outra pasta de saida (teste)
#   --overwrite              refaz renders ja gravados

import argparse
import csv
import math
import sys
import time
from pathlib import Path

import bpy
from mathutils import Vector

# caminhos ---------------------------------------------------------------------


def script_file():
    try:
        return Path(__file__).resolve()
    except NameError:  # rodando por -P sem __file__
        return Path(sys.argv[sys.argv.index("-P") + 1]).resolve()


PROJECT = script_file().parents[1]
DIR_02 = PROJECT / "data" / "intermediate" / "02_prepared_dem"
DIR_04 = PROJECT / "data" / "intermediate" / "04_relief_renders"

UNIT_PX = 1000  # 1 unidade do Blender = 1000 px do heightmap

# blocos do teste de exagero (08/11/2026, log 11). Um exagero so vale para o
# Brasil inteiro, entao o teste cobre os extremos em vez de um lugar so.
# Escolhidos pelas estatisticas do DEM a 480 m por bloco (mediana, maximo,
# declividade, amplitude em 2,4 km; so pixels do Brasil):
TEST_BLOCKS = [
    "r12_c13",  # Mantiqueira, Itatiaia e Serra do Mar (RJ/MG): regiao mais alta
                #   com o maior desnivel, 13 a 2683 m num bloco todo no Brasil
    "r04_c06",  # Amazonia central (Manaus, foz do Madeira): planicie baixa e
                #   floresta densa, mediana 32 m, declividade mediana 0,23 graus
    "r10_c08",  # Pantanal: o bloco mais plano (declividade mediana 0,09 grau),
                #   com a borda do planalto; degraus de 0,107 m do png e ruido
                #   do DTM aparecem aqui primeiro
    "r02_c03",  # Pico da Neblina (2995 m, o ponto mais alto) isolado na
                #   planicie amazonica (mediana 79 m): os dois extremos no
                #   mesmo bloco, sombra longa sobre o plano
    "r15_c10",  # Aparados da Serra (RS/SC): paredao da Serra Geral, ~1000 m
                #   de desnivel em menos de 1 km, planicie costeira e lagoas
    "r12_c12",  # Sul de Minas (maior mediana, 890 m), vizinho a oeste do
                #   r12_c13: a emenda dos dois cruza a Mantiqueira perto da
                #   Pedra da Mina e serve de teste de costura entre blocos
]


# opcoes -----------------------------------------------------------------------

def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="04_render_relief.py")
    ap.add_argument("--mode", choices=["pilot", "test", "full"], default="pilot")
    ap.add_argument("--exaggeration", type=float, nargs="+", default=None)
    ap.add_argument("--percent", type=int, default=100)
    ap.add_argument("--samples", type=int, default=32)
    ap.add_argument("--sun-azimuth", type=float, default=315.0)
    ap.add_argument("--sun-elevation", type=float, default=45.0)
    ap.add_argument("--sun-angle", type=float, default=90.0)
    ap.add_argument("--sun-strength", type=float, default=5.0)
    ap.add_argument("--exposure", type=float, default=-0.5)
    # 1 = um micropoligono por pixel; 2 = 1/4 dos poligonos (menos RAM)
    ap.add_argument("--dicing-rate", type=float, default=1.0)
    ap.add_argument("--blocks", nargs="*", default=None)
    ap.add_argument("--all-blocks", action="store_true")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--overwrite", action="store_true")
    return ap.parse_args(argv)


# tabela de blocos do 02 -------------------------------------------------------

def num(s):
    # csv do Excel pt-BR: decimal com virgula
    return float(str(s).replace(".", "").replace(",", ".")) if "," in str(s) else float(s)


def read_blocks(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    if not rows:
        raise RuntimeError(f"tabela vazia: {path}")
    for r in rows:
        for k in ("core_xmin", "core_xmax", "core_ymin", "core_ymax", "res_m",
                  "z_min_m", "z_max_m", "png_px", "overlap_px"):
            r[k] = num(r[k])
        r["has_brazil"] = str(r["has_brazil"]).upper() == "TRUE"
    return rows


# cena -------------------------------------------------------------------------

def sun_rotation(azimuth_deg, elevation_deg):
    # direcao para o sol (x = leste, y = norte, z = cima); o sol do Blender
    # ilumina ao longo do seu -Z, entao o +Z local aponta para o sol
    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    s = Vector((math.sin(az) * math.cos(el), math.cos(az) * math.cos(el),
                math.sin(el)))
    return s.to_track_quat("Z", "Y").to_euler()


def build_scene(args, png_px, overlap_px):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    size = png_px / UNIT_PX

    # plano: grade 64 x 64 (cada face ~160 px; a subdivisao adaptativa
    # chega a 1 px dentro do limite de 12 niveis)
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=64, y_subdivisions=64,
                                    size=size, calc_uvs=True,
                                    location=(0, 0, 0))
    plane = bpy.context.active_object
    plane.name = "relief"
    mod = plane.modifiers.new("subsurf", "SUBSURF")
    mod.subdivision_type = "SIMPLE"
    plane.cycles.use_adaptive_subdivision = True
    plane.cycles.dicing_rate = 1.0

    # material: cinza 0,6 fosco + displacement verdadeiro do heightmap
    mat = bpy.data.materials.new("relief")
    mat.use_nodes = True
    if hasattr(mat, "displacement_method"):
        mat.displacement_method = "DISPLACEMENT"
    else:
        mat.cycles.displacement_method = "DISPLACEMENT"
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.6, 0.6, 0.6, 1.0)
    bsdf.inputs["Roughness"].default_value = 1.0
    for name in ("Specular IOR Level", "Specular"):
        if name in bsdf.inputs:
            bsdf.inputs[name].default_value = 0.0
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.interpolation = "Smart"
    tex.extension = "EXTEND"
    disp = nt.nodes.new("ShaderNodeDisplacement")
    disp.inputs["Midlevel"].default_value = 0.0
    nt.links.new(tex.outputs["Color"], disp.inputs["Height"])
    nt.links.new(disp.outputs["Displacement"],
                 nt.nodes["Material Output"].inputs["Displacement"])
    plane.data.materials.append(mat)

    # camera ortografica de cima, enquadrando o plano inteiro
    cam_data = bpy.data.cameras.new("camera")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = size
    cam_data.clip_start = 0.1
    cam_data.clip_end = 100.0
    cam = bpy.data.objects.new("camera", cam_data)
    cam.location = (0.0, 0.0, 20.0)
    scene.collection.objects.link(cam)
    scene.camera = cam

    # sol
    sun_data = bpy.data.lights.new("sun", "SUN")
    sun_data.energy = args.sun_strength
    sun_data.angle = math.radians(args.sun_angle)
    sun = bpy.data.objects.new("sun", sun_data)
    sun.rotation_euler = sun_rotation(args.sun_azimuth, args.sun_elevation)
    scene.collection.objects.link(sun)

    # mundo: cinza fraco (o padrao do Blender), so para as sombras nao
    # ficarem pretas
    world = bpy.data.worlds.new("world")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.050876, 0.050876, 0.050876, 1.0)
    bg.inputs["Strength"].default_value = 1.0
    scene.world = world

    # render
    scene.render.engine = "CYCLES"
    scene.cycles.feature_set = "EXPERIMENTAL"   # subdivisao adaptativa
    scene.cycles.device = "CPU"
    scene.cycles.samples = args.samples
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.use_denoising = True
    scene.cycles.denoiser = "OPENIMAGEDENOISE"
    scene.cycles.dicing_rate = args.dicing_rate
    scene.cycles.max_subdivisions = 12
    scene.cycles.max_bounces = 4
    scene.cycles.diffuse_bounces = 2
    scene.cycles.glossy_bounces = 0
    scene.cycles.transmission_bounces = 0
    scene.cycles.volume_bounces = 0
    scene.cycles.tile_size = 2048
    scene.render.threads_mode = "AUTO"

    scene.render.resolution_x = png_px
    scene.render.resolution_y = png_px
    scene.render.resolution_percentage = args.percent
    # so o nucleo: a sobreposicao fica fora do quadro
    f = overlap_px / png_px
    scene.render.use_border = True
    scene.render.use_crop_to_border = True
    scene.render.border_min_x = f
    scene.render.border_max_x = 1 - f
    scene.render.border_min_y = f
    scene.render.border_max_y = 1 - f

    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "BW"
    scene.render.image_settings.color_depth = "16"
    scene.render.image_settings.compression = 15
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = args.exposure
    scene.view_settings.gamma = 1.0
    scene.render.film_transparent = False

    return scene, tex, disp


# saida ------------------------------------------------------------------------

def style_name(args, e):
    tag = lambda v: f"{v:g}".replace(".", "p").replace("-", "m")
    return (f"e{tag(e)}_az{tag(args.sun_azimuth)}_el{tag(args.sun_elevation)}"
            f"_p{args.percent}")


def write_pgw(png, b, px_size):
    # world file: pixel, rotacoes, -pixel, centro do pixel superior esquerdo
    x0 = b["core_xmin"] + px_size / 2
    y0 = b["core_ymax"] - px_size / 2
    png.with_suffix(".pgw").write_text(
        f"{px_size:.6f}\n0\n0\n{-px_size:.6f}\n{x0:.6f}\n{y0:.6f}\n",
        encoding="ascii")


def append_log(path, row):
    new = not path.exists()
    with open(path, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        if new:
            w.writerow(list(row.keys()))
        w.writerow([str(v).replace(".", ",") if isinstance(v, float) else v
                    for v in row.values()])


def fmt_time(s):
    return f"{s:.0f} s" if s < 120 else (f"{s / 60:.0f} min" if s < 5400
                                        else f"{s / 3600:.1f} h")


# execucao ---------------------------------------------------------------------

def main():
    args = parse_args()
    pilot = args.mode == "pilot"
    test = args.mode == "test"
    if args.exaggeration is None:
        args.exaggeration = [1.0, 2.0, 4.0, 8.0] if test else [2.0]
    # o teste usa os heightmaps e a tabela da rodada inteira; so a saida muda
    sub = "pilot" if pilot else ""
    table = DIR_02 / "tables" / sub / "heightmap_blocks.csv"
    hm_dir = DIR_02 / "heightmaps" / sub
    out_root = Path(args.out_dir) if args.out_dir else DIR_04 / ("test" if test else sub)

    blocks = read_blocks(table)
    if test and not args.blocks:
        args.blocks = TEST_BLOCKS
    if args.blocks:
        # na ordem pedida (no teste, o mais informativo primeiro)
        by_id = {b["block_id"]: b for b in blocks}
        missing = [k for k in args.blocks if k not in by_id]
        if missing:
            raise RuntimeError(f"bloco fora da tabela: {', '.join(missing)}")
        blocks = [by_id[k] for k in args.blocks]
    elif not args.all_blocks and not pilot:
        blocks = [b for b in blocks if b["has_brazil"]]
    if not blocks:
        raise RuntimeError("nenhum bloco selecionado")

    png_px = int(blocks[0]["png_px"])
    overlap_px = int(blocks[0]["overlap_px"])
    res = blocks[0]["res_m"]
    z_range = blocks[0]["z_max_m"] - blocks[0]["z_min_m"]
    # escala do Displacement para relevo em escala real (E = 1)
    true_scale = z_range / (UNIT_PX * res)
    px_size = res * 100 / args.percent
    core_px = round((png_px - 2 * overlap_px) * args.percent / 100)

    print(f"\n# 04 render {'-' * 66}")
    print(f"modo {args.mode}: {len(blocks)} blocos x {len(args.exaggeration)} exageros;"
          f" saida {core_px} x {core_px} px ({px_size:g} m) em {out_root}")
    print(f"escala real do displacement: {true_scale:.4f} unidade por 1,0 do heightmap"
          f" ({z_range:g} m); sol az {args.sun_azimuth:g} el {args.sun_elevation:g}"
          f" angulo {args.sun_angle:g} forca {args.sun_strength:g} exposicao {args.exposure:g};"
          f" {args.samples} amostras;"
          f" dicing {args.dicing_rate:g} px")
    # sombra mais longa que a sobreposicao vira costura: uma montanha fora da
    # borda do heightmap nao projeta sombra para dentro do nucleo vizinho.
    # Pior caso no Brasil: o Pico da Neblina, ~2900 m acima da planicie
    tan_el = math.tan(math.radians(args.sun_elevation))
    for e in args.exaggeration:
        shadow_px = 2900 * e / tan_el / res
        flag = "" if shadow_px < overlap_px else "  << maior que a sobreposicao: costura"
        print(f"  E {e:g}: sombra de 2900 m de desnivel = {shadow_px:.0f} px"
              f" (sobreposicao {overlap_px} px){flag}")

    scene, tex, disp = build_scene(args, png_px, overlap_px)

    n_total = len(blocks) * len(args.exaggeration)
    i, t_start, t_renders = 0, time.time(), []
    for b in blocks:
        hm = hm_dir / b["file"]
        if not hm.exists():
            raise FileNotFoundError(hm)
        img = None
        for e in args.exaggeration:
            i += 1
            out_dir = out_root / style_name(args, e)
            out_dir.mkdir(parents=True, exist_ok=True)
            out = out_dir / f"relief_{b['block_id']}.png"
            if out.exists() and not args.overwrite:
                print(f"[{i}/{n_total}] {b['block_id']} e{e:g} ja existe")
                continue
            if img is None:
                img = bpy.data.images.load(str(hm), check_existing=False)
                img.colorspace_settings.name = "Non-Color"
                tex.image = img
            disp.inputs["Scale"].default_value = true_scale * e
            scene.render.filepath = str(out)
            t0 = time.time()
            bpy.ops.render.render(write_still=True)
            dt = time.time() - t0
            t_renders.append(dt)
            write_pgw(out, b, px_size)
            append_log(out_root / "render_log.csv", {
                "block_id": b["block_id"], "exaggeration": float(e),
                "percent": args.percent, "samples": args.samples,
                "sun_azimuth": args.sun_azimuth, "sun_elevation": args.sun_elevation,
                "exposure": args.exposure,
                "seconds": round(dt, 1), "file": str(out)})
            left = (n_total - i) * (sum(t_renders) / len(t_renders))
            print(f"[{i}/{n_total}] {b['block_id']} e{e:g}: {fmt_time(dt)}"
                  f" | falta ~{fmt_time(left)}", flush=True)
        if img is not None:
            tex.image = None
            bpy.data.images.remove(img)

    print(f"\nfim em {fmt_time(time.time() - t_start)}")
    if t_renders and args.percent == 100:
        mean = sum(t_renders) / len(t_renders)
        print(f"media {fmt_time(mean)} por bloco a 100%: os 183 blocos com Brasil"
              f" levariam ~{fmt_time(mean * 183)} por estilo")


if __name__ == "__main__":
    main()
