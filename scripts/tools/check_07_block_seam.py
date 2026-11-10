# check_07_block_seam.py -----------------------------------------------------
# confere a emenda entre dois blocos vizinhos do 07 --mode full contra o
# render unico da mesma area (seam_ew_joint / seam_ns_joint do --mode test,
# anel do canvas inteiro). So le; imprime e grava uma folha png.
#   python check_07_block_seam.py              (r12_c12 | r12_c13, seam_ew)
#   python check_07_block_seam.py r11_c13 r12_c13 seam_ns
# Diferencas em niveis de 8 bits. O que importa: o salto assinado na linha
# da emenda e a diferenca de vies entre os dois lados (um bloco mais claro
# que o outro); o vies comum aos dois lados (bloco inteiro x teste pequeno)
# nao vira emenda.

import sys
from pathlib import Path

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
D7 = Path(r"D:\usuario_armazenamento\cassio\projects\brazil_shaded_relief_maps\data\intermediate\07_hybrid_renders")
STYLE = "h128_8_s2000_az315_el45_ang90_ctx5000_fd1"
OUT = D7 / "test_check"

a_id, b_id, seam = (sys.argv[1:4] if len(sys.argv) >= 4 else ("r12_c12", "r12_c13", "seam_ew"))
axis = 1 if seam == "seam_ew" else 0          # emenda vertical (L-O) ou horizontal (N-S)


def read(png):
    a = np.asarray(Image.open(png), dtype=np.float64) / 65535 * 255
    v = [float(x) for x in Path(png).with_suffix(".pgw").read_text().split()]
    return a, v[4] - v[0] / 2, v[5] - v[3] / 2  # imagem, x e y do canto superior esquerdo


j, xj, yj = read(D7 / "test" / f"{seam}_joint_m1024_c5000.png")
mos = np.full_like(j, np.nan)
for bid in (a_id, b_id):
    b, xb, yb = read(D7 / STYLE / f"relief_{bid}.png")
    r0, c0 = int(round((yb - yj) / -30)), int(round((xb - xj) / 30))
    # parte do bloco dentro da janela do joint
    rr0, rr1 = max(0, r0), min(j.shape[0], r0 + b.shape[0])
    cc0, cc1 = max(0, c0), min(j.shape[1], c0 + b.shape[1])
    mos[rr0:rr1, cc0:cc1] = b[rr0 - r0:rr1 - r0, cc0 - c0:cc1 - c0]
assert not np.isnan(mos).any(), "os dois blocos nao cobrem a janela do joint"

n = j.shape[axis] // 2                       # a linha da emenda fica no meio do joint
d = mos - j
side_a = d.take(range(0, n), axis=axis)
side_b = d.take(range(n, j.shape[axis]), axis=axis)
step_m = (mos.take(n, axis=axis) - mos.take(n - 1, axis=axis))
step_j = (j.take(n, axis=axis) - j.take(n - 1, axis=axis))
print(f"{a_id} | {b_id} contra {seam}_joint (c5000), {j.shape[1]} x {j.shape[0]} px")
print(f"  vies lado {a_id}: {side_a.mean():.2f} | lado {b_id}: {side_b.mean():.2f} | diferenca entre lados: {side_a.mean() - side_b.mean():.2f}")
print(f"  MAE: {np.abs(d).mean():.2f}")
print(f"  salto assinado na emenda: blocos {step_m.mean():.2f} | render unico {step_j.mean():.2f}")
print(f"  salto sem sinal na emenda: blocos {np.abs(step_m).mean():.2f} | render unico {np.abs(step_j).mean():.2f}")
# folha: 512 px de cada lado da emenda, no meio do outro eixo
sl = [slice(None), slice(None)]
sl[axis] = slice(n - 512, n + 512)
mid = j.shape[1 - axis] // 2
sl[1 - axis] = slice(mid - 512, mid + 512)
to8 = lambda x: np.clip(np.round(x), 0, 255).astype(np.uint8)
sheet = np.hstack([to8(mos[tuple(sl)]), to8(j[tuple(sl)]), to8(128 + 8 * d[tuple(sl)])])
OUT.mkdir(parents=True, exist_ok=True)
f = OUT / f"blocks_{a_id}_{b_id}_vs_{seam}.png"
Image.fromarray(sheet).save(f)
print("  folha:", f)
