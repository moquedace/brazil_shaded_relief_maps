# brazil_shaded_relief_maps - 05 compoe o sombreado do blender com as cores ---
#
# entrada (somente leitura):
#   data/intermediate/04_relief_renders/[test|pilot/]e<E>_<estilo>/relief_rRR_cCC.png
#     sombreado do Blender, png 16 bits, so o nucleo do bloco (8192 px a 30 m);
#     o render do Brasil inteiro (04 --mode full) fica direto em 04_relief_renders
#   data/intermediate/02_prepared_dem/raster/gedtm30_v1_2_brazil_5880_30m.tif
#     altitude para a hipsometria
#   data/intermediate/03_thematic/raster/<tema>/<tema>_rRR_cCC.tif + tables/
#     classes de geologia, solos e paises, com as cores
#
# saida: data/intermediate/05_compose/<test|pilot|soft>/
#   figures/<bloco>_<tema>.png      uma folha por bloco e tema: uma linha por
#                                   variante (exagero x gama), com o bloco
#                                   inteiro a 480 m e um detalhe a 30 m
#   figures/overview_<tema>.png     todos os blocos x todas as variantes a 480 m
#   figures/seam_hypsometry.png     emenda de dois blocos vizinhos a 30 m
#   tables/shade_check.csv          cinza do plano, encostas estouradas e area
#                                   escurecida a 480 m, por variante
# no modo preview, em data/intermediate/05_compose/preview/:
#   raster/brazil_<tema>_<variante>_480m.tif   mosaico RGB do canvas inteiro
#   figures/brazil_<tema>_<variante>_480m.png  o mesmo em png (9216 px)
#   figures/brazil_compare_<tema>.png          as variantes lado a lado, Brasil
#                                              inteiro a 2,9 km
#   figures/regions_compare_<tema>.png         as variantes lado a lado em 4
#                                              janelas de ~490 km, a 480 m
#   tables/shade_check.csv + shade_summary.csv  por bloco e no Brasil inteiro
#
# modos de escolha do exagero (logs 11 e 12):
#   test   os 6 blocos de TEST_BLOCKS do 04 (--mode test), E = 1, 2, 4 e 8
#   soft   os mesmos 6 renders: E4 e E8 sem suavizar e E8 com gama 0,7 e 0,5
#          (sombra clareada no 05, sem renderizar de novo), com a sombra do
#          plano fixa, como no mapa inteiro
#   pilot  o bloco do piloto do 04 (r11_c13, heightmap antigo), E = 1, 2 e 4
# modo do mapa inteiro, primeira etapa (log 14):
#   preview  os 183 renders E8 do Brasil (04 --mode full) com gama 1, 0,7 e
#            0,5, a 480 m, para escolher o gama olhando o Brasil inteiro. Os
#            blocos sem Brasil (sem render) saem com mar e vizinhos chapados.
#            preview_pilot = TRUE roda so 12 blocos do Sudeste, para conferir
#            o codigo e medir o tempo antes da rodada inteira
# a composicao final a 30 m, com legenda, barras de area e escala, entra
# depois de escolhido o gama.
#
# composicao (como o "multiply" do Huffman, mas sem estourar o branco):
#   k = (sombra / sombra_do_plano)^gama, 1 no chao plano; gama < 1 clareia a
#     sombra e apaga um pouco o brilho das encostas ao sol
#   k <= 1 (encosta na sombra): cor x k
#   k > 1 (encosta de frente para o sol): cor clareada para o branco, em
#     proporcao a k, sem mudar o matiz (multiplicar acima de 1 estouraria um
#     canal antes dos outros)
#   sombra_do_plano: mediana da sombra nos pixels do Brasil com declividade
#     abaixo de flat_slope_deg, medida em cada render (~0,73 com a exposicao
#     -0,5 do 04; ~0,86 no piloto, renderizado com exposicao 0), ou um valor
#     fixo para todos os blocos (shade_flat_fixed; obrigatorio no mapa
#     inteiro, log 12)
#
# por que duas escalas: a 480 m (o mapa do Brasil inteiro impresso em A0 tem
#   ~450 m por pixel) a media de 256 pixels apaga o relevo miudo das
#   planicies; a 30 m aparecem as sombras longas e os defeitos do DTM. O
#   exagero tem de servir as duas
#
# cores: hipsometria em rampa aproximada do mapa de elevacao da Souza (2020,
#   fig. 1); geologia e solos das tabelas do 03 (Lamego 1960 e SiBCS 2025,
#   Anexo I); vizinhos em cinza claro com sombreado; mar liso
#
# rodar (R, na maquina local GEOCARBONX; nao junto com o Blender):
#   source("D:/usuario_armazenamento/cassio/projects/brazil_shaded_relief_maps/scripts/05_compose_maps.R")

rm(list = ls())
gc()

suppressPackageStartupMessages({
  library(terra)
  library(sf)
  library(dplyr)
  library(readr)
  library(future)
  library(future.apply)
})

options(width = 200, scipen = 999)

# configuracao ---------------------------------------------------------------

run_mode        <- "preview"        # "pilot" (r11_c13), "test" (6 blocos do 04 --mode test), "soft" (E8 suavizado, mesmos renders do test) ou "preview" (Brasil inteiro em E8 a 480 m)
preview_pilot   <- FALSE            # preview: TRUE = so 12 blocos do Sudeste (conferir e medir o tempo); FALSE = os 324
n_workers       <- if (run_mode == "preview") 8 else 3   # um bloco por worker (~5 GB de RAM cada; 8 x 5 = 40 GB dos ~46 livres); nunca com o Blender aberto
style_tag       <- "az315_el45_p100"
detail_px       <- 1024             # janela do detalhe a 30 m (30,7 km)
overview_factor <- 16               # bloco inteiro a 480 m (512 px)
flat_slope_deg  <- 0.3              # declividade maxima do "chao plano"

