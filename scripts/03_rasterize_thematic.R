# brazil_shaded_relief_maps - 03 rasteriza geologia, solos e paises a 30 m ---
#
# entrada (somente leitura):
#   projects/brazil_lithology_harmonized/data/final/
#     brazil_lithology_harmonized_4326.gpkg       poligonos das unidades,
#                                                 campo group_rock (9 grupos)
#   projects/brazil_soil_harmonized/data/final/
#     brazil_soil_harmonized_4674.gpkg            poligonos, campo map_suborder
#                                                 (subordem do SiBCS 2025 ou
#                                                 tipo de terreno)
#     brazil_soil_harmonized_suborders_4674.gpkg  rotulos, simbolos e cores das
#                                                 subordens (so os atributos)
#   projects/brazil_soil_harmonized/data/lookup/map_classes.csv
#                                                 cores das ordens (SiBCS 2025,
#                                                 Anexo I)
#   cassio/data/lac_countries/wb_countries_admin0_10m/   contorno dos paises
#   config/canvas_5880.csv                        retangulo do mapa e blocos
#
# saida: data/intermediate/03_thematic/
#   vector/<tema>_5880.gpkg           poligonos em EPSG:5880 com class_id e
#                                     indice espacial
#   raster/<tema>/<tema>_rRR_cCC.tif  Byte, nucleo do bloco (8192 px, a mesma
#                                     grade dos heightmaps do 02), piramides
#                                     internas pela moda
#   raster/<tema>.vrt + <tema>.qml    mosaico dos blocos e estilo do QGIS
#   tables/<tema>_classes.csv         class_id, codigo, rotulo e cor
#   tables/thematic_blocks.csv        cada bloco: situacao, tempo, pixels por
#                                     classe
#   tables/thematic_area_check.csv    area por classe: raster x poligonos
#   tables/thematic_point_check.csv   pontos sorteados: raster x poligonos
#   figures/<tema>_preview.png        olhada rapida (solos em ordem e subordem)
#   no modo piloto tudo, menos vector/, vai para subpastas pilot/
#
# temas (classe 0 = sem dado em geology e soil; mar ou fora em country):
#   geology  9 grupos de rocha, com as cores do mapa geologico de Lamego
#            (1960), o mapa modelo da Souza (2020)
#   soil     subordens do SiBCS 2025 + 4 tipos de terreno (agua, area urbana,
#            afloramentos, dunas). A ordem vem da tabela de classes, entao o
#            mesmo raster serve para o mapa de ordens (o das figuras atuais) e
#            para o de subordens
#   country  1 Brasil, 2 outros paises (contorno World Bank). Mascara para o
#            05 (vizinhos em cinza, mar)
#   soil_diversity       numero de componentes (classe dominante, subdominantes
#                        e inclusoes, val_ncompo do IBGE) por unidade de
#                        mapeamento, em 6 faixas (1 a 5, 6 ou mais) + tipos de
#                        terreno; a medida da figura 05 de brazil_soil_harmonized
#   lithology_diversity  numero de litologias descritas por unidade
#                        litoestratigrafica (campo litologias, separadas por
#                        "; "), em 6 faixas (1, 2, 3-4, 5-7, 8-12, 13 ou mais);
#                        a medida da figura 04 de brazil_lithology_harmonized
#   os dois de diversidade entraram em 10/11/2026 (log 25), para o site; rodar
#   de novo com overwrite_* = FALSE so faz os temas novos
#   A hipsometria nao passa por aqui: o dem do 02 ja esta na grade, e as cores
#   entram no 05.
#
# regra: cada pixel de 30 m recebe a classe do poligono que contem o seu
#   centro (padrao do gdal_rasterize). Classe nao se interpola.
#
# blocos: o mesmo corte do 02 (18 x 18 blocos de 8192 px), so o nucleo. Cada
#   bloco le, pelo indice espacial do gpkg, so os poligonos que tocam nele, e
#   os blocos rodam em paralelo. Um bloco ja gravado e pulado (overwrite_raster).
#
# conferencias: area de cada classe no raster x nos poligonos (no plano da
#   EPSG:5880, que nao e de area igual: serve so para comparar os dois) e
#   pontos sorteados, classe do raster x classe do poligono que contem o ponto.
#   Um ponto pode discordar so a ate meia diagonal do pixel (21,2 m) de uma
#   borda; mais longe que isso e erro.
#
# modo: run_mode <- "pilot" faz so o bloco do Quadrilatero Ferrifero (r11_c13,
#   o mesmo do piloto do 02 e do 04) nos 3 temas, mede o tempo e estima a
#   rodada inteira. Conferido o piloto, trocar para "full".
#
# rodar (R, na maquina local GEOCARBONX; nao junto com o Blender):
#   source("D:/usuario_armazenamento/cassio/projects/brazil_shaded_relief_maps/scripts/03_rasterize_thematic.R")

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

run_mode         <- "full"          # "pilot" ou "full" (piloto aprovado em 08/11/2026)
n_workers        <- 16              # blocos em paralelo (< 1 GB de RAM cada)
overwrite_vector <- FALSE           # TRUE refaz a reprojecao dos poligonos
overwrite_raster <- FALSE           # TRUE refaz os blocos ja gravados
pilot_block      <- "r11_c13"       # Quadrilatero Ferrifero (MG)
n_points         <- 5000            # pontos sorteados por tema na conferencia
tol_area_pct     <- 0.5             # |raster - poligonos| maximo por classe (%),
min_area_km2     <- 1000            # so nas classes com pelo menos essa area
                                    # (no piloto, 50 km2: o bloco tem 60.000 km2)

