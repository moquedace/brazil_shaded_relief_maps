# brazil_shaded_relief_maps - 02 reprojeta o gedtm30 e gera os heightmaps ----
#
# entrada (somente leitura):
#   cassio/data/gedtm30_brazil/gedtm30_v1_2_brazil_30m.vrt
#     EPSG:4326, 1 segundo de arco, metros, sem scale (ver README dos dados)
#   config/canvas_5880.csv
#     retangulo do mapa, tamanho dos blocos, sobreposicao, faixa de altitude
#
# saida: data/intermediate/02_prepared_dem/
#   raster/gedtm30_v1_2_brazil_5880_30m.tif      dem 30 m, EPSG:5880, piramides
#   raster/gedtm30_v1_2_brazil_5880_preview.tif  reducao (~2 km) para conferir
#   figures/dem_preview.png                      olhada rapida no relevo
#   heightmaps/heightmap_rRR_cCC.png             16 bits, 10240 x 10240 px
#   tables/heightmap_blocks.csv                  um bloco por linha (extensoes)
#   tables/dem_check.csv                         conferencias
#   no modo piloto tudo vai para subpastas pilot/
#
# etapas:
#   1. warp do vrt para EPSG:5880 a 30 m no retangulo do mapa (gdalwarp,
#      bilinear, todos os nucleos) e piramides para abrir rapido no QGIS
#   2. conferencia: dem x vrt em pontos sorteados, pontos de controle, sem
#      dado dentro do Brasil
#   3. heightmaps para o Blender: um png de 16 bits por bloco, nucleo de
#      8192 px + 1024 px de sobreposicao de cada lado (as sombras atravessam
#      a borda do bloco; o 04 renderiza o bloco inteiro e o 05 corta o nucleo)
#
# heightmap: altitude fixa de 0 a 7000 m -> 0 a 65535 (0,107 m por nivel),
#   a mesma em todos os blocos (faixa em config/canvas_5880.csv). Assim o
#   exagero vertical no Blender e igual no mapa inteiro e pode ser dado em
#   vezes (ex.: 10x). Sem dado (mar aberto) e valores < 0 viram 0 (nivel do
#   mar). 7000 m porque o retangulo do mapa pega os Andes ate o Aconcagua
#   (6961 m); com 3000 m (primeira versao, o maximo do Brasil) os Andes das
#   bordas sairiam com o topo cortado. O png nao tem valor de "sem dado".
#
# modo: run_mode <- "pilot" faz so o bloco do Quadrilatero Ferrifero, mede o
#   tempo e estima a rodada inteira. Conferido o piloto, trocar para "full".
#
# rodar (R, na maquina local GEOCARBONX):
#   source("D:/usuario_armazenamento/cassio/projects/brazil_shaded_relief_maps/scripts/02_prepare_dem.R")

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

run_mode       <- "full"            # "pilot" ou "full" (piloto aprovado em 07/11/2026)
n_workers      <- 8                 # heightmaps em paralelo (~3 GB de RAM cada); nao
                                    # rodar junto com o Blender a 100% (chega a 38 GB)
overwrite_dem  <- FALSE             # TRUE refaz o warp mesmo se o tif existir
overwrite_hm   <- FALSE             # TRUE refaz heightmaps ja gravados. Foi TRUE na
                                    # rodada de 08/11/2026, que refez os 324 (os da
                                    # rodada de 07/11 sairam do codigo antigo, que caiu
                                    # com o C: cheio)
pilot_lonlat   <- c(-43.6, -20.2)   # Quadrilatero Ferrifero (MG)

# pontos de controle: lon, lat, altitude de referencia (m)
control_points <- tribble(
  ~name,                 ~lon,      ~lat,     ~ref_m,
  "esalq_piracicaba",    -47.630,   -22.711,   540,
  "pico_da_bandeira",    -41.7972,  -20.4344, 2892,
  "brasilia_esplanada",  -47.8636,  -15.7998, 1070,
  "manaus_centro",       -60.0217,   -3.1190,   60
)