# o soft le os renders do test; o preview, os do Brasil inteiro (04 --mode full)
render_mode <- switch(run_mode, soft = "test", preview = "full", run_mode)

# variantes: exagero do render (E) x contraste do sombreado (gama). Gama < 1
# clareia a sombra no 05, sem renderizar de novo; a area coberta pela sombra
# e o granulado do DTM continuam os do render. No soft, gama 0,7 deixa a
# sombra mais escura das serras em E8 (p01 0,31) mais ou menos tao escura
# quanto em E4 sem suavizar (p01 0,40): 0,416^0,7 = 0,54 (log 12)
variants <- list(
  pilot   = tibble(e = c(1, 2, 4), gamma = 1),
  test    = tibble(e = c(1, 2, 4, 8), gamma = 1),
  soft    = tibble(e = c(4, 8, 8, 8), gamma = c(1, 1, 0.7, 0.5)),
  # o Brasil foi renderizado em E8 (log 13); o gama sai daqui (log 14)
  preview = tibble(e = 8, gamma = c(1, 0.7, 0.5))
)[[run_mode]] %>%
  mutate(id    = sprintf("e%g_g%g", e, gamma),
         label = ifelse(gamma == 1, sprintf("E %g", e),
                        sprintf("E %g, gama %s", e, format(gamma, decimal.mark = ","))))
exaggerations <- sort(unique(variants$e))

# sombra do plano: NA mede em cada render (diagnostico do test e do pilot);
# um valor fixo vale para todos os blocos, como no mapa inteiro. Normalizar
# cada bloco pelo proprio plano deu um salto de 3,5 niveis na emenda em E8,
# porque a sombra das serras cobre o plano ao pe delas (0,705 no r12_c13 x
# 0,728 no r12_c12). 0,735 e o plano dos 4 blocos de planicie em todos os
# exageros, com a exposicao -0,5 do 04 (log 12)
shade_flat_fixed <- list(pilot = NA, test = NA, soft = 0.735, preview = 0.735)[[run_mode]]

# blocos do piloto do preview: Sudeste (Mantiqueira, Serra do Mar, Sul de
# Minas e o mar ao lado), com as 2 emendas do teste
preview_pilot_blocks <- sprintf("r%02d_c%02d", rep(11:13, each = 4), rep(11:14, 3))

# janelas de comparacao do preview a 480 m (centro em lon/lat, 1024 px =
# 492 km): serras do Sudeste, Serra Geral, Amazonia central e Chapada
# Diamantina/Espinhaco
compare_windows <- tribble(
  ~window,                              ~lon,   ~lat,
  "Mantiqueira e Serra do Mar",         -45.0,  -22.5,
  "Aparados e Serra Geral",             -50.5,  -28.8,
  "Amazonia central (Manaus)",          -60.0,   -3.5,
  "Chapada Diamantina e Espinhaco",     -41.8,  -12.8
)

# blocos e lugar do detalhe (lon/lat; a janela e recortada dentro do bloco)
sites <- list(
  test = tribble(
    ~block_id, ~site,                         ~detail,                        ~lon,   ~lat,
    "r12_c13", "Mantiqueira e Serra do Mar",  "Itatiaia",                     -44.67, -22.38,
    "r04_c06", "Amazonia central",            "rio Madeira em Borba",         -59.59,  -4.39,
    "r10_c08", "Pantanal",                    "planicie do Paiaguas",         -56.35, -17.50,
    "r02_c03", "Pico da Neblina",             "Pico da Neblina",              -66.00,   0.80,
    "r15_c10", "Aparados da Serra",           "canion do Itaimbezinho",       -50.08, -29.17,
    "r12_c12", "Sul de Minas",                "caldeira de Pocos de Caldas",  -46.57, -21.84
  ),
  pilot = tribble(
    ~block_id, ~site,                         ~detail,                        ~lon,   ~lat,
    "r11_c13", "Quadrilatero Ferrifero",      "Serra do Curral e Moeda",      -43.95, -20.10
  )
)[[render_mode]]

# emenda: bloco da esquerda, bloco da direita e latitude do centro da janela
seam <- list(test = list(left = "r12_c12", right = "r12_c13", lon = -44.84, lat = -22.43,
                         label = "Pedra da Mina, ~4 km a leste da emenda"),
             pilot = NULL)[[render_mode]]

# rampa hipsometrica: cores aproximadas do mapa de elevacao da Souza (2020),
# amostradas nas faces iluminadas (foz do Amazonas, Amazonia, Acre, Mato
# Grosso, Minas) e ajustadas a altitude do GEDTM30. Primeira versao, para o
# teste do exagero
hypso <- tribble(
  ~z_m,  ~color,
  0,     "#1f8fa0",
  20,    "#1e9a5a",
  100,   "#2ea043",
  200,   "#6db34a",
  300,   "#b5b85c",
  500,   "#d9c37a",
  700,   "#d39a4f",
  900,   "#b9643a",
  1200,  "#93391f",
  1600,  "#6e2416",
  3000,  "#4c1a10"
)

color_sea      <- "#dbe9f2"         # mar, sem sombreado
color_neighbor <- "#e4e2dc"         # outros paises, com sombreado
color_nodata   <- "#dfe8ee"         # Brasil sem classe (rios largos e represas na geologia)

themes <- c("hypsometry", "geology", "soil_orders")
theme_label <- c(hypsometry = "hipsometria", geology = "geologia (Lamego 1960)",
                 soil_orders = "solos, ordens (SiBCS 2025)")