themes <- c("geology", "soil", "country", "soil_diversity", "lithology_diversity")

# pastas ---------------------------------------------------------------------

project_root <- c(
  "D:/usuario_armazenamento/cassio/projects/brazil_shaded_relief_maps",
  "//192.168.0.5/usuario_armazenamento/cassio/projects/brazil_shaded_relief_maps"
)
project_root <- project_root[dir.exists(project_root)][1]
if (is.na(project_root)) stop("Pasta do projeto não encontrada.", call. = FALSE)
projects_dir <- dirname(project_root)
cassio_root  <- dirname(projects_dir)

soil_root <- file.path(projects_dir, "brazil_soil_harmonized")
src <- list(
  geology        = file.path(projects_dir, "brazil_lithology_harmonized", "data", "final",
                             "brazil_lithology_harmonized_4326.gpkg"),
  # area das faixas de diversidade litologica na projecao de area igual
  # (Goode, ESRI:54052), a mesma da figura 04 de brazil_lithology_harmonized
  geology_ea     = file.path(projects_dir, "brazil_lithology_harmonized", "data", "final",
                             "brazil_lithology_harmonized_54052.gpkg"),
  soil           = file.path(soil_root, "data", "final", "brazil_soil_harmonized_4674.gpkg"),
  soil_suborders = file.path(soil_root, "data", "final",
                             "brazil_soil_harmonized_suborders_4674.gpkg"),
  soil_orders    = file.path(soil_root, "data", "lookup", "map_classes.csv"),
  country        = file.path(cassio_root, "data", "lac_countries", "wb_countries_admin0_10m",
                             "WB_countries_Admin0_10m", "WB_countries_Admin0_10m.shp")
)
for (f in src) {
  if (!file.exists(f)) stop("Arquivo de entrada não encontrado: ", f, call. = FALSE)
}

stopifnot(run_mode %in% c("pilot", "full"))
is_pilot  <- run_mode == "pilot"
step_root <- file.path(project_root, "data", "intermediate", "03_thematic")
step_dir <- function(type, pilot_sub = TRUE) {
  d <- file.path(step_root, type)
  if (is_pilot && pilot_sub) d <- file.path(d, "pilot")
  dir.create(d, recursive = TRUE, showWarnings = FALSE)
  d
}
dir_vec    <- step_dir("vector", pilot_sub = FALSE)   # os mesmos no piloto e na rodada inteira
dir_raster <- step_dir("raster")
dir_tab    <- step_dir("tables")
dir_fig    <- step_dir("figures")

# temporarios do terra no D:, nunca no temp do Windows (C:): ver o 02 e a
# queda de 07/11/2026 com o C: cheio
dir_tmp <- step_dir("tmp", pilot_sub = FALSE)
terraOptions(tempdir = dir_tmp, progress = 0)

vec_file <- setNames(file.path(dir_vec, paste0(themes, "_5880.gpkg")), themes)
vrt_file <- setNames(file.path(dir_raster, paste0(themes, ".vrt")), themes)

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
res     <- canvas$res_m
bp      <- canvas$block_px
crs_map <- canvas$crs

stopifnot(canvas$ncol == canvas$nblock_x * bp,
          canvas$nrow == canvas$nblock_y * bp,
          (canvas$xmax - canvas$xmin) == canvas$ncol * res,
          (canvas$ymax - canvas$ymin) == canvas$nrow * res)

# mesmo corte e mesmos nomes do 02; linha 0 = bloco mais ao norte
blocks <- expand.grid(col = seq_len(canvas$nblock_x) - 1,
                      row = seq_len(canvas$nblock_y) - 1) %>%
  as_tibble() %>%
  mutate(block_id = sprintf("r%02d_c%02d", row, col),
         xmin = canvas$xmin + col * bp * res,
         xmax = xmin + bp * res,
         ymax = canvas$ymax - row * bp * res,
         ymin = ymax - bp * res)
if (is_pilot) blocks <- filter(blocks, block_id == pilot_block)
stopifnot(nrow(blocks) >= 1)

rect <- function(xmin, ymin, xmax, ymax) {
  st_as_sfc(st_bbox(c(xmin = xmin, ymin = ymin, xmax = xmax, ymax = ymax),
                    crs = st_crs(crs_map)))
}
# area coberta pelos rasters desta rodada: o bloco do piloto ou o retangulo
area_poly <- if (is_pilot) {
  rect(blocks$xmin, blocks$ymin, blocks$xmax, blocks$ymax)
} else {
  rect(canvas$xmin, canvas$ymin, canvas$xmax, canvas$ymax)
}

cat("\n# retangulo do mapa", strrep("-", 59), "\n")
cat(sprintf("%s, %d m, %d x %d px; %s\n", crs_map, res, canvas$ncol, canvas$nrow,
            if (is_pilot) paste("piloto: bloco", pilot_block) else
              sprintf("%d blocos de %d px", nrow(blocks), bp)))

# classes --------------------------------------------------------------------