# pastas ---------------------------------------------------------------------

project_root <- c(
  "D:/usuario_armazenamento/cassio/projects/brazil_shaded_relief_maps",
  "//192.168.0.5/usuario_armazenamento/cassio/projects/brazil_shaded_relief_maps"
)
project_root <- project_root[dir.exists(project_root)][1]
if (is.na(project_root)) stop("Pasta do projeto não encontrada.", call. = FALSE)
cassio_root <- dirname(dirname(project_root))

src_vrt  <- file.path(cassio_root, "data", "gedtm30_brazil",
                      "gedtm30_v1_2_brazil_30m.vrt")
boundary <- file.path(cassio_root, "data", "lac_countries",
                      "wb_countries_admin0_10m", "WB_countries_Admin0_10m",
                      "WB_countries_Admin0_10m.shp")
for (f in c(src_vrt, boundary)) {
  if (!file.exists(f)) stop("Arquivo de entrada não encontrado: ", f, call. = FALSE)
}

is_pilot <- run_mode == "pilot"
step_dir <- function(type) {
  d <- file.path(project_root, "data", "intermediate", "02_prepared_dem", type)
  if (is_pilot) d <- file.path(d, "pilot")
  dir.create(d, recursive = TRUE, showWarnings = FALSE)
  d
}
dir_raster <- step_dir("raster")
dir_hm     <- step_dir("heightmaps")
dir_tab    <- step_dir("tables")
dir_fig    <- step_dir("figures")

# temporarios do terra no D:, nunca no temp do Windows (C:). Em 07/11/2026 a
# primeira rodada inteira encheu o C: com mais de 500 GB: cada passo do
# heightmap gravava um tif temporario que so e apagado quando a sessao do R
# fecha, e os workers ficam abertos a rodada inteira
dir_tmp <- file.path(project_root, "data", "intermediate", "02_prepared_dem", "tmp")
dir.create(dir_tmp, recursive = TRUE, showWarnings = FALSE)
terraOptions(tempdir = dir_tmp, progress = 0)

# CSV no padrão do Excel em pt-BR: ";", decimal "," e UTF-8 com BOM
write_table <- function(x, name) {
  f <- file.path(dir_tab, paste0(name, ".csv"))
  write_excel_csv2(x, f, na = "")
  cat("gravado:", f, "\n")
  invisible(f)
}

fmt_num <- function(x) format(x, scientific = FALSE, trim = TRUE)
fmt_time <- function(s) {
  if (s < 120) sprintf("%.0f s", s) else if (s < 5400) sprintf("%.0f min", s / 60)
  else sprintf("%.1f h", s / 3600)
}

# retangulo do mapa e blocos -------------------------------------------------

canvas <- read_delim(file.path(project_root, "config", "canvas_5880.csv"),
                     delim = ";", locale = locale(decimal_mark = ",", grouping_mark = "."),
                     show_col_types = FALSE, progress = FALSE)
res   <- canvas$res_m
bp    <- canvas$block_px
ov    <- canvas$overlap_px
z_min <- canvas$z_min_m
z_max <- canvas$z_max_m
crs_map <- canvas$crs

stopifnot(canvas$ncol == canvas$nblock_x * bp,
          canvas$nrow == canvas$nblock_y * bp,
          (canvas$xmax - canvas$xmin) == canvas$ncol * res,
          (canvas$ymax - canvas$ymin) == canvas$nrow * res)

# linha 0 = bloco mais ao norte; extensao "full" = nucleo + sobreposicao
blocks <- expand.grid(col = seq_len(canvas$nblock_x) - 1,
                      row = seq_len(canvas$nblock_y) - 1) %>%
  as_tibble() %>%
  mutate(
    block_id  = sprintf("r%02d_c%02d", row, col),
    core_xmin = canvas$xmin + col * bp * res,
    core_xmax = core_xmin + bp * res,
    core_ymax = canvas$ymax - row * bp * res,
    core_ymin = core_ymax - bp * res,
    full_xmin = core_xmin - ov * res,
    full_xmax = core_xmax + ov * res,
    full_ymin = core_ymin - ov * res,
    full_ymax = core_ymax + ov * res,
    file      = file.path(dir_hm, paste0("heightmap_", block_id, ".png"))
  )