# pastas ---------------------------------------------------------------------

project_root <- c(
  "D:/usuario_armazenamento/cassio/projects/brazil_shaded_relief_maps",
  "//192.168.0.5/usuario_armazenamento/cassio/projects/brazil_shaded_relief_maps"
)
project_root <- project_root[dir.exists(project_root)][1]
if (is.na(project_root)) stop("Pasta do projeto não encontrada.", call. = FALSE)

dir_int    <- file.path(project_root, "data", "intermediate")
dir_render <- file.path(dir_int, "04_relief_renders")
if (render_mode != "full") dir_render <- file.path(dir_render, render_mode)
dir_03     <- file.path(dir_int, "03_thematic")
dem_file   <- file.path(dir_int, "02_prepared_dem", "raster", "gedtm30_v1_2_brazil_5880_30m.tif")
dir_out    <- file.path(dir_int, "05_compose", run_mode)
dir_fig    <- file.path(dir_out, "figures")
dir_tab    <- file.path(dir_out, "tables")
dir_tmp    <- file.path(dir_int, "05_compose", "tmp")
for (d in c(dir_fig, dir_tab, dir_tmp)) dir.create(d, recursive = TRUE, showWarnings = FALSE)

# temporarios do terra no D:, nunca no temp do Windows (C:)
terraOptions(tempdir = dir_tmp, progress = 0)

write_table <- function(x, name) {
  f <- file.path(dir_tab, paste0(name, ".csv"))
  write_excel_csv2(x, f, na = "")
  cat("gravado:", f, "\n")
  invisible(f)
}
fmt_time <- function(s) {
  if (s < 120) sprintf("%.0f s", s) else if (s < 5400) sprintf("%.0f min", s / 60)
  else sprintf("%.1f h", s / 3600)
}

# grade, blocos e cores ------------------------------------------------------

canvas <- read_delim(file.path(project_root, "config", "canvas_5880.csv"),
                     delim = ";", locale = locale(decimal_mark = ",", grouping_mark = "."),
                     show_col_types = FALSE, progress = FALSE)
res     <- canvas$res_m
bp      <- canvas$block_px
crs_map <- canvas$crs

# preview: todos os blocos da grade do 02; so os que tem Brasil tem render
if (run_mode == "preview") {
  sites <- read_delim(file.path(dir_int, "02_prepared_dem", "tables", "heightmap_blocks.csv"),
                      delim = ";", show_col_types = FALSE, progress = FALSE) %>%
    transmute(block_id, site = block_id, has_render = as.logical(has_brazil))
  if (preview_pilot) sites <- filter(sites, block_id %in% preview_pilot_blocks)
  stopifnot(nrow(sites) == if (preview_pilot) length(preview_pilot_blocks)
            else canvas$nblock_x * canvas$nblock_y, !anyNA(sites$has_render))
} else {
  sites <- mutate(sites, has_render = TRUE)
}

sites <- sites %>%
  mutate(row = as.integer(substr(block_id, 2, 3)),
         col = as.integer(substr(block_id, 6, 7)),
         xmin = canvas$xmin + col * bp * res,
         xmax = xmin + bp * res,
         ymax = canvas$ymax - row * bp * res,
         ymin = ymax - bp * res)
if ("lon" %in% names(sites)) {
  xy <- st_coordinates(st_transform(st_as_sf(sites, coords = c("lon", "lat"), crs = 4326), crs_map))
  sites$x <- xy[, 1]
  sites$y <- xy[, 2]
} else {
  sites$x <- NA_real_
  sites$y <- NA_real_
}

renders <- expand.grid(block_id = sites$block_id[sites$has_render], e = exaggerations,
                       stringsAsFactors = FALSE) %>%
  as_tibble() %>%
  mutate(file = file.path(dir_render, sprintf("e%g_%s", e, style_tag),
                          paste0("relief_", block_id, ".png")))
miss <- renders$file[!file.exists(renders$file)]
if (length(miss)) {
  stop("render do 04 nao encontrado (", length(miss), "): ", paste(basename(dirname(miss)),
       basename(miss), sep = "/", collapse = ", "), call. = FALSE)
}

read_classes <- function(theme) {
  read_delim(file.path(dir_03, "tables", paste0(theme, "_classes.csv")), delim = ";",
             locale = locale(decimal_mark = ","), show_col_types = FALSE, progress = FALSE)
}
hex2rgb <- function(h) t(col2rgb(h)) / 255

# tabela de cores por codigo de classe (posicao 1 = classe 0)
class_lut <- function(class_id, color) {
  lut <- matrix(rep(hex2rgb(color_nodata), each = 256), ncol = 3)
  lut[class_id + 1, ] <- hex2rgb(color)
  lut
}
cls_geo  <- read_classes("geology")
cls_soil <- read_classes("soil")
if ("#0184e9" %in% tolower(cls_geo$color)) {
  stop("tabela de geologia ainda com as cores antigas: rode o 03 de novo (log 11)", call. = FALSE)
}
luts <- list(
  geology     = class_lut(cls_geo$class_id, cls_geo$color),
  soil_orders = class_lut(cls_soil$class_id, cls_soil$color_order)
)
# hipsometria: uma cor por metro de 0 a 3000 m, interpolada no espaco Lab
ramp <- colorRamp(hypso$color, space = "Lab")
pos  <- approx(hypso$z_m, seq(0, 1, length.out = nrow(hypso)), xout = 0:3000)$y
luts$hypsometry <- ramp(pos) / 255
# ultima linha de cada tabela: o cinza dos outros paises
luts <- lapply(luts, function(l) rbind(l, hex2rgb(color_neighbor)))