# atributos sem geometria (o sf devolve data.frame com um aviso)
read_attrs <- function(file, sql) {
  as_tibble(suppressWarnings(st_read(file, query = sql, quiet = TRUE)))
}

# geologia: cores do mapa modelo, o Mapa Geologico do Brasil de Lamego (1960,
# DNPM, 1:5.000.000), o que a Souza (2020, Confins 47, fig. 2) levantou no
# Blender. Pedido do Cassio em 08/11/2026 ("tinha ficado muito bom"); antes
# eram as cores das figuras de brazil_lithology_harmonized (pal_group do
# 04_plot_lithology_maps.R), descartadas aqui por serem saturadas demais para
# ir por baixo do sombreado (log 11).
# A legenda do Lamego e por idade e a nossa por tipo de rocha, entao cada grupo
# leva a cor da unidade do Lamego com a mesma rocha. Cores amostradas no
# interior liso das caixas da legenda da foto do artigo (img-2.jpg, mediana de
# ~20 px fora das letras):
#   felsica      pre-cambriano C/D, embasamento gnaissico (o rosa dos escudos)
#   mafica       efusivas basalticas (o azul da Serra Geral)
#   ultramafica  ultrabasicas
#   ferruginosa  pre-cambriano B, onde o Lamego poe a serie Minas (itabiritos)
#   psamitica    devoniano medio (Formacao Cabecas, arenito); o devoniano
#                inferior (Furnas) foi testado e descartado: amarelo-ouro forte
#                demais para 30% do pais
#   psefitica    cambro-ordoviciano (series Itajai, Camaqua e Marica,
#                conglomerados)
#   pelitica     carbonifero inferior (Formacao Poti): o Lamego nao separa
#                pelito; o oliva escuro e a caixa que mais se afasta dos
#                amarelos e do rosa
#   sedimentos_inconsolidados  terciario (o amarelo-esverdeado da Amazonia)
#   carbonatica  jurassico: o Lamego nao tem classe de carbonato (o Bambui
#                esta no lilas do siluriano, quase igual ao rosa da felsica);
#                o cinza-azulado e a unica caixa clara azulada (carbonato e
#                azul na convencao geologica)
# Menor diferenca entre dois grupos: CIEDE2000 9,1 (psamitica x sedimentos);
# na pal_group era 19,8. Paleta clara como a do papel de 1960: o sombreado do
# 05 escurece as cores
geology_colors <- c(
  carbonatica               = "#d2d5d5",
  felsica                   = "#e7d0c6",
  ferruginosa               = "#e5a763",
  mafica                    = "#6db4be",
  pelitica                  = "#a6a47a",
  psamitica                 = "#e6c696",
  psefitica                 = "#d1b43c",
  sedimentos_inconsolidados = "#e0d696",
  ultramafica               = "#be7796"
)

classes <- list()
classes$geology <- read_attrs(src$geology, paste(
  "SELECT DISTINCT group_rock AS code, group_rock_label AS label,",
  "group_rock_label_en AS label_en FROM brazil_lithology_harmonized_4326")) %>%
  arrange(code) %>%
  mutate(class_id = row_number(), color = unname(geology_colors[code])) %>%
  select(class_id, code, label, label_en, color)

# solos: cor da subordem (SiBCS 2025, Anexo I; nos tipos de terreno, a do
# IBGE) e cor da ordem, as duas ja usadas nas figuras de brazil_soil_harmonized.
# Conferido em 08/11/2026: as 41 subordens e as 13 ordens batem uma a uma com
# brazil_soil_harmonized/data/lookup/sibcs2025_colors.csv (Anexo I transcrito)
soil_orders <- read_delim(src$soil_orders, delim = ";", show_col_types = FALSE,
                          progress = FALSE) %>%
  select(map_class, color_order = color_sibcs)
classes$soil <- read_attrs(src$soil_suborders, paste(
  "SELECT map_suborder AS code, map_suborder_label AS label,",
  "map_suborder_label_en AS label_en, map_suborder_symbol AS symbol,",
  "color_sibcs AS color, map_class, map_class_label AS order_label,",
  "map_class_symbol AS order_symbol, is_soil",
  "FROM brazil_soil_harmonized_suborders_4674")) %>%
  mutate(is_soil = as.logical(is_soil)) %>%
  left_join(soil_orders, by = "map_class") %>%
  arrange(desc(is_soil), map_class, code) %>%
  mutate(class_id = row_number()) %>%
  select(class_id, code, label, label_en, symbol, color, map_class, order_label,
         order_symbol, color_order, is_soil)

classes$country <- tibble(class_id = 1:2, code = c("brasil", "outro_pais"),
                          label = c("Brasil", "Outros países"),
                          label_en = c("Brazil", "Other countries"),
                          color = c("#d9d6cc", "#efede8"))