brazil <- st_read(boundary, quiet = TRUE) %>%
  filter(ISO_A3 == "BRA") %>%
  st_transform(crs_map) %>%
  st_geometry() %>%
  st_union()

core_sfc <- st_sfc(lapply(seq_len(nrow(blocks)), function(i) {
  b <- blocks[i, ]
  st_polygon(list(matrix(c(b$core_xmin, b$core_ymin, b$core_xmax, b$core_ymin,
                           b$core_xmax, b$core_ymax, b$core_xmin, b$core_ymax,
                           b$core_xmin, b$core_ymin), ncol = 2, byrow = TRUE)))
}), crs = crs_map)
blocks$has_brazil <- lengths(st_intersects(core_sfc, brazil)) > 0

cat("\n# retangulo do mapa", strrep("-", 59), "\n")
cat(sprintf("%s, %d m, %d x %d px, %d x %d blocos de %d px (+%d px de sobreposicao)\n",
            crs_map, res, canvas$ncol, canvas$nrow, canvas$nblock_x,
            canvas$nblock_y, bp, ov))
cat(sprintf("blocos com Brasil: %d de %d\n", sum(blocks$has_brazil), nrow(blocks)))

if (is_pilot) {
  pp <- st_sfc(st_point(pilot_lonlat), crs = 4326) %>%
    st_transform(crs_map) %>%
    st_coordinates()
  blocks <- blocks %>%
    filter(core_xmin <= pp[1], core_xmax > pp[1],
           core_ymin < pp[2], core_ymax >= pp[2])
  stopifnot(nrow(blocks) == 1)
  cat("piloto: bloco", blocks$block_id, "\n")
}

# 1. warp para EPSG:5880 a 30 m ----------------------------------------------

dem_file <- file.path(dir_raster, if (is_pilot) {
  paste0("gedtm30_v1_2_5880_30m_", blocks$block_id, ".tif")
} else {
  "gedtm30_v1_2_brazil_5880_30m.tif"
})

# piloto: extensao do bloco com sobreposicao; completo: retangulo do mapa
te <- if (is_pilot) {
  c(blocks$full_xmin, blocks$full_ymin, blocks$full_xmax, blocks$full_ymax)
} else {
  c(canvas$xmin, canvas$ymin, canvas$xmax, canvas$ymax)
}
n_px_warp <- (te[3] - te[1]) / res * (te[4] - te[2]) / res

cat("\n# 1. warp", strrep("-", 68), "\n")
t_warp <- NA_real_
if (file.exists(dem_file) && !overwrite_dem) {
  cat("dem ja existe, pulando o warp:", dem_file, "\n")
} else {
  cat(sprintf("%s px (%.1f Gpx) -> %s\n",
              format(n_px_warp, big.mark = ".", decimal.mark = ","),
              n_px_warp / 1e9, dem_file))
  t0 <- Sys.time()
  # sem -multi: o sf so aceita -multi com quiet = TRUE (a barra de progresso
  # vinda de varias threads derruba o R) e aqui a barra e necessaria. O
  # calculo do warp continua em todos os nucleos via -wo NUM_THREADS.
  gdal_utils(
    "warp", src_vrt, dem_file, quiet = FALSE,
    options = c(
      "-t_srs", crs_map, "-tr", fmt_num(res), fmt_num(res),
      "-te", fmt_num(te), "-r", "bilinear", "-ot", "Float32",
      "-dstnodata", "-9999", "-wo", "NUM_THREADS=ALL_CPUS",
      "-wm", "4096", "-overwrite",
      "-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=3", "-co", "TILED=YES",
      "-co", "BLOCKXSIZE=512", "-co", "BLOCKYSIZE=512", "-co", "BIGTIFF=YES",
      "-co", "NUM_THREADS=ALL_CPUS"
    ),
    config_options = c(GDAL_CACHEMAX = "4096", GDAL_NUM_THREADS = "ALL_CPUS")
  )
  t_warp <- as.numeric(difftime(Sys.time(), t0, units = "secs"))
  cat(sprintf("warp: %s (%.1f s por Gpx)\n", fmt_time(t_warp), t_warp / (n_px_warp / 1e9)))

  if (!is_pilot) {
    cat("piramides (para abrir no QGIS)...\n")
    t0 <- Sys.time()
    gdal_addo(dem_file, overviews = c(2, 4, 8, 16, 32, 64, 128), method = "AVERAGE",
              config_options = c(COMPRESS_OVERVIEW = "DEFLATE", PREDICTOR_OVERVIEW = "3",
                                 GDAL_NUM_THREADS = "ALL_CPUS"))
    cat("piramides:", fmt_time(as.numeric(difftime(Sys.time(), t0, units = "secs"))), "\n")
  }
}