cat("\n# 05 composicao", strrep("-", 62), "\n")
cat(sprintf("modo %s%s: %d blocos (%d com render) x %d variantes (%s) x %d temas; renders em %s\n",
            run_mode, if (run_mode == "preview" && preview_pilot) " (piloto)" else "",
            nrow(sites), sum(sites$has_render), nrow(variants),
            paste(variants$label, collapse = " | "), length(themes), dir_render))
cat(sprintf("sombra do plano: %s\n", if (is.na(shade_flat_fixed)) "medida em cada render"
            else sprintf("fixa em %s para todos os blocos", format(shade_flat_fixed, decimal.mark = ","))))
cat(sprintf("geologia: %s\n", paste(cls_geo$code, cls_geo$color, collapse = ", ")))

# composicao de um bloco -----------------------------------------------------

# memoria: um canal de cor por vez (cada vetor de 8192^2 em double tem 537 MB;
# os 3 temas x 3 canais inteiros de uma vez dariam ~10 GB por worker)
compose_block <- function(s, variants, renders, luts, args) {
  suppressPackageStartupMessages(library(terra))
  terraOptions(tempdir = args$dir_tmp, progress = 0)
  bp <- args$bp
  e_blk <- ext(s$xmin, s$xmax, s$ymin, s$ymax)
  # crs explicito: sem ele o terra pode tomar a grade por graus e errar a
  # declividade
  as_rast <- function(v) rast(nrows = bp, ncols = bp, extent = e_blk, crs = args$crs, vals = v)

  # celulas em ordem de linha (a ordem do terra) de uma janela do bloco
  win_cells <- function(r0, c0, nr, nc) as.vector(outer(c0:(c0 + nc - 1), (r0:(r0 + nr - 1) - 1) * bp, "+"))
  clamp <- function(v, lo, hi) min(max(v, lo), hi)
  # canal em 0-1 (ordem de linha) -> matriz h x w de bytes, para a folha
  to_bytes <- function(v, h, w) matrix(as.raw(as.integer(round(v * 255))), h, w, byrow = TRUE)
  ov_n <- bp / args$overview_factor

  # media em janelas f x f de um canal do bloco (bp x bp, ordem de linha) ->
  # (bp / f) x (bp / f), tambem em ordem de linha. Faz o mesmo que
  # aggregate(fun = "mean") do terra, sem raster nem arquivo temporario
  # (conferido contra o terra em todo bloco, abaixo)
  block_mean <- function(v, f = args$overview_factor) {
    n <- bp / f
    dim(v) <- c(f, n * bp)                       # [coluna na janela, (janela, linha)]
    v <- colSums(v)
    dim(v) <- c(n, f, n)                         # [janela, linha na janela, linha da janela]
    as.vector(colSums(aperm(v, c(2, 1, 3)))) / f^2
  }

  rd <- function(theme) {
    v <- values(rast(file.path(args$dir_03, "raster", theme, sprintf("%s_%s.tif", theme, s$block_id))),
                mat = FALSE)
    v[is.na(v)] <- 0L
    as.integer(v)
  }
  cty <- rd("country")
  stopifnot(length(cty) == bp^2)
  sea <- which(cty == 0)
  rgb_sea <- col2rgb(args$color_sea)[, 1] / 255
  out <- list(tiles = setNames(rep(list(list()), length(luts)), names(luts)),
              seam = list(), check = list())

  # bloco sem Brasil (sem render, so no preview): mar e vizinhos chapados,
  # iguais nos 3 temas e em todas as variantes
  rr <- renders[renders$block_id == s$block_id, ]
  if (nrow(rr) == 0) {
    if (any(cty == 1)) stop("bloco com Brasil sem render: ", s$block_id, call. = FALSE)
    rgb_nb <- col2rgb(args$color_neighbor)[, 1] / 255
    ovw <- array(as.raw(0), c(ov_n, ov_n, 3))
    for (j in 1:3) {
      ch <- rep(rgb_nb[j], bp^2)
      ch[sea] <- rgb_sea[j]
      ovw[, , j] <- to_bytes(block_mean(ch), ov_n, ov_n)
    }
    for (th in names(luts)) for (id in variants$id) out$tiles[[th]][[id]] <- list(overview = ovw)
    out$check <- NULL
    return(out)
  }

  # altitude do bloco
  dem <- rast(args$dem_file)
  window(dem) <- e_blk
  z <- values(dem, mat = FALSE)
  window(dem) <- NULL
  # indice de cor de cada pixel em cada tema (linha da tabela de cores); os
  # vizinhos levam a ultima linha, a do cinza dos outros paises
  idx <- list(
    hypsometry  = as.integer(pmin(pmax(round(ifelse(is.na(z), 0, z)), 0), 3000)) + 1L,
    geology     = rd("geology") + 1L,
    soil_orders = rd("soil") + 1L
  )
  stopifnot(length(z) == bp^2, all(lengths(idx) == bp^2))
  nb  <- which(cty == 2)
  for (th in names(idx)) idx[[th]][nb] <- nrow(luts[[th]])

  # chao plano: declividade a 30 m abaixo do limite, so no Brasil
  slope <- values(terrain(as_rast(z), v = "slope", unit = "degrees"), mat = FALSE)
  flat <- which(cty == 1 & !is.na(slope) & slope < args$flat_slope_deg)
  rm(slope, z)
  # celulas de 480 m quase todas no Brasil (> 99%), para medir a area
  # escurecida sem contar mar e vizinhos. A mesma media pelo terra confere a
  # ordem das celulas do block_mean neste bloco
  br_frac <- block_mean(as.numeric(cty == 1))
  br_terra <- values(aggregate(as_rast(as.numeric(cty == 1)), args$overview_factor, "mean"),
                     mat = FALSE)
  if (max(abs(br_frac - br_terra)) > 1e-9) {
    stop("block_mean diferente do aggregate do terra em ", s$block_id, call. = FALSE)
  }
  br_ov <- br_frac > 0.99
  rm(br_terra)

  # janela do detalhe e, se o bloco for de uma emenda, a faixa da borda (o
  # preview nao tem detalhe)
  cells_detail <- NULL
  if (!is.na(s$x)) {
    r_site <- floor((s$ymax - s$y) / args$res) + 1
    c_site <- floor((s$x - s$xmin) / args$res) + 1
    r0 <- clamp(r_site - args$detail_px / 2, 1, bp - args$detail_px + 1)
    c0 <- clamp(c_site - args$detail_px / 2, 1, bp - args$detail_px + 1)
    cells_detail <- win_cells(r0, c0, args$detail_px, args$detail_px)
  }
  cells_seam <- NULL
  if (!is.null(args$seam) && s$block_id %in% c(args$seam$left, args$seam$right)) {
    r_seam <- clamp(floor((s$ymax - args$seam$y) / args$res) + 1 - args$detail_px / 2,
                    1, bp - args$detail_px + 1)
    half <- args$detail_px / 2
    c_seam <- if (s$block_id == args$seam$left) bp - half + 1 else 1
    cells_seam <- win_cells(r_seam, c_seam, args$detail_px, half)
  }

  for (i in seq_len(nrow(rr))) {
    sh <- rast(rr$file[i])
    # o render tem de ser o nucleo deste bloco, na mesma grade (o terra le o
    # world file .pgw que o 04 grava ao lado do png)
    if (nrow(sh) != bp || ncol(sh) != bp ||
        any(abs(as.vector(ext(sh)) - as.vector(e_blk)) > 1e-3)) {
      stop("render fora da grade do bloco (falta o .pgw?): ", rr$file[i], call. = FALSE)
    }
    v <- values(sh, mat = FALSE) / 65535
    rm(sh)
    # com o plano fixo (soft, preview), o plano medido e so conferencia: os
    # blocos de borda com uma lasca de Brasil ficam sem medida (NA)
    s_meas <- if (length(flat) >= 10000) median(v[flat]) else NA_real_
    if (is.na(s_meas) && is.na(args$shade_flat_fixed)) {
      stop("menos de 10.000 pixels planos em ", s$block_id, call. = FALSE)
    }
    s_flat <- if (is.na(args$shade_flat_fixed)) s_meas else args$shade_flat_fixed
    pct_clip <- 100 * mean(v >= 65280 / 65535)
    q <- unname(quantile(v, c(0.01, 0.99)))
    vv <- variants[variants$e == rr$e[i], ]
    for (iv in seq_len(nrow(vv))) {
      id <- vv$id[iv]
      k <- (v / s_flat)^vv$gamma[iv]
      # brilho medio a 480 m em relacao ao plano (1 = plano), so nas celulas
      # do Brasil: a parte do bloco mais de 20% e mais de 40% mais escura
      ka <- block_mean(k)[br_ov]
      out$check[[length(out$check) + 1]] <- data.frame(
        block_id = s$block_id, variant = id, exaggeration = vv$e[iv], gamma = vv$gamma[iv],
        shade_flat = s_meas, shade_flat_used = s_flat, n_flat_px = length(flat),
        pct_clipped = pct_clip, shade_p01 = q[1], shade_p99 = q[2],
        n_cells_480m = length(ka), n_dark20_480m = sum(ka < 0.8), n_dark40_480m = sum(ka < 0.6),
        pct_dark20_480m = 100 * mean(ka < 0.8), pct_dark40_480m = 100 * mean(ka < 0.6))
      k_max <- (1 / s_flat)^vv$gamma[iv]
      dark  <- pmin(k, 1)
      light <- pmax(k - 1, 0) / (k_max - 1)
      rm(k, ka)
      for (th in names(idx)) {
        det <- if (!is.null(cells_detail)) array(as.raw(0), c(args$detail_px, args$detail_px, 3))
        ovw <- array(as.raw(0), c(ov_n, ov_n, 3))
        sem <- if (th == "hypsometry" && !is.null(cells_seam)) {
          array(as.raw(0), c(args$detail_px, args$detail_px / 2, 3))
        }
        for (j in 1:3) {
          ch <- luts[[th]][idx[[th]], j] * dark
          ch <- ch + (1 - ch) * light
          ch[sea] <- rgb_sea[j]
          if (!is.null(det)) det[, , j] <- to_bytes(ch[cells_detail], args$detail_px, args$detail_px)
          if (!is.null(sem)) sem[, , j] <- to_bytes(ch[cells_seam], args$detail_px, args$detail_px / 2)
          ovw[, , j] <- to_bytes(block_mean(ch), ov_n, ov_n)
          rm(ch)
        }
        out$tiles[[th]][[id]] <- list(detail = det, overview = ovw)
        if (!is.null(sem)) out$seam[[id]] <- sem
      }
      rm(dark, light)
      gc()
      tmpFiles(remove = TRUE)
    }
    rm(v)
    gc()
  }
  out$check <- do.call(rbind, out$check)
  out
}