# diversidade (log 25): as medidas e as faixas das figuras 05 de
# brazil_soil_harmonized e 04 de brazil_lithology_harmonized. Cores:
# "Atlantico e cobre", escolhidas pelo Cassio em 10/11/2026 entre as opcoes
# testadas sobre o relevo (pais a 960 m e janelas a 30 m): cobre (creme ->
# ocre -> cobre -> vinho) na pedologica e Atlantico (creme -> verde -> azul
# petroleo) na litologica. Sao as cores de entrada do 08, que aplica C^1,3:
# na area plana saem L* de 91 a 38 (solos) e 91 a 39 (litologia). Ficou de
# fora a primeira versao deste log, uma so rampa azul (a pal_seq das figuras
# clareada em Lab, L 90 a 45): os dois mapas ficavam iguais entre si e frios
# demais ao lado de geologia e solos. Tipos de terreno e areas sem unidade em
# cinza neutro (o #dfe8ee do sem-classe da geologia se confundiria com a faixa 1)
soil_div_colors    <- c("#f3ecd4", "#e8d1a3", "#e0b684", "#d0946f", "#ba7369", "#9b5d6a")
lito_div_colors    <- c("#f3eccb", "#d2e0b6", "#a3ccb9", "#72b6bb", "#5499b0", "#56769d")
no_diversity_color <- "#d9d7d0"
div <- list(
  soil_breaks = c(1:6, Inf),
  soil_codes  = c("1", "2", "3", "4", "5", "6_plus"),
  lito_breaks = c(1, 2, 3, 5, 8, 13, Inf),
  lito_codes  = c("1", "2", "3_4", "5_7", "8_12", "13_plus"),
  # n de litologias = n de "; " + 1 (stri_count_fixed na figura 04)
  count_lito  = function(x) lengths(regmatches(x, gregexpr("; ", x, fixed = TRUE))) + 1L
)

# unidades e area de cada faixa (para a legenda das pranchas): solos pela
# area_km2 do brazil_soil_harmonized e unidades = cd_fcim + nom_unidad, como
# na figura 05; litologia pela area na Goode (54052) e unidades = id_unidade
soil_div_attr <- read_attrs(src$soil, paste(
  "SELECT is_soil, val_ncompo, cd_fcim, nom_unidad, area_km2",
  "FROM brazil_soil_harmonized_4674")) %>%
  mutate(is_soil = as.logical(is_soil))
if (any(soil_div_attr$is_soil & is.na(soil_div_attr$val_ncompo))) {
  stop("unidade de solo sem val_ncompo: rever as faixas da diversidade", call. = FALSE)
}
soil_div_attr <- soil_div_attr %>%
  mutate(code = ifelse(is_soil, div$soil_codes[findInterval(val_ncompo, div$soil_breaks)],
                       "terrain_type"))
classes$soil_diversity <- tibble(
  code     = c(div$soil_codes, "terrain_type"),
  label    = c("1", "2", "3", "4", "5", "6 ou mais", "Tipos de terreno"),
  label_en = c("1", "2", "3", "4", "5", "6 or more", "Terrain types"),
  color    = c(soil_div_colors, no_diversity_color)
) %>%
  left_join(soil_div_attr %>%
              group_by(code) %>%
              summarise(n_units = n_distinct(paste(cd_fcim, nom_unidad)),
                        area_km2 = sum(area_km2), .groups = "drop"),
            by = "code") %>%
  mutate(class_id = row_number()) %>%
  select(class_id, code, label, label_en, color, n_units, area_km2)

lito_div_attr <- st_read(src$geology_ea, quiet = TRUE, query = paste(
  "SELECT id_unidade, litologias, geom FROM brazil_lithology_harmonized_54052")) %>%
  mutate(code = div$lito_codes[findInterval(div$count_lito(litologias), div$lito_breaks)],
         area_km2 = as.numeric(st_area(geom)) / 1e6) %>%
  st_drop_geometry()
classes$lithology_diversity <- tibble(
  code     = div$lito_codes,
  label    = c("1", "2", "3–4", "5–7", "8–12", "13 ou mais"),
  label_en = c("1", "2", "3–4", "5–7", "8–12", "13 or more"),
  color    = lito_div_colors
) %>%
  left_join(lito_div_attr %>%
              group_by(code) %>%
              summarise(n_units = n_distinct(id_unidade), area_km2 = sum(area_km2),
                        .groups = "drop"),
            by = "code") %>%
  mutate(class_id = row_number()) %>%
  select(class_id, code, label, label_en, color, n_units, area_km2)
rm(soil_div_attr, lito_div_attr)
gc()   # a geometria da litologia (54052) ocupava alguns GB antes dos workers

for (th in themes) {
  x <- classes[[th]]
  if (anyDuplicated(x$code) || anyNA(x$color) || max(x$class_id) > 254 ||
      (th == "soil" && anyNA(x$color_order))) {
    stop("tabela de classes com problema: ", th, call. = FALSE)
  }
  write_table(x, paste0(th, "_classes"))
}
cat(sprintf("classes: geology %d; soil %d (subordens de %d ordens + %d tipos de terreno); country %d\n",
            nrow(classes$geology), nrow(classes$soil),
            n_distinct(classes$soil$map_class[classes$soil$is_soil]),
            sum(!classes$soil$is_soil), nrow(classes$country)))
for (th in c("soil_diversity", "lithology_diversity")) {
  x <- classes[[th]]
  cat(sprintf("%s: %s\n", th, paste(sprintf("%s = %s unidades, %s km2", x$label, x$n_units,
                                            round(x$area_km2)), collapse = "; ")))
}

# 1. poligonos em EPSG:5880 --------------------------------------------------

cat("\n# 1. poligonos", strrep("-", 63), "\n")

