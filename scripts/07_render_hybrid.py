# brazil_shaded_relief_maps - 07 renderiza o terreno hibrido no blender -----------
#
# roda dentro do Blender 4.5 LTS (bpy), sem abrir a interface. PowerShell, sem
# o R aberto:
#   & "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" -b `
#     -P "<projeto>\scripts\07_render_hybrid.py" -- --mode test
#   & "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" -b `
#     -P "<projeto>\scripts\07_render_hybrid.py" -- --mode full --context-km 600
#
# cena da rodada 2 (09/11/2026; docs/round2), aceita pelo Cassio
# (log 15), com o entorno em dois niveis para caber no Brasil inteiro:
#   perto  heightmap hibrido de 30 m do 06 (nucleo + margem); malha
#          adaptativa de 1 px dentro da camera e offscreen_dicing_scale 16 fora
#          dela (~480 m), como na rodada 2
#   longe  anel com o terreno hibrido de 480 m do canvas inteiro
#          (06/heightmaps/far_hybrid_480m.png), furado onde esta o plano de
#          perto e indo ate context_km alem dele. Em E128 a sombra de um
#          desnivel de 2900 m vai a ~370 km com o sol a 45 graus, e o sol de 90
#          graus de diametro tem raios mais rasantes: o entorno de 245 km da
#          rodada 2 nao prova que basta (log 15). O alcance sai do --mode test
# luz e material: os do 04 (sol azimute 315, elevacao 45, diametro 90, forca
#   5; cinza 0,6 fosco; mundo 0,050876; Standard, exposicao -0,5; 32 amostras
#   com OpenImageDenoise); exagero 128 aplicado ao z hibrido (E128 nas formas
#   largas, E8 no detalhe)
# camera: ortografica, enquadra so o nucleo (ortho_scale = nucleo / 1000 px).
#   Com o render border do 04 o plano inteiro ficava no quadro e a margem era
#   picada a 1 px; enquadrando o nucleo, a margem e o anel saem a ~480 m
#   (rodada 2)
# escala: 1 unidade do Blender = 1000 px de 30 m = 30 km nos dois objetos;
#   displacement = 7000 / 30000 x 128 = 29,87 unidades para 1,0 do heightmap
#
# saida (pasta nova; os renders do 04 ficam como estao):
#   data/intermediate/07_hybrid_renders/test/<id>.png       testes (--mode test)
#   data/intermediate/07_hybrid_renders/<estilo>/relief_rRR_cCC.png + .pgw
#   render_log.csv em cada pasta
#
# opcoes (depois do --):
#   --mode test|full       test: os renders de 06/tables/test_jobs.json
#                          full: os 183 blocos com Brasil
#   --context-km 600       alcance do anel distante no full (obrigatorio la);
#                          no test, refaz so os jobs de 600 km com esse alcance
#                          (5000 = canvas inteiro; o anel e recortado no canvas)
#   --far-dicing 1         escala da malha do anel (2 = metade da resolucao)
#   --samples 32  --blocks r12_c13 ...  --only <id> ...  --overwrite

import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path

import bpy
from mathutils import Vector

# caminhos e constantes --------------------------------------------------------


def script_file():
    try:
        return Path(__file__).resolve()
    except NameError:  # rodando por -P sem __file__
        return Path(sys.argv[sys.argv.index("-P") + 1]).resolve()


PROJECT = script_file().parents[1]
DIR_02 = PROJECT / "data" / "intermediate" / "02_prepared_dem"
DIR_06 = PROJECT / "data" / "intermediate" / "06_hybrid_terrain"
DIR_07 = PROJECT / "data" / "intermediate" / "07_hybrid_renders"
FAR_PNG = DIR_06 / "heightmaps" / "far_hybrid_480m.png"

RES = 30.0                 # m por px do heightmap de perto e do render
UNIT_PX = 1000             # 1 unidade do Blender = 1000 px de 30 m
UNIT_M = UNIT_PX * RES     # = 30 km
Z_MAX = 7000.0             # m, topo da escala dos heightmaps
E = 128.0                  # exagero aplicado ao z hibrido (06)
BLOCK_MARGIN = 1024        # px de 30 m de cada lado do nucleo nos blocos (06)
RING_STEP_M = 60000.0      # faces do anel de ~60 km (a subdivisao adaptativa faz o resto)
OFFSCREEN_DICING = 16      # rodada 2: ~480 m de malha fora da camera


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="07_render_hybrid.py")
    ap.add_argument("--mode", choices=["test", "full"], required=True)
    ap.add_argument("--context-km", type=float, default=None)
    ap.add_argument("--far-dicing", type=float, default=1.0)
    ap.add_argument("--samples", type=int, default=32)
    ap.add_argument("--sun-azimuth", type=float, default=315.0)
    ap.add_argument("--sun-elevation", type=float, default=45.0)
    ap.add_argument("--sun-angle", type=float, default=90.0)
    ap.add_argument("--sun-strength", type=float, default=5.0)
    ap.add_argument("--exposure", type=float, default=-0.5)
    ap.add_argument("--blocks", nargs="*", default=None)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--overwrite", action="store_true")
    return ap.parse_args(argv)