args <- list(bp = bp, res = res, crs = crs_map, dem_file = dem_file, dir_03 = dir_03,
             dir_tmp = dir_tmp, detail_px = detail_px, overview_factor = overview_factor,
             shade_flat_fixed = shade_flat_fixed, flat_slope_deg = flat_slope_deg,
             color_sea = color_sea, color_neighbor = color_neighbor, seam = NULL)
if (!is.null(seam)) {
  seam_y <- st_coordinates(st_transform(st_sfc(st_point(c(seam$lon, seam$lat)), crs = 4326),
                                        crs_map))[2]
  args$seam <- c(seam, y = seam_y)
}

t0 <- Sys.time()
nw <- min(n_workers, nrow(sites))
cat(sprintf("compondo %d blocos em %d workers\n", nrow(sites), nw))
plan(multisession, workers = nw)
# em lotes de 2 blocos por worker, para mostrar o andamento; os blocos com
# render (os demorados) primeiro, os sem Brasil (segundos) no fim
ord <- order(!sites$has_render)
chunks <- split(ord, ceiling(seq_along(ord) / (2 * nw)))
res_blocks <- vector("list", nrow(sites))
for (ci in seq_along(chunks)) {
  ii <- chunks[[ci]]
  res_blocks[ii] <- tryCatch(
    future_lapply(ii, function(i) {
      compose_block(sites[i, ], variants, renders, luts, args)
    }, future.seed = NULL),
    error = function(e) {
      plan(sequential)
      stop(conditionMessage(e), call. = FALSE)
    }
  )
  done <- unlist(chunks[seq_len(ci)])
  el <- as.numeric(difftime(Sys.time(), t0, units = "secs"))
  left <- sum(sites$has_render[-done])
  cat(sprintf("[%d/%d] %d blocos prontos em %s | faltam %d com render, ~%s\n", ci, length(chunks),
              length(done), fmt_time(el), left,
              fmt_time(el / max(sum(sites$has_render[done]), 1) * left)))
}
plan(sequential)
names(res_blocks) <- sites$block_id
cat(sprintf("composto em %s\n", fmt_time(as.numeric(difftime(Sys.time(), t0, units = "secs")))))