prepare_vector <- function(theme, src, classes, crs_map, out, overwrite, div) {
  suppressPackageStartupMessages({
    library(sf)
    library(dplyr)
  })
  if (file.exists(out) && !overwrite) {
    return(tibble(theme = theme, status = "exists", n = NA_integer_,
                  n_invalid = NA_integer_, seconds = 0))
  }
  t0 <- Sys.time()
  x <- switch(
    theme,
    geology = st_read(src$geology, quiet = TRUE, query = paste(
      "SELECT group_rock AS code, geom FROM brazil_lithology_harmonized_4326")),
    soil = st_read(src$soil, quiet = TRUE, query = paste(
      "SELECT map_suborder AS code, geom FROM brazil_soil_harmonized_4674")),
    # diversidade: os mesmos poligonos de soil e geology, com a faixa no lugar
    # da classe (as faixas vem de div, montado nas classes)
    soil_diversity = st_read(src$soil, quiet = TRUE, query = paste(
      "SELECT is_soil, val_ncompo, geom FROM brazil_soil_harmonized_4674")) %>%
      mutate(code = ifelse(as.logical(is_soil),
                           div$soil_codes[findInterval(val_ncompo, div$soil_breaks)],
                           "terrain_type")) %>%
      select(code),
    lithology_diversity = st_read(src$geology, quiet = TRUE, query = paste(
      "SELECT litologias, geom FROM brazil_lithology_harmonized_4326")) %>%
      mutate(code = div$lito_codes[findInterval(div$count_lito(litologias), div$lito_breaks)]) %>%
      select(code),
    country = {
      # recorte na America do Sul, em graus, antes de reprojetar: poligonos do
      # outro lado do globo saem deformados por cima do retangulo na
      # policonica (a "Indonesia" do log 3)
      suppressMessages(sf_use_s2(FALSE))
      w <- st_read(src$country, quiet = TRUE) %>%
        select(ISO_A3) %>%
        st_make_valid()
      w <- suppressMessages(suppressWarnings(
        st_crop(w, xmin = -95, ymin = -60, xmax = -20, ymax = 20)
      ))
      w <- suppressWarnings(st_collection_extract(w[!st_is_empty(w), ], "POLYGON"))
      w %>%
        mutate(code = ifelse(ISO_A3 == "BRA", "brasil", "outro_pais")) %>%
        select(code)
    }
  )
  if (is.na(st_crs(x))) {
    st_crs(x) <- c(geology = 4326, soil = 4674, country = 4326, soil_diversity = 4674,
                   lithology_diversity = 4326)[[theme]]
  }
  x$class_id <- classes[[theme]]$class_id[match(x$code, classes[[theme]]$code)]
  if (anyNA(x$class_id)) {
    stop(theme, ": codigo sem classe na tabela: ",
         paste(unique(x$code[is.na(x$class_id)]), collapse = ", "), call. = FALSE)
  }
  x <- st_transform(x, crs_map)

  # geometria invalida depois da reprojecao: corrige so essas e fica so com a
  # parte de poligono (uma linha que sobrar seria queimada como linha)
  bad <- !st_is_valid(x)
  bad[is.na(bad)] <- TRUE
  if (any(bad)) {
    fixed <- suppressWarnings(st_collection_extract(st_make_valid(x[bad, ]), "POLYGON"))
    x <- rbind(x[!bad, ], fixed)
  }

  unlink(out)
  st_write(x[, c("class_id", "code")], out, layer = theme, quiet = TRUE,
           layer_options = c("GEOMETRY_NAME=geom", "FID=fid", "SPATIAL_INDEX=YES"))
  tibble(theme = theme, status = "ok", n = nrow(x), n_invalid = sum(bad),
         seconds = as.numeric(difftime(Sys.time(), t0, units = "secs")))
}

if (!all(file.exists(vec_file)) || overwrite_vector) {
  cat(sprintf("reprojetando os poligonos dos temas que faltam em paralelo (alguns minutos, so na primeira vez)\n"))
}
plan(multisession, workers = length(themes))
vec_log <- tryCatch(
  bind_rows(future_lapply(themes, function(th) {
    prepare_vector(th, src, classes, crs_map, vec_file[[th]], overwrite_vector, div)
  }, future.seed = NULL)),
  error = function(e) {
    plan(sequential)
    stop(conditionMessage(e), call. = FALSE)
  }
)
plan(sequential)
print(as.data.frame(vec_log), row.names = FALSE)

# 2. rasters por bloco -------------------------------------------------------

cat("\n# 2. rasters", strrep("-", 65), "\n")

jobs <- merge(blocks, data.frame(theme = themes)) %>%
  as_tibble() %>%
  mutate(vector = unname(vec_file[theme]),
         file   = file.path(dir_raster, theme, paste0(theme, "_", block_id, ".tif")),
         nodata = theme != "country")   # em country o 0 e o mar, um valor valido
for (th in themes) dir.create(file.path(dir_raster, th), recursive = TRUE, showWarnings = FALSE)