# grade --------------------------------------------------------------------------

def num(s):
    s = str(s).strip()
    return float(s.replace(".", "").replace(",", ".")) if "," in s else float(s)


def read_canvas():
    with open(PROJECT / "config" / "canvas_5880.csv", encoding="utf-8-sig") as f:
        row = next(csv.DictReader(f, delimiter=";"))
    return {k: (row[k] if k == "crs" else num(row[k])) for k in row}


def read_blocks():
    with open(DIR_02 / "tables" / "heightmap_blocks.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    for r in rows:
        for k in ("core_xmin", "core_xmax", "core_ymin", "core_ymax"):
            r[k] = num(r[k])
        r["has_brazil"] = str(r["has_brazil"]).upper() == "TRUE"
    return rows


# cena ----------------------------------------------------------------------------

def sun_rotation(azimuth_deg, elevation_deg):
    # igual ao 04: o +Z local do sol aponta para o sol
    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    s = Vector((math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)))
    return s.to_track_quat("Z", "Y").to_euler()


def relief_material(name, image_path):
    # cinza 0,6 fosco + displacement verdadeiro do heightmap (igual ao 04)
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    if hasattr(mat, "displacement_method"):
        mat.displacement_method = "DISPLACEMENT"
    else:
        mat.cycles.displacement_method = "DISPLACEMENT"
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.6, 0.6, 0.6, 1.0)
    bsdf.inputs["Roughness"].default_value = 1.0
    for s in ("Specular IOR Level", "Specular"):
        if s in bsdf.inputs:
            bsdf.inputs[s].default_value = 0.0
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.interpolation = "Smart"
    tex.extension = "EXTEND"
    tex.image = bpy.data.images.load(str(image_path), check_existing=False)
    tex.image.colorspace_settings.name = "Non-Color"
    disp = nt.nodes.new("ShaderNodeDisplacement")
    disp.inputs["Midlevel"].default_value = 0.0
    disp.inputs["Scale"].default_value = Z_MAX / UNIT_M * E
    nt.links.new(tex.outputs["Color"], disp.inputs["Height"])
    nt.links.new(disp.outputs["Displacement"], nt.nodes["Material Output"].inputs["Displacement"])
    return mat


def adaptive(obj, dicing):
    mod = obj.modifiers.new("subsurf", "SUBSURF")
    mod.subdivision_type = "SIMPLE"
    obj.cycles.use_adaptive_subdivision = True
    obj.cycles.dicing_rate = dicing


def near_plane(job):
    # plano de perto centrado na origem (= centro do nucleo), nx x ny px
    sx, sy = job["nx"] / UNIT_PX, job["ny"] / UNIT_PX
    k = max(job["nx"], job["ny"])
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=max(8, round(64 * job["nx"] / k)),
                                    y_subdivisions=max(8, round(64 * job["ny"] / k)),
                                    size=1.0, calc_uvs=True, location=(0, 0, 0))
    ob = bpy.context.active_object
    ob.name = "near"
    for v in ob.data.vertices:
        v.co.x *= sx
        v.co.y *= sy
    ob.data.materials.append(relief_material("near", job["height"]))
    adaptive(ob, 1.0)
    return ob


def axis_breaks(o0, i0, i1, o1):
    # arestas do anel num eixo: de fora ate o furo, o furo, do furo ate fora,
    # em passos de ate RING_STEP_M
    def seg(a, b):
        n = max(1, math.ceil((b - a) / RING_STEP_M))
        return [a + (b - a) * t / n for t in range(n + 1)]
    xs = []
    for a, b in ((o0, i0), (i0, i1), (i1, o1)):
        if b - a > 1e-6:
            xs += seg(a, b)
    return sorted(set(round(v, 3) for v in xs))