dem <- rast(dem_file)
stopifnot(all(dim(dem)[1:2] == c((te[4] - te[2]) / res, (te[3] - te[1]) / res)),
          all(abs(as.vector(ext(dem)) - te[c(1, 3, 2, 4)]) < 1e-6))
if (!is.na(scoff(dem)[1, 1]) && scoff(dem)[1, 1] != 1) {
  stop("o dem tem scale diferente de 1; o GEDTM30 v1.2 ja esta em metros", call. = FALSE)
}

# 2. conferencia -------------------------------------------------------------

cat("\n# 2. conferencia", strrep("-", 61), "\n")
checks <- list()

# dem (warp bilinear) x vrt de origem nos mesmos pontos
set.seed(42)
area <- st_as_sfc(st_bbox(c(xmin = te[1], ymin = te[2], xmax = te[3], ymax = te[4]),
                          crs = st_crs(crs_map)))
pts_brazil <- st_as_sf(st_sample(st_intersection(area, brazil), 2000))
v_dem <- extract(dem, vect(pts_brazil))[, 2]
v_src <- extract(rast(src_vrt), vect(st_transform(pts_brazil, 4326)))[, 2]
d <- v_dem - v_src
checks$dem_vs_vrt <- tibble(
  check = "dem_5880_menos_vrt_4326_2000_pontos_no_brasil",
  n = length(d), n_na_dem = sum(is.na(v_dem)), n_na_vrt = sum(is.na(v_src)),
  median_abs_m = median(abs(d), na.rm = TRUE),
  p95_abs_m = quantile(abs(d), 0.95, na.rm = TRUE, names = FALSE),
  max_abs_m = max(abs(d), na.rm = TRUE)
)
cat(sprintf("dem x vrt (2000 pontos no Brasil): sem dado no dem %d; |dif| mediana %.2f m, p95 %.2f m, max %.1f m\n",
            sum(is.na(v_dem)), checks$dem_vs_vrt$median_abs_m,
            checks$dem_vs_vrt$p95_abs_m, checks$dem_vs_vrt$max_abs_m))
cat(sprintf("altitude nos pontos: min %.1f, mediana %.1f, max %.1f m; negativos %d\n",
            min(v_dem, na.rm = TRUE), median(v_dem, na.rm = TRUE),
            max(v_dem, na.rm = TRUE), sum(v_dem < 0, na.rm = TRUE)))

cp <- st_as_sf(control_points, coords = c("lon", "lat"), crs = 4326) %>%
  st_transform(crs_map)
cp_in <- lengths(st_intersects(cp, area)) > 0
checks$control <- control_points %>%
  mutate(in_extent = cp_in,
         dem_m = ifelse(cp_in, extract(dem, vect(cp))[, 2], NA_real_),
         vrt_m = extract(rast(src_vrt), vect(st_transform(cp, 4326)))[, 2])
cat("pontos de controle (m):\n")
print(as.data.frame(checks$control), row.names = FALSE)