make_block <- function(j, jobs, res, bp, crs_map, dir_tmp, overwrite) {
  suppressPackageStartupMessages({
    library(terra)
    library(sf)
  })
  terraOptions(tempdir = dir_tmp, progress = 0)
  fmt <- function(x) format(x, scientific = FALSE, trim = TRUE)
  b <- jobs[j, ]
  t0 <- Sys.time()
  status <- "exists"
  if (!file.exists(b$file) || overwrite) {
    # grava num temporario e so renomeia no fim: uma queda no meio nao deixa
    # um tif incompleto que a proxima rodada pularia por "ja existir" (log
    # 25). gdal_rasterize num arquivo que ja existe queima por cima dele em
    # vez de criar um novo, por isso apaga antes
    tmp <- sub("\\.tif$", ".tmp.tif", b$file)
    unlink(c(b$file, tmp))
    # so os poligonos cujo retangulo toca o bloco, pelo indice espacial
    # (rtree) do gpkg; sem o filtro cada bloco leria o arquivo inteiro. Bloco
    # sem poligono sai todo 0 (testado com o GDAL 3.10 do QGIS em 08/11/2026)
    sql <- sprintf(paste(
      "SELECT class_id, geom FROM %1$s WHERE fid IN (SELECT id FROM rtree_%1$s_geom",
      "WHERE maxx >= %2$s AND minx <= %3$s AND maxy >= %4$s AND miny <= %5$s)"),
      b$theme, fmt(b$xmin), fmt(b$xmax), fmt(b$ymin), fmt(b$ymax))
    gdal_utils("rasterize", b$vector, tmp, quiet = TRUE, options = c(
      "-sql", sql, "-a", "class_id", "-a_srs", crs_map,
      "-te", fmt(c(b$xmin, b$ymin, b$xmax, b$ymax)), "-tr", fmt(res), fmt(res),
      "-ot", "Byte", "-init", "0", if (b$nodata) c("-a_nodata", "0"),
      "-co", "TILED=YES", "-co", "BLOCKXSIZE=512", "-co", "BLOCKYSIZE=512",
      "-co", "COMPRESS=DEFLATE"
    ))
    # piramides internas pela moda: o vrt do QGIS e a previa usam essas. O
    # capture.output engole a barra de progresso do gdal_addo, que no piloto
    # saiu no console (seriam 972 barras na rodada inteira)
    invisible(capture.output(
      gdal_addo(tmp, overviews = c(2, 4, 8, 16, 32, 64), method = "MODE",
                config_options = c(COMPRESS_OVERVIEW = "DEFLATE"))
    ))
    if (!file.rename(tmp, b$file)) stop("nao consegui renomear ", tmp)
    status <- "ok"
  }
  r <- rast(b$file)
  grid_ok <- nrow(r) == bp && ncol(r) == bp &&
    all(abs(as.vector(ext(r)) - c(b$xmin, b$xmax, b$ymin, b$ymax)) < 1e-6)
  # pixels por classe com o freq() do terra, que le em blocos. Antes era
  # values() do bloco inteiro em double (512 MB) + copias, ~2 GB por worker:
  # com 16 workers deu std::bad_alloc em 10/11/2026 (log 25). Mesmo
  # resultado: NA (o 0 dos temas com nodata) volta para a classe 0
  f <- freq(r)
  n <- numeric(256)                    # posicao 1 = classe 0
  if (nrow(f)) n[f$value + 1] <- f$count
  n[1] <- n[1] + (ncell(r) - sum(f$count))
  rm(r, f)
  gc()
  tmpFiles(remove = TRUE)
  data.frame(theme = b$theme, block_id = b$block_id,
             status = if (grid_ok) status else "grid_differs",
             seconds = as.numeric(difftime(Sys.time(), t0, units = "secs")),
             class_id = which(n > 0) - 1, n_px = n[n > 0])
}

cat(sprintf("%d blocos x %d temas = %d rasters de %d x %d px em %s\n", nrow(blocks),
            length(themes), nrow(jobs), bp, bp, dir_raster))
todo <- seq_len(nrow(jobs))
plan(multisession, workers = min(n_workers, length(todo)))
t0 <- Sys.time()
blk_log <- list()
chunks <- split(todo, ceiling(seq_along(todo) / n_workers))
tryCatch({
  for (k in seq_along(chunks)) {
    blk_log[[k]] <- bind_rows(future_lapply(
      chunks[[k]], make_block, jobs = jobs, res = res, bp = bp, crs_map = crs_map,
      dir_tmp = dir_tmp, overwrite = overwrite_raster, future.seed = NULL
    ))
    done <- sum(lengths(chunks[seq_len(k)]))
    el <- as.numeric(difftime(Sys.time(), t0, units = "secs"))
    cat(sprintf("[%d/%d] %s | falta ~%s\n", done, length(todo), fmt_time(el),
                fmt_time(el / done * (length(todo) - done))))
  }
}, error = function(e) {
  plan(sequential)
  stop(conditionMessage(e), call. = FALSE)
})
plan(sequential)
t_blocks <- as.numeric(difftime(Sys.time(), t0, units = "secs"))
blk_log <- bind_rows(blk_log)
tmpFiles(remove = TRUE)
write_table(blk_log, "thematic_blocks")

bad_grid <- unique(blk_log$block_id[blk_log$status == "grid_differs"])
if (length(bad_grid)) {
  stop("raster com grade diferente do bloco: ", paste(bad_grid, collapse = ", "), call. = FALSE)
}