def far_ring(job, canvas, context_m, dicing):
    # anel do entorno distante: canvas recortado em context_m alem do plano de
    # perto, sem as faces de dentro dele. UV = posicao no canvas (a imagem de
    # 480 m cobre o canvas inteiro)
    cx, cy = job["cx"], job["cy"]
    hx, hy = job["nx"] * RES / 2, job["ny"] * RES / 2
    ix0, ix1, iy0, iy1 = cx - hx, cx + hx, cy - hy, cy + hy
    ox0, ox1 = max(canvas["xmin"], ix0 - context_m), min(canvas["xmax"], ix1 + context_m)
    oy0, oy1 = max(canvas["ymin"], iy0 - context_m), min(canvas["ymax"], iy1 + context_m)
    xs = axis_breaks(ox0, ix0, ix1, ox1)
    ys = axis_breaks(oy0, iy0, iy1, oy1)
    nxv = len(xs)
    verts = [((x - cx) / UNIT_M, (y - cy) / UNIT_M, 0.0) for y in ys for x in xs]
    faces = []
    for j in range(len(ys) - 1):
        for i in range(len(xs) - 1):
            xc, yc = (xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2
            if ix0 < xc < ix1 and iy0 < yc < iy1:
                continue                      # furo do plano de perto
            a = j * nxv + i
            faces.append((a, a + 1, a + 1 + nxv, a + nxv))
    if not faces:
        return None
    me = bpy.data.meshes.new("far")
    me.from_pydata(verts, [], faces)
    me.update()
    uv = me.uv_layers.new(name="UVMap")
    w, h = canvas["xmax"] - canvas["xmin"], canvas["ymax"] - canvas["ymin"]
    for poly in me.polygons:
        for li in poly.loop_indices:
            vi = me.loops[li].vertex_index
            x, y = xs[vi % nxv], ys[vi // nxv]
            uv.data[li].uv = ((x - canvas["xmin"]) / w, (y - canvas["ymin"]) / h)
    ob = bpy.data.objects.new("far", me)
    bpy.context.scene.collection.objects.link(ob)
    ob.data.materials.append(relief_material("far", FAR_PNG))
    adaptive(ob, dicing)
    return ob


def build_scene(job, canvas, args):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    near_plane(job)
    ring = None
    if job["context_km"] and job["context_km"] > 0:
        ring = far_ring(job, canvas, job["context_km"] * 1000.0, args.far_dicing)

    # camera ortografica de cima, enquadrando so o nucleo
    cam_data = bpy.data.cameras.new("camera")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = max(job["core_x"], job["core_y"]) / UNIT_PX
    z_cam = Z_MAX / UNIT_M * E + 10.0          # acima do maior deslocamento possivel
    cam_data.clip_start = 0.1
    cam_data.clip_end = z_cam + 50.0
    cam = bpy.data.objects.new("camera", cam_data)
    cam.location = (0.0, 0.0, z_cam)
    scene.collection.objects.link(cam)
    scene.camera = cam

    sun_data = bpy.data.lights.new("sun", "SUN")
    sun_data.energy = args.sun_strength
    sun_data.angle = math.radians(args.sun_angle)
    sun = bpy.data.objects.new("sun", sun_data)
    sun.rotation_euler = sun_rotation(args.sun_azimuth, args.sun_elevation)
    scene.collection.objects.link(sun)

    world = bpy.data.worlds.new("world")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.050876, 0.050876, 0.050876, 1.0)
    bg.inputs["Strength"].default_value = 1.0
    scene.world = world

    scene.render.engine = "CYCLES"
    scene.cycles.feature_set = "EXPERIMENTAL"      # subdivisao adaptativa
    scene.cycles.device = "CPU"
    scene.cycles.samples = args.samples
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.use_denoising = True
    scene.cycles.denoiser = "OPENIMAGEDENOISE"
    scene.cycles.dicing_rate = 1.0
    scene.cycles.offscreen_dicing_scale = OFFSCREEN_DICING
    scene.cycles.max_subdivisions = 12
    scene.cycles.max_bounces = 4
    scene.cycles.diffuse_bounces = 2
    scene.cycles.glossy_bounces = 0
    scene.cycles.transmission_bounces = 0
    scene.cycles.volume_bounces = 0
    scene.cycles.tile_size = 2048
    scene.render.threads_mode = "AUTO"

    scene.render.resolution_x = job["core_x"]
    scene.render.resolution_y = job["core_y"]
    scene.render.resolution_percentage = 100
    scene.render.use_border = False
    scene.render.use_crop_to_border = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "BW"
    scene.render.image_settings.color_depth = "16"
    scene.render.image_settings.compression = 15
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = args.exposure
    scene.view_settings.gamma = 1.0
    scene.render.film_transparent = False
    return scene, ring


# saida ------------------------------------------------------------------------------

def write_pgw(png, job):
    # world file do nucleo: pixel, rotacoes, -pixel, centro do pixel superior esquerdo
    x0 = job["cx"] - job["core_x"] * RES / 2 + RES / 2
    y0 = job["cy"] + job["core_y"] * RES / 2 - RES / 2
    png.with_suffix(".pgw").write_text(f"{RES:.6f}\n0\n0\n{-RES:.6f}\n{x0:.6f}\n{y0:.6f}\n",
                                       encoding="ascii")


def append_log(path, row):
    new = not path.exists()
    with open(path, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        if new:
            w.writerow(list(row.keys()))
        w.writerow([str(v).replace(".", ",") if isinstance(v, float) else v for v in row.values()])


def fmt_time(s):
    return f"{s:.0f} s" if s < 120 else (f"{s / 60:.0f} min" if s < 5400 else f"{s / 3600:.1f} h")


def style_name(args):
    tag = lambda v: f"{v:g}".replace(".", "p").replace("-", "m")
    return (f"h128_8_s2000_az{tag(args.sun_azimuth)}_el{tag(args.sun_elevation)}"
            f"_ang{tag(args.sun_angle)}_ctx{tag(args.context_km)}_fd{tag(args.far_dicing)}")


# execucao ---------------------------------------------------------------------------

def main():
    args = parse_args()
    canvas = read_canvas()
    if not FAR_PNG.exists():
        sys.exit(f"falta {FAR_PNG}: rode o 06 --stage national")

    if args.mode == "test":
        jobs = json.loads((DIR_06 / "tables" / "test_jobs.json").read_text())
        if args.context_km is not None:
            # teste extra (log 16): repete os jobs de 600 km (janelas m1024 e
            # m2048 e os pares de emenda) com outro alcance. 5000 km = canvas
            # inteiro, porque o anel e recortado no canvas (4.424 km de lado)
            tag = f"_c{args.context_km:g}"
            jobs = [dict(j, id=j["id"].replace("_c600", tag), context_km=args.context_km)
                    for j in jobs if j["id"].endswith("_c600")]
        if args.only:
            jobs = [j for j in jobs if j["id"] in set(args.only)]
        out_dir = DIR_07 / "test"
        for j in jobs:
            j["out"] = out_dir / f"{j['id']}.png"
    else:
        if args.context_km is None:
            sys.exit("--context-km e obrigatorio no --mode full (sai do --mode test, log 15)")
        out_dir = DIR_07 / style_name(args)
        bp = int(canvas["block_px"])
        jobs = []
        for b in read_blocks():
            if not b["has_brazil"] or (args.blocks and b["block_id"] not in set(args.blocks)):
                continue
            n = bp + 2 * BLOCK_MARGIN
            jobs.append(dict(id=b["block_id"],
                             height=str(DIR_06 / "heightmaps" / f"hybrid_{b['block_id']}.png"),
                             nx=n, ny=n, core_x=bp, core_y=bp,
                             cx=(b["core_xmin"] + b["core_xmax"]) / 2,
                             cy=(b["core_ymin"] + b["core_ymax"]) / 2,
                             context_km=args.context_km,
                             out=out_dir / f"relief_{b['block_id']}.png"))
    out_dir.mkdir(parents=True, exist_ok=True)
    for j in jobs:
        if not Path(j["height"]).exists():
            sys.exit(f"falta o heightmap {j['height']}: rode o 06 (--stage {args.mode if args.mode == 'test' else 'blocks'})")

    print(f"\n# 07 render {'-' * 64}")
    print(f"modo {args.mode}: {len(jobs)} renders em {out_dir}")
    print(f"sol az {args.sun_azimuth:g} el {args.sun_elevation:g} diametro {args.sun_angle:g}"
          f" forca {args.sun_strength:g}; exposicao {args.exposure:g}; {args.samples} amostras;"
          f" E {E:g} sobre o z hibrido; anel distante com dicing x{args.far_dicing:g}")

    t_start, times = time.time(), []
    for i, j in enumerate(jobs, 1):
        out = Path(j["out"])
        if out.exists() and not args.overwrite:
            print(f"[{i}/{len(jobs)}] {j['id']} ja existe")
            continue
        t0 = time.time()
        scene, ring = build_scene(j, canvas, args)
        t_scene = time.time() - t0
        scene.render.filepath = str(out)
        bpy.ops.render.render(write_still=True)
        dt = time.time() - t0
        times.append(dt)
        write_pgw(out, j)
        append_log(out_dir / "render_log.csv", {
            "id": j["id"], "core_x": j["core_x"], "core_y": j["core_y"], "nx": j["nx"], "ny": j["ny"],
            "context_km": float(j["context_km"] or 0), "far_faces": len(ring.data.polygons) if ring else 0,
            "far_dicing": float(args.far_dicing), "samples": args.samples,
            "seconds_scene": round(t_scene, 1), "seconds": round(dt, 1), "file": str(out)})
        left = sum(1 for k in jobs[i:] if not Path(k["out"]).exists() or args.overwrite)
        print(f"[{i}/{len(jobs)}] {j['id']}: {fmt_time(dt)} | falta ~{fmt_time(left * sum(times) / len(times))}",
              flush=True)
    print(f"\nfim em {fmt_time(time.time() - t_start)}")


if __name__ == "__main__":
    main()