if (!is_pilot) {
  # olhada rapida: reducao a ~2 km (usa as piramides) e figura simples
  prev_file <- file.path(dir_raster, "gedtm30_v1_2_brazil_5880_preview.tif")
  gdal_utils("translate", dem_file, prev_file, quiet = TRUE,
             options = c("-outsize", "2304", "2304", "-r", "average"))
  prev <- rast(prev_file)
  png(file.path(dir_fig, "dem_preview.png"), width = 2400, height = 2400, res = 200)
  plot(prev, col = hcl.colors(100, "Earth"), range = c(0, 2000),
       main = "GEDTM30 v1.2, EPSG:5880 (redução a ~2 km)")
  plot(vect(st_as_sf(brazil)), add = TRUE, border = "grey20", lwd = 0.6)
  dev.off()
  cat("previa:", file.path(dir_fig, "dem_preview.png"), "\n")
}

# 3. heightmaps para o Blender -----------------------------------------------

cat("\n# 3. heightmaps", strrep("-", 62), "\n")

# o bloco e lido de uma vez para a memoria (readValues) e todo o calculo e
# feito numa matriz do R, sem passos encadeados do terra. A versao anterior
# (crop -> extend -> clamp -> ifel -> round) gravava ~2,3 GB de temporarios
# por bloco no C: e encheu o disco na rodada de 07/11/2026
make_heightmap <- function(i, blocks, dem_file, z_min, z_max, res, dir_tmp, overwrite) {
  suppressPackageStartupMessages(library(terra))
  terraOptions(tempdir = dir_tmp, progress = 0)
  b <- blocks[i, ]
  t0 <- Sys.time()
  if (file.exists(b$file) && !overwrite) {
    return(data.frame(block_id = b$block_id, status = "exists", seconds = 0))
  }
  dem  <- rast(dem_file)
  n_px <- round((b$full_xmax - b$full_xmin) / res)

  # linhas e colunas do bloco na grade do dem; o que cai fora do dem (borda
  # do retangulo do mapa) fica sem dado
  r0   <- round((ymax(dem) - b$full_ymax) / res) + 1
  c0   <- round((b$full_xmin - xmin(dem)) / res) + 1
  rows <- r0:(r0 + n_px - 1)
  cols <- c0:(c0 + n_px - 1)
  rin  <- rows[rows >= 1 & rows <= nrow(dem)]
  cin  <- cols[cols >= 1 & cols <= ncol(dem)]
  z <- matrix(NA_real_, n_px, n_px)
  if (length(rin) > 0 && length(cin) > 0) {
    readStart(dem)
    v <- readValues(dem, row = rin[1], nrows = length(rin),
                    col = cin[1], ncols = length(cin))
    readStop(dem)
    z[rin - r0 + 1, cin - c0 + 1] <- matrix(v, nrow = length(rin), byrow = TRUE)
    rm(v)
  }

  z[is.na(z) | z < z_min] <- z_min   # sem dado e abaixo de 0 -> nivel do mar
  z[z > z_max] <- z_max
  z <- round((z - z_min) / (z_max - z_min) * 65535)

  hm <- rast(z, crs = crs(dem),
             extent = ext(b$full_xmin, b$full_xmax, b$full_ymin, b$full_ymax))
  rm(z)

  # png sem valor de "sem dado". O terra grava INT2U com 65535 como sem dado
  # e, no png, isso vira transparencia (bloco tRNS): o pixel no topo da faixa
  # e lido como NA e, no Blender, perderia a altura. Por isso: tif temporario
  # pelo terra e png pelo gdal_translate com -a_nodata none. Antes, apaga o
  # png antigo e os arquivos que o acompanham (estatisticas velhas no aux.xml)
  tmp_tif <- file.path(dir_tmp, paste0("heightmap_", b$block_id, ".tif"))
  writeRaster(hm, tmp_tif, datatype = "INT2U", overwrite = TRUE)
  unlink(c(b$file, paste0(b$file, ".aux.xml"), sub("\\.png$", ".wld", b$file)))
  sf::gdal_utils("translate", tmp_tif, b$file, quiet = TRUE,
                 options = c("-of", "PNG", "-a_nodata", "none", "-co", "WORLDFILE=YES"))
  unlink(tmp_tif)

  # conferencia: o png gravado tem de ser identico ao calculado
  same <- isTRUE(all(values(rast(b$file), mat = FALSE) == values(hm, mat = FALSE)))
  rm(hm)
  gc()
  tmpFiles(remove = TRUE)            # algum temporario do terra deste worker
  data.frame(block_id = b$block_id, status = if (same) "ok" else "png_differs",
             seconds = as.numeric(difftime(Sys.time(), t0, units = "secs")))
}