# mosaico (vrt) e estilo do QGIS (.qml com o mesmo nome, que o QGIS carrega
# sozinho ao abrir o vrt)
write_qml <- function(cls, file) {
  esc <- function(s) {
    s <- gsub("&", "&amp;", s, fixed = TRUE)
    s <- gsub("<", "&lt;", s, fixed = TRUE)
    s <- gsub(">", "&gt;", s, fixed = TRUE)
    gsub("\"", "&quot;", s, fixed = TRUE)
  }
  entries <- sprintf('        <paletteEntry value="%d" color="%s" label="%s" alpha="255"/>',
                     cls$class_id, cls$color, esc(cls$label))
  writeLines(c(
    "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>",
    '<qgis version="3.40" styleCategories="Symbology">',
    "  <pipe>",
    '    <rasterrenderer type="paletted" band="1" opacity="1" alphaBand="-1" nodataColor="">',
    "      <colorPalette>", entries, "      </colorPalette>",
    "    </rasterrenderer>",
    "  </pipe>",
    "</qgis>"
  ), file, useBytes = TRUE)
}

ext_expected <- as.vector(ext(vect(area_poly)))
for (th in themes) {
  unlink(vrt_file[[th]])
  gdal_utils("buildvrt", jobs$file[jobs$theme == th], vrt_file[[th]], quiet = TRUE)
  v <- rast(vrt_file[[th]])
  if (any(abs(as.vector(ext(v)) - ext_expected) > 1e-6) || any(res(v) != res)) {
    stop("o vrt de ", th, " nao cobre a area esperada", call. = FALSE)
  }
  write_qml(classes[[th]], sub("\\.vrt$", ".qml", vrt_file[[th]]))
}
if (!is_pilot) {
  # mesma grade do dem do 02 (o 05 le os dois bloco a bloco)
  dem_file <- file.path(project_root, "data", "intermediate", "02_prepared_dem", "raster",
                        "gedtm30_v1_2_brazil_5880_30m.tif")
  if (file.exists(dem_file)) {
    same <- compareGeom(rast(vrt_file[["soil"]]), rast(dem_file), crs = FALSE,
                        stopOnError = FALSE)
    if (!same) stop("os rasters nao estao na grade do dem do 02", call. = FALSE)
    cat("grade igual a do dem do 02\n")
  }
}
cat("mosaicos:", paste(basename(vrt_file), collapse = ", "), "em", dir_raster, "\n")

# previas: le a piramide (sem passar pelos 30 m) e pinta cada classe
save_preview <- function(vrt, class_id, color, bg, file, n_out) {
  tmp <- file.path(dir_tmp, paste0("preview_", basename(file), ".tif"))
  gdal_utils("translate", vrt, tmp, quiet = TRUE,
             options = c("-outsize", n_out, n_out, "-r", "nearest"))
  r <- rast(tmp)
  v <- values(r, mat = FALSE)
  v[is.na(v)] <- 0
  pal <- rep(bg, 256)
  pal[class_id + 1] <- color
  m <- matrix(pal[v + 1], nrow = nrow(r), byrow = TRUE)
  nr <- nrow(r)
  nc <- ncol(r)
  rm(r)
  unlink(tmp)
  png(file, width = nc, height = nr)
  par(mar = c(0, 0, 0, 0))
  plot(as.raster(m), interpolate = FALSE)
  dev.off()
  cat("previa:", file, "\n")
}
n_out <- if (is_pilot) bp / 4 else canvas$ncol / 64   # ~120 m no piloto, ~2 km inteiro
save_preview(vrt_file[["geology"]], classes$geology$class_id, classes$geology$color,
             "#ffffff", file.path(dir_fig, "geology_preview.png"), n_out)
save_preview(vrt_file[["soil"]], classes$soil$class_id, classes$soil$color,
             "#ffffff", file.path(dir_fig, "soil_suborders_preview.png"), n_out)
save_preview(vrt_file[["soil"]], classes$soil$class_id, classes$soil$color_order,
             "#ffffff", file.path(dir_fig, "soil_orders_preview.png"), n_out)
save_preview(vrt_file[["country"]], classes$country$class_id, classes$country$color,
             "#dbe9f2", file.path(dir_fig, "country_preview.png"), n_out)
for (th in c("soil_diversity", "lithology_diversity")) {
  save_preview(vrt_file[[th]], classes[[th]]$class_id, classes[[th]]$color, "#ffffff",
               file.path(dir_fig, paste0(th, "_preview.png")), n_out)
}

# 3. conferencia -------------------------------------------------------------

cat("\n# 3. conferencia", strrep("-", 61), "\n")

brazil <- st_read(src$country, quiet = TRUE) %>%
  filter(ISO_A3 == "BRA") %>%
  st_transform(crs_map) %>%
  st_geometry() %>%
  st_union()

set.seed(3)
pts_brazil <- st_as_sf(st_sample(st_intersection(area_poly, brazil), n_points))
pts_area   <- st_as_sf(st_sample(area_poly, n_points))
lim_m      <- res * sqrt(2) / 2     # ponto e centro do pixel: no maximo meia diagonal
min_area   <- if (is_pilot) 50 else min_area_km2