# conferencia do sombreado ---------------------------------------------------

shade_check <- bind_rows(lapply(res_blocks, `[[`, "check")) %>%
  as_tibble() %>%
  left_join(select(sites, block_id, site), by = "block_id") %>%
  relocate(site, .after = block_id)
write_table(shade_check, "shade_check")
if (run_mode == "preview") {
  # Brasil inteiro: a area escurecida e somada em celulas de 480 m; o plano
  # medido so vale nos blocos com bastante chao plano (>= 1 milhao de px)
  ok_flat <- shade_check$n_flat_px >= 1e6
  shade_summary <- shade_check %>%
    mutate(ok_flat = ok_flat) %>%
    group_by(variant, exaggeration, gamma) %>%
    summarise(n_blocks = n(),
              n_blocks_flat = sum(ok_flat),
              shade_flat_used = first(shade_flat_used),
              shade_flat_p10 = unname(quantile(shade_flat[ok_flat], 0.10)),
              shade_flat_median = median(shade_flat[ok_flat]),
              shade_flat_p90 = unname(quantile(shade_flat[ok_flat], 0.90)),
              n_blocks_flat_off = sum(ok_flat & abs(shade_flat - shade_flat_used) > 0.01),
              pct_clipped_max = max(pct_clipped),
              pct_dark20_480m = 100 * sum(n_dark20_480m) / sum(n_cells_480m),
              pct_dark40_480m = 100 * sum(n_dark40_480m) / sum(n_cells_480m),
              .groups = "drop") %>%
    arrange(desc(gamma))
  write_table(shade_summary, "shade_summary")
  cat("\nBrasil inteiro, por variante: plano medido (p10, mediana, p90 nos blocos com >= 1 milhao",
      "de px planos) contra o fixo, encostas estouradas e parte do Brasil a 480 m mais de 20% e",
      "mais de 40% escura que o plano:\n")
  print(as.data.frame(shade_summary %>% transmute(variante = variant, blocos = n_blocks,
                                                  blocos_plano = n_blocks_flat,
                                                  usado = shade_flat_used,
                                                  plano_p10 = round(shade_flat_p10, 3),
                                                  plano_med = round(shade_flat_median, 3),
                                                  plano_p90 = round(shade_flat_p90, 3),
                                                  fora_001 = n_blocks_flat_off,
                                                  estourado_max_pct = round(pct_clipped_max, 3),
                                                  escuro20_pct = round(pct_dark20_480m, 2),
                                                  escuro40_pct = round(pct_dark40_480m, 2))),
        row.names = FALSE)
  top <- shade_check %>%
    filter(variant == variants$id[1]) %>%
    arrange(desc(pct_dark40_480m)) %>%
    head(6) %>%
    pull(block_id)
  cat("\nos 6 blocos mais escuros em", variants$label[1], "(mais de 40% escuro a 480 m), nas 3 variantes:\n")
  print(as.data.frame(shade_check %>%
                        filter(block_id %in% top) %>%
                        arrange(match(block_id, top), desc(gamma)) %>%
                        transmute(block_id, variante = variant,
                                  plano = round(shade_flat, 3),
                                  escuro20_pct = round(pct_dark20_480m, 1),
                                  escuro40_pct = round(pct_dark40_480m, 1))),
        row.names = FALSE)
} else {
  print(as.data.frame(shade_check %>% transmute(block_id, variante = variant,
                                                plano = round(shade_flat, 3),
                                                usado = round(shade_flat_used, 3),
                                                estourado_pct = round(pct_clipped, 3),
                                                p01 = round(shade_p01, 3),
                                                p99 = round(shade_p99, 3),
                                                escuro20_pct = round(pct_dark20_480m, 1),
                                                escuro40_pct = round(pct_dark40_480m, 1))),
        row.names = FALSE)
}

# folhas ---------------------------------------------------------------------