# conferencia de um heightmap: tamanho e n pixels sorteados no bloco inteiro
# (nucleo + sobreposicao) contra o dem; fora do dem o esperado e o nivel do mar.
# O png e lido inteiro uma vez (~1 s) e os pontos saem da memoria. Com
# extract() direto no png, o gdal decodifica o arquivo desde o comeco a cada
# ponto numa linha acima da ultima lida (~0,3 s por ponto): a conferencia do
# primeiro lote levou 23 min e a final 92 min na rodada de 08/11/2026. No dem
# (tif em tiles de 512) o extract e rapido (500 pontos em ~1 s)
check_hm <- function(b, n = 2000) {
  h  <- rast(b$file)
  hv <- values(h, mat = FALSE)
  xy <- cbind(runif(n, b$full_xmin, b$full_xmax), runif(n, b$full_ymin, b$full_ymax))
  z_dem <- extract(dem, xy)[, 1]
  z_hm  <- hv[cellFromXY(h, xy)] / 65535 * (z_max - z_min) + z_min
  z_exp <- pmin(pmax(ifelse(is.na(z_dem), z_min, z_dem), z_min), z_max)
  tibble(block_id = b$block_id, nrow = nrow(h), ncol = ncol(h),
         hm_min = min(hv), hm_max = max(hv), n_points = n,
         n_outside_or_sea = sum(is.na(z_dem)),
         max_abs_diff_m = max(abs(z_hm - z_exp)))
}
# tolerancia = meio nivel do heightmap (erro maximo do arredondamento) + 1 mm:
# 0,054 m com 0 a 7000 m. Era 0,05 m fixo, pensado para 0 a 3000 m (meio
# nivel = 0,023 m), e barrou a rodada de 08/11/2026 com 0,0533 m
tol_m <- (z_max - z_min) / 65535 / 2 + 0.001
hm_ok <- function(chk) {
  all(chk$nrow == bp + 2 * ov & chk$ncol == bp + 2 * ov) &&
    all(chk$max_abs_diff_m <= tol_m)
}

# o bloco do piloto vai no primeiro lote, e o primeiro lote e conferido contra
# o dem antes de seguir: um erro na leitura ou na orientacao do bloco aparece
# em ~1 min, e nao depois da rodada inteira
todo <- seq_len(nrow(blocks))
i_first <- which(blocks$block_id == "r11_c13")
todo <- c(i_first, setdiff(todo, i_first))
cat(sprintf("%d heightmaps de %d x %d px em %s\n", length(todo), bp + 2 * ov,
            bp + 2 * ov, dir_hm))