check_theme <- function(th) {
  vec <- st_read(vec_file[[th]], quiet = TRUE, wkt_filter = st_as_text(area_poly))

  # area por classe: poligonos recortados na area dos rasters x pixels
  inside <- seq_len(nrow(vec)) %in% st_contains(area_poly, vec)[[1]]
  cut <- suppressWarnings(st_intersection(vec[!inside, ], area_poly))
  a_vec <- bind_rows(
    tibble(class_id = vec$class_id[inside], a = as.numeric(st_area(vec[inside, ]))),
    tibble(class_id = cut$class_id, a = as.numeric(st_area(cut)))
  ) %>%
    group_by(class_id) %>%
    summarise(area_5880_vector_km2 = sum(a) / 1e6, .groups = "drop")
  a_ras <- blk_log %>%
    filter(theme == th, class_id > 0) %>%
    group_by(class_id) %>%
    summarise(area_5880_raster_km2 = sum(n_px) * res^2 / 1e6, .groups = "drop")
  area <- classes[[th]] %>%
    select(class_id, code, label) %>%
    left_join(a_vec, by = "class_id") %>%
    left_join(a_ras, by = "class_id") %>%
    mutate(theme = th,
           area_5880_vector_km2 = coalesce(area_5880_vector_km2, 0),
           area_5880_raster_km2 = coalesce(area_5880_raster_km2, 0),
           diff_pct = ifelse(area_5880_vector_km2 > 0,
                             100 * (area_5880_raster_km2 / area_5880_vector_km2 - 1),
                             NA_real_),
           checked = area_5880_vector_km2 >= min_area) %>%
    relocate(theme)

  # pontos: classe do raster x classe do poligono que contem o ponto (0 se
  # nenhum). Discordancia longe de qualquer borda e erro
  pts <- if (th == "country") pts_area else pts_brazil
  hit <- st_intersects(pts, vec)
  cls_vec <- vapply(hit, function(h) if (length(h)) as.numeric(vec$class_id[h[1]]) else 0,
                    numeric(1))
  cls_ras <- extract(rast(vrt_file[[th]]), vect(pts))[, 2]
  cls_ras[is.na(cls_ras)] <- 0
  dif <- which(cls_vec != cls_ras)
  near <- st_is_within_distance(pts[dif, ], vec, dist = 1000)   # uma busca so para todos
  d_edge <- vapply(seq_along(dif), function(k) {
    if (!length(near[[k]])) return(Inf)
    min(as.numeric(st_distance(pts[dif[k], ], st_boundary(vec[near[[k]], ]))))
  }, numeric(1))
  points <- tibble(
    theme = th, n_points = nrow(pts), n_inside_polygon = sum(lengths(hit) > 0),
    n_overlap = sum(lengths(hit) > 1), n_differs = length(dif),
    pct_agree = 100 * (1 - length(dif) / nrow(pts)),
    max_edge_dist_differs_m = if (length(dif)) max(d_edge) else NA_real_,
    n_differs_far = sum(d_edge > lim_m)
  )
  list(area = area, points = points)
}

chk <- lapply(themes, check_theme)
area_check  <- bind_rows(lapply(chk, `[[`, "area"))
point_check <- bind_rows(lapply(chk, `[[`, "points"))

cat(sprintf("area por classe, raster x poligonos (classes com >= %s km2; tolerancia %.1f%%):\n",
            fmt_num(min_area), tol_area_pct))
print(as.data.frame(area_check %>%
                      filter(checked) %>%
                      transmute(theme, code, vector_km2 = round(area_5880_vector_km2, 1),
                                raster_km2 = round(area_5880_raster_km2, 1),
                                diff_pct = round(diff_pct, 3))), row.names = FALSE)
cat(sprintf("\npontos sorteados (%d por tema; discordancia so vale a ate %.1f m de uma borda):\n",
            n_points, lim_m))
print(as.data.frame(point_check), row.names = FALSE)

write_table(area_check, "thematic_area_check")
write_table(point_check, "thematic_point_check")

bad_area  <- area_check %>% filter(checked, abs(diff_pct) > tol_area_pct)
bad_point <- point_check %>% filter(n_differs_far > 0 | n_overlap > 0)
if (nrow(bad_area)) {
  stop("area do raster difere dos poligonos em: ",
       paste(bad_area$theme, bad_area$code, collapse = ", "), call. = FALSE)
}
if (nrow(bad_point)) {
  stop("pontos discordam longe da borda ou caem em poligonos sobrepostos: ",
       paste(bad_point$theme, collapse = ", "), call. = FALSE)
}

# resumo ---------------------------------------------------------------------

cat("\n# resumo", strrep("-", 69), "\n")
cat(sprintf("rasters: %d gravados, %d ja existiam, em %s\n",
            nrow(distinct(filter(blk_log, status == "ok"), theme, block_id)),
            nrow(distinct(filter(blk_log, status == "exists"), theme, block_id)),
            fmt_time(t_blocks)))
if (is_pilot) {
  s <- blk_log %>% filter(status == "ok") %>% distinct(theme, block_id, seconds)
  if (nrow(s)) {
    cat("tempo por tema no bloco do piloto:",
        paste(sprintf("%s %.0f s", s$theme, s$seconds), collapse = ", "), "\n")
    n_full <- canvas$nblock_x * canvas$nblock_y * length(themes)
    cat(sprintf("estimativa da rodada inteira (%d rasters, %d workers): ~%s (teto: os blocos so de mar ou fora do Brasil sao mais rapidos)\n",
                n_full, n_workers, fmt_time(mean(s$seconds) * n_full / n_workers)))
  }
}
cat(sprintf("temporarios em %s: %d arquivos\n", dir_tmp, length(list.files(dir_tmp))))