# desenha arrays 0-255 numa folha em pixels (origem no canto superior esquerdo)
sheet_open <- function(file, w, h) {
  png(file, width = w, height = h)
  par(mar = c(0, 0, 0, 0))
  plot.new()
  plot.window(xlim = c(0, w), ylim = c(h, 0), xaxs = "i", yaxs = "i")
  rect(0, h, w, 0, col = "white", border = NA)
}
put <- function(a, x, y) {
  img <- array(as.integer(a), dim(a)) / 255   # bytes -> 0-1
  rasterImage(img, x, y + dim(a)[1], x + dim(a)[2], y, interpolate = FALSE)
}

lab_w <- 110
head_h <- 130
gap <- 12
ov_px <- bp / overview_factor

# folhas do test, soft e pilot
if (run_mode != "preview") {
  # uma folha por bloco e tema
  for (i in seq_len(nrow(sites))) {
    s <- sites[i, ]
    for (th in themes) {
      tl <- res_blocks[[s$block_id]]$tiles[[th]]
      w <- lab_w + ov_px + gap + detail_px + gap
      h <- head_h + nrow(variants) * (detail_px + gap)
      f <- file.path(dir_fig, sprintf("%s_%s.png", s$block_id, th))
      sheet_open(f, w, h)
      text(gap, 30, sprintf("%s  %s  |  %s", s$block_id, s$site, theme_label[[th]]),
           adj = c(0, 0.5), cex = 2.2, font = 2)
      text(lab_w, 85, sprintf("bloco inteiro a %d m (%d px)", res * overview_factor, ov_px),
           adj = c(0, 0.5), cex = 1.6)
      text(lab_w + ov_px + gap, 85, sprintf("detalhe a %d m: %s (%d px = %.1f km)", res, s$detail,
                                            detail_px, detail_px * res / 1000),
           adj = c(0, 0.5), cex = 1.6)
      for (k in seq_len(nrow(variants))) {
        id <- variants$id[k]
        y <- head_h + (k - 1) * (detail_px + gap)
        text(lab_w / 2, y + 40, paste0("E ", variants$e[k]), cex = 2.4, font = 2)
        if (variants$gamma[k] != 1) {
          text(lab_w / 2, y + 90, sprintf("gama\n%s", format(variants$gamma[k], decimal.mark = ",")),
               cex = 1.5)
        }
        put(tl[[id]]$overview, lab_w, y)
        put(tl[[id]]$detail, lab_w + ov_px + gap, y)
      }
      dev.off()
    }
    cat("folhas:", s$block_id, "\n")
  }

  # todos os blocos x variantes a 480 m, por tema
  for (th in themes) {
    w <- lab_w + nrow(variants) * (ov_px + gap)
    h <- head_h + nrow(sites) * (ov_px + gap + 40)
    f <- file.path(dir_fig, sprintf("overview_%s.png", th))
    sheet_open(f, w, h)
    text(gap, 30, sprintf("%s: blocos inteiros a %d m, por exagero", theme_label[[th]],
                          res * overview_factor), adj = c(0, 0.5), cex = 2.2, font = 2)
    for (k in seq_len(nrow(variants))) {
      text(lab_w + (k - 1) * (ov_px + gap) + ov_px / 2, 95, variants$label[k], cex = 2.2, font = 2)
    }
    for (i in seq_len(nrow(sites))) {
      y <- head_h + (i - 1) * (ov_px + gap + 40)
      text(lab_w, y + 18, sprintf("%s  %s", sites$block_id[i], sites$site[i]), adj = c(0, 0.5), cex = 1.6)
      for (k in seq_len(nrow(variants))) {
        put(res_blocks[[sites$block_id[i]]]$tiles[[th]][[variants$id[k]]]$overview,
            lab_w + (k - 1) * (ov_px + gap), y + 40)
      }
    }
    dev.off()
    cat("folha:", f, "\n")
  }

  # emenda entre dois blocos, a 30 m (sem marca: a costura, se houver, tem de
  # aparecer sozinha no meio da janela)
  if (!is.null(seam)) {
    w <- lab_w + nrow(variants) * (detail_px + gap)
    h <- head_h + detail_px + gap
    f <- file.path(dir_fig, "seam_hypsometry.png")
    sheet_open(f, w, h)
    text(gap, 30, sprintf("emenda %s | %s a %d m, no meio de cada janela (%s)", seam$left, seam$right,
                          res, seam$label), adj = c(0, 0.5), cex = 2.2, font = 2)
    for (k in seq_len(nrow(variants))) {
      id <- variants$id[k]
      x <- lab_w + (k - 1) * (detail_px + gap)
      text(x + detail_px / 2, 95, variants$label[k], cex = 2.2, font = 2)
      put(res_blocks[[seam$left]]$seam[[id]], x, head_h)
      put(res_blocks[[seam$right]]$seam[[id]], x + detail_px / 2, head_h)
    }
    dev.off()
    cat("folha:", f, "\n")
  }
}

# brasil inteiro a 480 m (preview) -------------------------------------------