plan(multisession, workers = min(n_workers, length(todo)))
t0 <- Sys.time()
t_chk1 <- 0                         # tempo da conferencia do primeiro lote, fora da estimativa
hm_log <- list()
chunks <- split(todo, ceiling(seq_along(todo) / n_workers))
for (k in seq_along(chunks)) {
  hm_log[[k]] <- bind_rows(future_lapply(
    chunks[[k]], make_heightmap, blocks = blocks, dem_file = dem_file,
    z_min = z_min, z_max = z_max, res = res, dir_tmp = dir_tmp,
    overwrite = overwrite_hm, future.seed = NULL
  ))
  if (any(hm_log[[k]]$status == "png_differs")) {
    plan(sequential)
    stop("png gravado diferente do calculado: ",
         paste(hm_log[[k]]$block_id[hm_log[[k]]$status == "png_differs"], collapse = ", "),
         call. = FALSE)
  }
  if (k == 1) {
    t1 <- Sys.time()
    set.seed(2)
    chk1 <- bind_rows(lapply(chunks[[1]], function(i) check_hm(blocks[i, ], n = 500)))
    t_chk1 <- as.numeric(difftime(Sys.time(), t1, units = "secs"))
    cat("conferencia do primeiro lote (500 pixels por bloco contra o dem):\n")
    print(as.data.frame(chk1), row.names = FALSE)
    if (!hm_ok(chk1)) {
      plan(sequential)
      stop("primeiro lote não bate com o dem; rodada interrompida", call. = FALSE)
    }
  }
  done <- sum(lengths(chunks[seq_len(k)]))
  el <- as.numeric(difftime(Sys.time(), t0, units = "secs"))
  cat(sprintf("[%d/%d] %s | falta ~%s\n", done, length(todo), fmt_time(el),
              fmt_time((el - t_chk1) / done * (length(todo) - done))))
}
plan(sequential)
t_hm <- as.numeric(difftime(Sys.time(), t0, units = "secs"))
hm_log <- bind_rows(hm_log)
tmpFiles(remove = TRUE)

set.seed(1)
idx_check <- if (is_pilot) {
  1
} else {
  # 6 blocos com Brasil, o do piloto e um canto (todo fora do dem ou mar)
  sort(unique(c(sample(which(blocks$has_brazil), 6),
                which(blocks$block_id %in% c("r11_c13", "r00_c00")))))
}
checks$heightmaps <- bind_rows(lapply(idx_check, function(i) check_hm(blocks[i, ])))
cat("conferencia dos heightmaps:\n")
print(as.data.frame(checks$heightmaps), row.names = FALSE)
if (!hm_ok(checks$heightmaps)) {
  stop(sprintf("heightmap com tamanho errado ou que não bate com o dem (> %.3f m)", tol_m),
       call. = FALSE)
}

# tabelas ----------------------------------------------------------------------

blocks_out <- blocks %>%
  left_join(hm_log, by = "block_id") %>%
  mutate(file = basename(file), png_px = bp + 2 * ov, overlap_px = ov,
         res_m = res, z_min_m = z_min, z_max_m = z_max)
write_table(blocks_out, "heightmap_blocks")
# sem converter para texto: as colunas numericas das duas partes nao se
# repetem, e numero convertido em texto saia com ponto decimal no CSV
write_table(bind_rows(
  checks$dem_vs_vrt,
  checks$heightmaps %>% mutate(check = paste0("heightmap_", block_id))
), "dem_check")

# resumo e estimativa ----------------------------------------------------------

cat("\n# resumo", strrep("-", 69), "\n")
cat("dem:", dem_file, "\n")
cat(sprintf("heightmaps: %d ok (png identico ao calculado), %d ja existiam, em %s\n",
            sum(hm_log$status == "ok"), sum(hm_log$status == "exists"), fmt_time(t_hm)))
cat(sprintf("temporarios em %s: %d arquivos\n", dir_tmp,
            length(list.files(dir_tmp, recursive = TRUE))))

if (is_pilot && !is.na(t_warp)) {
  n_full <- as.numeric(canvas$ncol) * canvas$nrow
  n_blocks <- canvas$nblock_x * canvas$nblock_y
  sec_hm <- mean(hm_log$seconds[hm_log$status == "ok"])
  cat(sprintf("estimativa da rodada inteira: warp ~%s (%.1f Gpx); %d heightmaps ~%s com %d workers\n",
              fmt_time(t_warp / n_px_warp * n_full), n_full / 1e9, n_blocks,
              fmt_time(sec_hm * n_blocks / n_workers), n_workers))
  cat("o piloto rodou 1 heightmap sem disputa de disco: a taxa com", n_workers,
      "workers pode ser menor.\n")
  cat("se estiver tudo certo, trocar run_mode para \"full\" e rodar de novo.\n")
}
