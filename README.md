# brazil_shaded_relief_maps

Série de mapas do Brasil com relevo sombreado renderizado no Blender, todos a
30 m e no mesmo relevo, luz, projeção e enquadramento:

1. **Relevo**: cores hipsométricas sobre o sombreado
2. **Geologia**: 9 grupos de rocha (`brazil_lithology_harmonized`), com as cores do Mapa Geológico do Brasil de Lamego (1960), o mapa modelo
3. **Solos**: classes do SiBCS 2025, 6ª ed., com as cores oficiais do Anexo I (`brazil_soil_harmonized`)
4. **Diversidade pedológica**: número de componentes (classe dominante, subdominantes e inclusões) por unidade de mapeamento do IBGE/BDiA
5. **Diversidade litológica**: número de litologias descritas por unidade do mapa litoestratigráfico do SGB/CPRM

**Site:** https://moquedace.github.io/brazil_shaded_relief_maps/, com as
pranchas, as versões de tela, um visualizador com zoom (até 120 m) e os
downloads. Os PDFs A0 originais, para gráfica, ficam nas
[releases](https://github.com/moquedace/brazil_shaded_relief_maps/releases).
Só produtos são distribuídos: os dados de origem e os rasters de 30 m não
estão no repositório nem no site.

Inspiração: Souza (2020), *Mapas em representação tridimensional*, Confins 47
(https://doi.org/10.4000/confins.31886), que usou SRTM e o mapa geológico de
Lamego (1960, 1:5.000.000) no Blender pelo método de Daniel Huffman. Aqui o
relevo vem do GEDTM30 (terreno sem vegetação) e os temas das bases harmonizadas
em 1:250.000.

## Dados de entrada (somente leitura)

| Dado | Onde |
|---|---|
| GEDTM30 v1.2, 30 m | `cassio/data/gedtm30_brazil/` (baixado pelo 01) |
| Geologia | `projects/brazil_lithology_harmonized/data/final/` |
| Solos (SiBCS 2025) | `projects/brazil_soil_harmonized/data/final/` |
| Contorno do Brasil | `cassio/data/lac_countries/wb_countries_admin0_10m/` |

## Scripts

| Script | Faz | Situação |
|---|---|---|
| `01_download_gedtm30_brazil.py` | baixa o GEDTM30 v1.2 do Brasil em tiles de 4096 px + VRT | rodado 07/11/2026 (659 tiles, 15,7 GB) |
| `02_prepare_dem.R` | reprojeção para EPSG:5880 a 30 m, heightmaps PNG 16 bits em blocos de 10.240 px para o Blender | rodado 08/11/2026: DEM 30 m (48 GB) e 324 heightmaps de 0 a 7.000 m (21 GB), conferidos contra o DEM |
| `03_rasterize_thematic.R` | geologia (9 grupos), solos (subordens do SiBCS 2025, que dão também as ordens), máscara de países e, desde o log 25, diversidade pedológica e litológica (6 faixas cada) em rasters de classe na mesma grade e blocos de 30 m, com tabelas de classes e cores; a hipsometria sai direto do DEM no 05 | rodado 08/11/2026: 972 rasters em 8 min; áreas a até 0,007% dos polígonos, pontos conferidos. Cores da geologia trocadas pelas do Lamego no mesmo dia (log 11): rodar de novo só regrava tabelas e prévias. Temas de diversidade rodados em 10/11/2026 (log 25): 648 rasters em 6 min, áreas a até 0,001% dos polígonos |
| `04_render_relief.py` | Blender por script (bpy), um PNG 16 bits por bloco, só o núcleo, com world file; exagero vertical em vezes reais | piloto a 100% ok (E = 1, 2, 4); `--mode test`: 6 blocos extremos x E = 1, 2, 4, 8 para escolher o exagero (log 11-12). **Rodado 08-09/11/2026 em E8 (log 13):** 183 blocos em 15,4 h (~5 min e ~53 GB de pico por bloco), conferidos; `scripts/tools/check_04_render.ps1` confere o andamento |
| `05_compose_maps.R` | sombreado x cores (hipsometria, geologia, solos), legenda, barras de área, escala | modos `pilot`, `test` e `soft` rodados (08/11/2026): folhas por bloco e exagero, a 480 m e a 30 m, para escolher o exagero (E8, log 12). Modo `preview` escrito em 09/11/2026 (log 14): Brasil inteiro em E8 a 480 m com gama 1, 0,7 e 0,5, para escolher o gama; a composição final a 30 m entra depois |
| `06_prepare_hybrid_terrain.py` | terreno em duas escalas da rodada 2 (macro gaussiana de 2 km em E128, detalhe em E8): macro nacional a 120 m, entorno distante a 480 m e heightmaps híbridos por bloco | escrito 09/11/2026 (log 15); `national` (14 min), `test` e `blocks` rodados 09/11/2026 (log 16): 183 heightmaps híbridos em 8 min (7,1 GB), iguais pixel a pixel aos dos testes nas áreas em comum |
| `07_render_hybrid.py` | Blender: plano de perto de 30 m + anel de entorno distante de 480 m, câmera só no núcleo; um render cinza por bloco (as cores e a versão dramática saem no pós) | escrito 09/11/2026 (log 15); `--mode test` rodado (log 16): reproduz a rodada 2 (MAE 0,2–0,6), margem de 1.024 px basta, emendas sem degrau; o entorno distante clareia as sombras até 1.200 km e para no canvas inteiro (< 0,5 nível) → **full com `--context-km 5000`**; `scripts/tools/check_07_test.py` confere. **Rodado 09-10/11/2026 (log 17):** 183 blocos em ~20 h (~6,5 min e ~27 GB por bloco), conferidos por `scripts/tools/check_07_full.py` (formato, world file, estouro, 327 emendas sem viés de tom, mosaico a 480 m) |
| `08_compose_hybrid.py` | cores dos temas (3 + 2 de diversidade desde o log 25, `--themes`) sobre o render cinza do 07, nas duas apresentações da rodada 2 (dramática: cor × sombreado + curva 1,6; equilibrada: cor^1,3 e sombreado com gama 0,7), Brasil sobre papel com sombra projetada | escrito 10/11/2026 (log 18), conferido contra a rodada 2 (`scripts/tools/check_08_formulas.py`); `--mode preview` (480 m + janelas a 30 m) rodado 10/11/2026 (14 min). **Equilibrada escolhida (log 19):** `--mode full` grava GeoTIFF RGB de 30 m por bloco e tema (324 blocos, overviews, VRT com overviews) em `data/final/30m/`. **Rodado 10/11/2026:** 972 tiles em 29,7 min (50,4 GB), conferidos; diversidade (paletas cobre e Atlântico) em 24,8 min, 16 GB por tema |
| `09_layout_maps.py` | imagem do mapa para as folhas (`map_image`: recorte, leitura do VRT, papel e sombra refeitos além do canvas) | escrito 10/11/2026 (log 20); a folha própria dele foi substituída pelo atlas (log 21) e segue só como biblioteca do 10 e do 11 |
| `10_atlas_plates.py` | atlas: pranchas A0 verticais (Relevo, Geologia, Solos e, desde o log 25, Diversidade pedológica e Diversidade litológica) | **rodado 10/11/2026 (log 21, 25):** 5 PDFs de 102–120 MB a 300 dpi; precisa de `reportlab` |
| `11_atlas_multiformat.py` | atlas: A0 deitado com os 3 mapas, telas 1920 x 1440 (os 5 temas) e 3840 x 2160, HTML de consulta | **rodado 10/11/2026:** 7 PDFs conferidos (tamanho e classes); roda depois do 10 |
| `12_build_site.py` | site estático em `data/final/site/`: página com as 5 pranchas, zoom Deep Zoom (OpenSeadragon, WebP, até 120 m), PDFs A0 leves, telas, fontes, citação e licença | rodado 10/11/2026 (log 25): 0,72 GB, 36 mil arquivos, zoom de 5 temas em 13 min; `scripts/tools/publish_site.ps1` publica o site no ramo `gh-pages` e os PDFs A0 originais na release |

**Produto (10/11/2026):** `data/final/30m/brazil_<tema>_balanced_30m.vrt`
(hipsometria, geologia e ordens de solo; abrir no QGIS), com os tiles em
`<tema>_balanced/` e uma vista de 1920 m em `brazil_<tema>_balanced_1920m.jpg` (balanced = apresentação equilibrada).
Atlas para impressão e tela: `data/final/atlas/plates_a0/`
(`brazil_<tema>_a0.pdf`) e `data/final/atlas/multiformat/` (`brazil_three_maps_a0.pdf`,
`brazil_<tema>_screen.pdf/png`, `brazil_atlas.html`), scripts 10 e 11.

O método da rodada 2 (terreno em duas escalas, aceito pelo Cassio) está
documentado em `docs/round2/` (cópia local, fora do repositório). Os scripts 01-05 e as saídas deles ficaram como estavam.

O 01 é Python porque usa leitura remota do COG em paralelo (rasterio). Os
demais serão em R, exceto o 04, que roda dentro do Blender (bpy).

Software: Python 3.13 com rasterio, geopandas, pandas; R 4.6 com terra e sf;
Blender 4.5 LTS.

Histórico de decisões em `docs/project_log.md` (só na cópia local; `docs/`
fica fora do repositório público).

## Licença

Mapas, imagens e textos: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.pt-br),
com citação da autoria e das fontes dos dados. Código: MIT (`LICENSE`).

Como citar: Moquedace, C. M. (2026). *Brasil: relevo, geologia, solos e
diversidade*. Série cartográfica com relevo sombreado a 30 m. Departamento de
Ciência do Solo, ESALQ/USP. https://moquedace.github.io/brazil_shaded_relief_maps/

## Referências

- Ho, Y.-F.; Grohmann, C. H.; Lindsay, J.; Reuter, H. I.; Parente, L.; Witjes, M.; Hengl, T. (2025) GEDTM30: global ensemble digital terrain model at 30 m and derived multiscale terrain variables. *PeerJ* 13, e19673. https://doi.org/10.7717/peerj.19673
- IBGE (2023) Banco de Dados e Informações Ambientais (BDiA): Pedologia, 1:250.000. https://bdiaweb.ibge.gov.br
- Santos, H. G. et al. (2025) *Sistema Brasileiro de Classificação de Solos*. 6. ed. Brasília: Embrapa.
- Serviço Geológico do Brasil (SGB/CPRM). Mapa litoestratigráfico do Brasil, 1:250.000.
- World Bank. World Bank Official Boundaries (Admin 0), CC BY 4.0. https://datacatalog.worldbank.org/search/dataset/0038272
- Huffman, D. (2017, rev. 2023) *Creating Shaded Relief in Blender*. https://somethingaboutmaps.wordpress.com/2017/11/16/creating-shaded-relief-in-blender/
- Davies, J. *geoblender*. https://github.com/joewdavies/geoblender (consultado; sem licença, nenhum código copiado)
- Souza, A. (2020) Mapas em representação tridimensional. *Confins* 47. https://doi.org/10.4000/confins.31886