if (run_mode == "preview") {
  dir_ras <- file.path(dir_out, "raster")
  dir.create(dir_ras, recursive = TRUE, showWarnings = FALSE)
  e_canvas <- ext(canvas$xmin, canvas$xmax, canvas$ymin, canvas$ymax)
  ny <- canvas$nblock_y * ov_px
  nx <- canvas$nblock_x * ov_px
  res_ov <- res * overview_factor
  win_px <- 1024                    # janela de comparacao: 1024 px a 480 m = 492 km
  small_f <- 6                      # Brasil inteiro na folha de comparacao: 1536 px a 2,88 km

  # mosaico do canvas a 480 m de um tema e variante: array ny x nx x 3 de
  # bytes (no piloto, os blocos que nao rodaram ficam em branco)
  mosaic <- function(th, id) {
    m <- array(as.raw(255), c(ny, nx, 3))
    for (i in seq_len(nrow(sites))) {
      m[sites$row[i] * ov_px + seq_len(ov_px), sites$col[i] * ov_px + seq_len(ov_px), ] <-
        res_blocks[[i]]$tiles[[th]][[id]]$overview
    }
    m
  }
  # array de bytes -> raster RGB do canvas (valores em ordem de linha)
  to_spat <- function(m) {
    r <- rast(nrows = dim(m)[1], ncols = dim(m)[2], nlyrs = 3, extent = e_canvas, crs = crs_map)
    values(r) <- sapply(1:3, function(j) as.integer(t(m[, , j])))
    names(r) <- c("red", "green", "blue")
    r
  }
  # raster RGB -> array 0-255, para as folhas
  to_array <- function(r) {
    v <- values(r, mat = TRUE)
    a <- array(0L, c(nrow(r), ncol(r), 3))
    for (j in 1:3) a[, , j] <- matrix(as.integer(round(v[, j])), nrow(r), ncol(r), byrow = TRUE)
    a
  }

  # canto superior esquerdo de cada janela de comparacao na grade de 480 m
  xy_w <- st_coordinates(st_transform(st_as_sf(compare_windows, coords = c("lon", "lat"), crs = 4326),
                                      crs_map))
  compare_windows <- compare_windows %>%
    mutate(r0 = pmin(pmax(floor((canvas$ymax - xy_w[, 2]) / res_ov) - win_px / 2, 0), ny - win_px),
           c0 = pmin(pmax(floor((xy_w[, 1] - canvas$xmin) / res_ov) - win_px / 2, 0), nx - win_px))

  for (th in themes) {
    ms <- list()
    small <- list()
    for (k in seq_len(nrow(variants))) {
      id <- variants$id[k]
      ms[[id]] <- mosaic(th, id)
      r <- to_spat(ms[[id]])
      f_tif <- file.path(dir_ras, sprintf("brazil_%s_%s_480m.tif", th, id))
      writeRaster(r, f_tif, datatype = "INT1U", overwrite = TRUE,
                  gdal = c("COMPRESS=DEFLATE", "TILED=YES", "PHOTOMETRIC=RGB"))
      f_png <- file.path(dir_fig, sprintf("brazil_%s_%s_480m.png", th, id))
      if (file.exists(f_png)) file.remove(f_png)
      sf::gdal_utils("translate", f_tif, f_png, options = c("-of", "PNG", "-co", "WORLDFILE=YES"))
      small[[id]] <- to_array(aggregate(r, small_f, "mean"))
      rm(r)
      gc()
      cat("mosaico:", basename(f_tif), "+ png\n")
    }

    # Brasil inteiro, as variantes lado a lado
    sw <- nx / small_f
    w <- lab_w + nrow(variants) * (sw + gap)
    h <- head_h + ny / small_f + gap
    f <- file.path(dir_fig, sprintf("brazil_compare_%s.png", th))
    sheet_open(f, w, h)
    text(gap, 30, sprintf("%s: Brasil inteiro a %s km, E8 por gama", theme_label[[th]],
                          format(res_ov * small_f / 1000, decimal.mark = ",")),
         adj = c(0, 0.5), cex = 2.2, font = 2)
    for (k in seq_len(nrow(variants))) {
      x <- lab_w + (k - 1) * (sw + gap)
      text(x + sw / 2, 95, variants$label[k], cex = 2.2, font = 2)
      put(small[[variants$id[k]]], x, head_h)
    }
    dev.off()
    cat("folha:", f, "\n")

    # janelas de ~490 km a 480 m, as variantes lado a lado
    w <- lab_w + nrow(variants) * (win_px + gap)
    h <- head_h + nrow(compare_windows) * (win_px + gap + 40)
    f <- file.path(dir_fig, sprintf("regions_compare_%s.png", th))
    sheet_open(f, w, h)
    text(gap, 30, sprintf("%s: janelas de %d km a %d m, E8 por gama", theme_label[[th]],
                          round(win_px * res_ov / 1000), res_ov),
         adj = c(0, 0.5), cex = 2.2, font = 2)
    for (k in seq_len(nrow(variants))) {
      text(lab_w + (k - 1) * (win_px + gap) + win_px / 2, 95, variants$label[k], cex = 2.2, font = 2)
    }
    for (wi in seq_len(nrow(compare_windows))) {
      y <- head_h + (wi - 1) * (win_px + gap + 40)
      text(lab_w, y + 18, compare_windows$window[wi], adj = c(0, 0.5), cex = 1.6)
      rows <- compare_windows$r0[wi] + seq_len(win_px)
      cols <- compare_windows$c0[wi] + seq_len(win_px)
      for (k in seq_len(nrow(variants))) {
        put(ms[[variants$id[k]]][rows, cols, , drop = FALSE], lab_w + (k - 1) * (win_px + gap), y + 40)
      }
    }
    dev.off()
    cat("folha:", f, "\n")
    rm(ms, small)
    gc()
  }
}

# resumo ---------------------------------------------------------------------

cat("\n# resumo", strrep("-", 69), "\n")
cat(sprintf("%d folhas em %s, em %s\n", length(list.files(dir_fig, "\\.png$")), dir_fig,
            fmt_time(as.numeric(difftime(Sys.time(), t0, units = "secs")))))
tmpFiles(remove = TRUE)
cat(sprintf("temporarios em %s: %d arquivos\n", dir_tmp, length(list.files(dir_tmp))))
