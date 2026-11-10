# brazil_shaded_relief_maps - 10 pranchas A0 do atlas (relevo, geologia, solos) ----
#
# Python 3.13 com numpy, rasterio, scipy, Pillow, reportlab e PyMuPDF; fontes
# Georgia e Segoe UI do Windows. PowerShell:
#   pip install reportlab                                    (uma vez)
#   python "<projeto>\scripts\10_atlas_plates.py" --draft    (100 dpi, rapido)
#   python "<projeto>\scripts\10_atlas_plates.py"            (300 dpi, as 3 pranchas)
#
# layout definido em 10/11/2026 e escolhido pelo Cassio no lugar da folha do
# 09 (log 21). Adaptado ao projeto com o desenho igual:
#   - caminhos do projeto
#   - le o 08 e o 09 do proprio projeto (map_image, brazil_frac_480,
#     hypso_lut, NODATA); a imagem do mapa e a mesma do 09 (papel e sombra
#     refeitos alem do canvas, log 20)
#   - reportlab do Python do Cassio
#   - previa JPG de cada prancha gerada aqui com o PyMuPDF
#   - autoria e fontes completas (log 22): AUTHOR/AFFIL e as linhas de fonte
#     no topo, usadas tambem pelo 11; rodape com ate 5 linhas quebradas
#
# prancha: A0 vertical (841 x 1189 mm), mapa a ~300 dpi (overview de 240 m do
# VRT de 30 m do 08), titulo em Georgia, legendas em colunas no rodape, norte
# geografico calculado na posicao da seta, escala grafica pelo tamanho real
# do mapa na folha; textos vetoriais no PDF
#
# saida: data/final/atlas/plates_a0/brazil_<tema>_a0.pdf + _a0_preview.jpg +
#   _a0_layout.json (nomes limpos, minusculos e em ingles, log 23; antes
#   BRASIL_<TEMA>_A0.pdf); cache dos mapas em data/intermediate/10_atlas/
#   (apagar o cache se os rasters do 08 mudarem)
# opcoes: --draft  --theme hypsometry|geology|soil_orders|soil_diversity|lithology_diversity
#
# log 25: a serie passou a 5 pranchas (04 diversidade pedologica, 05
#   diversidade litologica, mesmas medidas das figuras dos projetos
#   harmonizados) e o cabecalho mostra "/ 05"; a legenda delas tem as faixas
#   lado a lado com % da area e numero de unidades (tabelas de classes do 03);
#   destaque cobre (04) e azul petroleo (05), os tons escuros das paletas
#   Atlantico e cobre escolhidas pelo Cassio

from pathlib import Path
import sys,importlib.util,csv,json,argparse,math,time
import numpy as np
import rasterio
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
from rasterio.warp import transform
Image.MAX_IMAGE_PIXELS=None
try:
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
except ImportError:
    sys.exit('falta o reportlab: rode  pip install reportlab  e repita')

# caminhos e textos ------------------------------------------------------------

PROJECT=Path(__file__).resolve().parents[1]
CACHE=PROJECT/'data/intermediate/10_atlas/layout_assets'
OUT=PROJECT/'data/final/atlas/plates_a0'
DRAFT=PROJECT/'data/intermediate/10_atlas/draft'
PAGE=(841,1189); MM=72/25.4
PAPER=(238/255,237/255,233/255);INK=(.15,.19,.17);MUTED=(.35,.39,.36);RULE=(.68,.71,.67)

# autoria e fontes (log 22). A referencia da geologia e a mesma passada a
# Iorrana em 05/11/2026: SGB/CPRM litoestratigrafico 1:250.000, agrupado no
# DPS/UFV; a do solo e a do brazil_soil_harmonized. Um lugar so: o 11 le daqui
AUTHOR='Cássio Moquedace'
AFFIL='Departamento de Ciência do Solo, ESALQ/USP'
YEAR='2026'
CREDIT=f'Elaboração: {AUTHOR} ({AFFIL}), {YEAR}.'
CRS_LINE='Sistema de referência SIRGAS 2000; projeção policônica (EPSG:5880).'
RELIEF_LINE=('Relevo sombreado: GEDTM30 v1.2, 30 m (Ho et al., 2025), renderizado no Blender 4.5 (Cycles), '
             'com luz a noroeste (azimute 315°, elevação 45°) e exagero vertical em duas escalas: '
             '128× nas formas amplas e 8× no detalhe.')
GEOLOGY_LINE=('Geologia: Serviço Geológico do Brasil (SGB/CPRM), mapa litoestratigráfico, 1:250.000. '
              'Unidades agrupadas em nove classes de rocha no Departamento de Solos da UFV '
              '(E. B. de Medeiros Júnior, G. P. Rosa, A. Pinheiro, C. Moquedace e C. Baldi), com '
              'nomenclatura segundo a IUGS (Le Maitre et al., 2002; Fettes & Desmons, 2007) e o '
              'Glossário Geológico do SGB (Winge et al., 2001). Paleta inspirada em Lamego (1960).')
SOIL_LINE=('Solos: IBGE, Banco de Dados e Informações Ambientais (BDiA), Pedologia, 1:250.000 (2023). '
           'Classes harmonizadas até o 3º nível categórico e atualizadas para o Sistema Brasileiro de '
           'Classificação de Solos, 6ª edição (Santos et al., 2025).')
# diversidade (log 25): as medidas das figuras de brazil_soil_harmonized (05)
# e brazil_lithology_harmonized (04), refeitas no layout do atlas sobre o
# mesmo relevo; faixas, unidades e areas vem das tabelas de classes do 03
SOIL_DIV_LINE=('Diversidade pedológica: número de componentes (classe dominante, subdominantes e inclusões) '
               'de cada unidade de mapeamento do IBGE, Banco de Dados e Informações Ambientais (BDiA), '
               'Pedologia, 1:250.000 (2023). Tipos de terreno sem contagem.')
LITHO_DIV_LINE=('Diversidade litológica: número de litologias descritas em cada unidade do mapa litoestratigráfico '
                'do Serviço Geológico do Brasil (SGB/CPRM), 1:250.000, na base harmonizada no Departamento de Solos '
                'da UFV (E. B. de Medeiros Júnior, G. P. Rosa, A. Pinheiro, C. Moquedace e C. Baldi).')
RELIEF_SHORT='Relevo: GEDTM30 v1.2 (Ho et al., 2025); exagero vertical em duas escalas (128× / 8×).'
DIVERSITY=('soil_diversity','lithology_diversity')
THEMES={
 'hypsometry':dict(title='Relevo',subtitle='Elevação e formas do terreno',legend='ALTITUDE',index='01',accent='#3e6250',
     sources=[RELIEF_LINE,
              'Cores da legenda referem-se a áreas planas; a luminosidade varia com o sombreado.'],
     short=['Altimetria: GEDTM30 v1.2, 30 m (Ho et al., 2025).',
            'Relevo no Blender; exagero vertical de 128× (formas amplas) e 8× (detalhe).'],
     screen='Altimetria: GEDTM30 v1.2, 30 m (Ho et al., 2025).'),
 'geology':dict(title='Geologia',subtitle='Grupos de rochas sobre relevo sombreado',legend='GRUPOS DE ROCHAS',index='02',accent='#35616b',
     sources=[GEOLOGY_LINE,'Relevo: GEDTM30 v1.2 (Ho et al., 2025); exagero vertical em duas escalas (128× / 8×).'],
     short=['Geologia: SGB/CPRM, mapa litoestratigráfico, 1:250.000; nove classes de rocha agrupadas no '
            'DPS/UFV (Medeiros Júnior, Rosa, Pinheiro, Moquedace e Baldi).',
            'Nomenclatura: IUGS e Glossário Geológico do SGB. Paleta inspirada em Lamego (1960).'],
     screen='Geologia: SGB/CPRM, litoestratigrafia 1:250.000; 9 classes de rocha (DPS/UFV).'),
 'soil_orders':dict(title='Solos',subtitle='Ordens do Sistema Brasileiro de Classificação de Solos',legend='ORDENS DE SOLOS',index='03',accent='#856440',
     sources=[SOIL_LINE,'Relevo: GEDTM30 v1.2 (Ho et al., 2025); exagero vertical em duas escalas (128× / 8×).'],
     short=['Solos: IBGE, BDiA Pedologia, 1:250.000 (2023).',
            'Classes atualizadas para o SiBCS, 6ª edição (Santos et al., 2025).'],
     screen='Solos: IBGE, BDiA Pedologia 1:250.000 (2023); SiBCS, 6ª ed. (Santos et al., 2025).'),
 'soil_diversity':dict(title='Diversidade pedológica',subtitle='Componentes de solo por unidade de mapeamento',
     legend='COMPONENTES POR UNIDADE',index='04',accent='#8a4b45',tag='IBGE · BDIA PEDOLOGIA · 1:250.000',
     note='Percentual da área com solo e número de unidades de mapeamento em cada faixa.',
     extra='Tipos de terreno (água, áreas urbanas, afloramentos e dunas)',
     sources=[SOIL_DIV_LINE,RELIEF_SHORT],
     short=['Pedodiversidade: IBGE, BDiA Pedologia, 1:250.000 (2023).',
            'Componentes (dominante, subdominantes e inclusões) por unidade de mapeamento.'],
     screen='Diversidade pedológica: IBGE, BDiA Pedologia 1:250.000 (2023); componentes por unidade de mapeamento.'),
 'lithology_diversity':dict(title='Diversidade litológica',subtitle='Litologias por unidade litoestratigráfica',
     legend='LITOLOGIAS POR UNIDADE',index='05',accent='#2f6e85',tag='SGB/CPRM · LITOESTRATIGRAFIA · 1:250.000',
     note='Percentual da área mapeada e número de unidades litoestratigráficas em cada faixa.',
     extra='Sem unidade litológica (rios largos e represas)',
     sources=[LITHO_DIV_LINE,RELIEF_SHORT],
     short=['Diversidade litológica: SGB/CPRM, mapa litoestratigráfico, 1:250.000.',
            'Litologias descritas por unidade; base harmonizada no DPS/UFV.'],
     screen='Diversidade litológica: SGB/CPRM, litoestratigrafia 1:250.000; litologias por unidade (DPS/UFV).')}
TAG={'hypsometry':'METROS ACIMA DO NÍVEL DO MAR','geology':'9 GRUPOS LITOLÓGICOS','soil_orders':'SiBCS · 6ª EDIÇÃO · 2025',
     **{t:THEMES[t]['tag'] for t in DIVERSITY}}
N_SERIES=f'{len(THEMES):02d}'

def wrap_lines(s,font,size,width_mm):
    # quebra de linha pela largura real do texto (mm)
    lines=[];cur=''
    for w in s.split():
        cand=(cur+' '+w).strip()
        if pdfmetrics.stringWidth(cand,font,size)/MM<=width_mm or not cur:cur=cand
        else:lines.append(cur);cur=w
    if cur:lines.append(cur)
    return lines

# apoio ---------------------------------------------------------------------------

def load(name,file):
    spec=importlib.util.spec_from_file_location(name,file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def helpers():
    # 09: map_image e brazil_frac_480; 08: hypso_lut, NODATA, shadow_field
    return load('layout09',PROJECT/'scripts/09_layout_maps.py'),load('compose08',PROJECT/'scripts/08_compose_hybrid.py')
def fonts():
    for name,file in [('AtlasSerif','georgia.ttf'),('AtlasItalic','georgiai.ttf'),('AtlasSans','segoeui.ttf'),
                      ('AtlasSemi','seguisb.ttf'),('AtlasLight','segoeuil.ttf')]:
        path=Path('C:/Windows/Fonts')/file
        if not path.exists():path=Path('C:/Windows/Fonts/arial.ttf')
        pdfmetrics.registerFont(TTFont(name,str(path)))
def rgbhex(s):return tuple(int(s.lstrip('#')[i:i+2],16)/255 for i in [0,2,4])
def flat(s):return tuple(float(v) for v in (np.array(rgbhex(s))**1.3))
def preview(pdf,jpg,width_px):
    # previa rasterizada do PDF (PyMuPDF)
    import fitz
    doc=fitz.open(pdf);p=doc[0];z=width_px/p.rect.width
    p.get_pixmap(matrix=fitz.Matrix(z,z)).pil_save(jpg,quality=92);doc.close()

class Plate:
    def __init__(self,file):
        self.c=canvas.Canvas(str(file),pagesize=(PAGE[0]*MM,PAGE[1]*MM),pageCompression=1)
        self.c.setFillColorRGB(*PAPER);self.c.rect(0,0,PAGE[0]*MM,PAGE[1]*MM,fill=1,stroke=0)
        self.boxes=[]
    def text(self,x,y,s,size=22,font='AtlasSans',color=INK,align='left',tracking=0,width=None):
        if width is not None:
            w=(pdfmetrics.stringWidth(s,font,size)+max(0,len(s)-1)*tracking)/MM
            assert w<=width+.5,(s,w,width)
        c=self.c;c.setFillColorRGB(*color)
        t=c.beginText();t.setFont(font,size);t.setCharSpace(tracking)
        w=pdfmetrics.stringWidth(s,font,size)+max(0,len(s)-1)*tracking
        xx=x*MM-(w if align=='right' else w/2 if align=='center' else 0)
        t.setTextOrigin(xx,(PAGE[1]-y)*MM);t.textOut(s);c.drawText(t)
        self.boxes.append(dict(text=s,x_mm=x,y_mm=y,font=font,pt=size,width_mm=w/MM))
    def line(self,x1,y1,x2,y2,color=RULE,width=.5):
        c=self.c;c.setStrokeColorRGB(*color);c.setLineWidth(width);c.line(x1*MM,(PAGE[1]-y1)*MM,x2*MM,(PAGE[1]-y2)*MM)
    def rect(self,x,y,w,h,fill,stroke=None,width=.4):
        c=self.c;c.setFillColorRGB(*fill)
        if stroke:c.setStrokeColorRGB(*stroke);c.setLineWidth(width)
        c.rect(x*MM,(PAGE[1]-y-h)*MM,w*MM,h*MM,fill=1,stroke=bool(stroke))
    def image(self,path,x,y,w,h):self.c.drawImage(str(path),x*MM,(PAGE[1]-y-h)*MM,w*MM,h*MM,mask=None)
    def north(self,x,y,lon,lat):
        # norte geografico calculado na posicao projetada da seta
        xx,yy=transform('EPSG:4326','EPSG:5880',[lon,lon],[lat,lat+.1]);ang=math.atan2(xx[1]-xx[0],yy[1]-yy[0])
        c=self.c;c.saveState();c.translate(x*MM,(PAGE[1]-y)*MM);c.rotate(-math.degrees(ang))
        c.setStrokeColorRGB(*MUTED);c.setFillColorRGB(*INK);c.setLineWidth(.75)
        c.line(0,-11*MM,0,8*MM);p=c.beginPath();p.moveTo(0,11*MM);p.lineTo(-1.5*MM,6*MM);p.lineTo(1.5*MM,6*MM);p.close();c.drawPath(p,fill=1,stroke=0)
        c.restoreState();self.text(x,y-17,'N',18,'AtlasSemi',MUTED,'center')

# legenda e rodape -------------------------------------------------------------------

def legend_data(theme,m09,m08):
    if theme=='geology':
        labels={'carbonatica':'Carbonáticas','felsica':'Félsicas','ferruginosa':'Ferruginosas','mafica':'Máficas','pelitica':'Pelíticas','psamitica':'Psamíticas','psefitica':'Psefíticas','sedimentos_inconsolidados':'Sedimentos inconsolidados','ultramafica':'Ultramáficas'}
        with open(m09.DIR_03/'tables/geology_classes.csv',encoding='utf-8-sig') as f:
            rows=list(csv.DictReader(f,delimiter=';'))
        return [(labels[r['code']],flat(r['color']),'') for r in rows],[]
    with open(m09.DIR_03/'tables/soil_classes.csv',encoding='utf-8-sig') as f:rows=list(csv.DictReader(f,delimiter=';'))
    soils={};other={}
    for r in rows:
        target=soils if r['is_soil'].upper()=='TRUE' else other
        target.setdefault(r['order_label'],(flat(r['color_order']),r['order_symbol']))
    return [(lab,*value) for lab,value in sorted(soils.items())],[(lab,*value) for lab,value in sorted(other.items())]

def fmt_pct(v):return f'{v:.1f}'.replace('.',',')+'%'
def fmt_int(v):return f'{int(round(v)):,}'.replace(',','.')
def diversity_rows(theme,m09):
    # faixas da diversidade (tabela de classes do 03): rotulo, cor plana, % da
    # area (solos: so a area com solo, como na figura 05) e n de unidades; os
    # tipos de terreno ficam fora, como item a parte da legenda
    with open(m09.DIR_03/f'tables/{theme}_classes.csv',encoding='utf-8-sig') as f:rows=list(csv.DictReader(f,delimiter=';'))
    num=lambda s:float(s.replace(',','.')) if s else 0.0
    bands=[r for r in rows if r['code']!='terrain_type'];tot=sum(num(r['area_km2']) for r in bands)
    return [(r['label'],flat(r['color']),fmt_pct(100*num(r['area_km2'])/tot),fmt_int(num(r['n_units']))) for r in bands]

def legend(pg,theme,m09,m08):
    info=THEMES[theme];accent=rgbhex(info['accent'])
    pg.line(42,968,799,968,width=.65)
    pg.text(42,983,info['legend'],19,'AtlasSemi',accent,tracking=1.1)
    pg.text(799,983,TAG[theme],15,'AtlasSans',MUTED,'right',tracking=.7)
    if theme in DIVERSITY:
        # faixas lado a lado, como a legenda da figura 04 de litologia; abaixo
        # de cada uma, % da area e unidades (as barras da figura 05 de solos)
        bands=diversity_rows(theme,m09);W=757;gap=2.5;bw=(W-gap*(len(bands)-1))/len(bands)
        for i,(label,color,pct,nu) in enumerate(bands):
            x=42+i*(bw+gap);pg.rect(x,1003,bw,11,color,(.58,.61,.57),.35)
            pg.text(x+bw/2,1029,label,23,'AtlasSans',INK,'center',width=bw)
            pg.text(x+bw/2,1042,f'{pct} · {nu} unidades',15,'AtlasSans',MUTED,'center',width=bw)
        pg.rect(42,1053,10,7.4,flat(m08.DIV_NODATA),(.58,.61,.57),.35)
        pg.text(57,1059.4,info['extra'],21,'AtlasSans')
        pg.text(42,1091,info['note'],19,'AtlasSans',MUTED)
        return
    if theme=='hypsometry':
        ticks=[0,100,300,500,900,1600,3000];W=757;H=11
        zz=np.interp(np.linspace(0,len(ticks)-1,3600),np.arange(len(ticks)),ticks)
        lut=m08.hypso_lut();colors=np.uint8((lut[np.rint(zz).astype(int)]/255)**1.3*255+.5)
        a=np.repeat(colors[None,:,:],50,axis=0);file=CACHE/'legend_hypso.png';Image.fromarray(a).save(file)
        pg.image(file,42,1008,W,H)
        for i,z in enumerate(ticks):
            x=42+W*i/(len(ticks)-1);pg.line(x,1020,x,1023,width=.6)
            pg.text(x,1036,f'{z:,}'.replace(',','.'),22,'AtlasSans',INK,'center')
        pg.text(42,1060,'Baixadas',18,'AtlasItalic',MUTED)
        pg.text(799,1060,'Terras altas',18,'AtlasItalic',MUTED,'right')
        pg.text(42,1091,'A rampa representa altitude; as sombras revelam as formas do terreno.',19,'AtlasSans',MUTED)
    else:
        items,other=legend_data(theme,m09,m08)
        nrows=5 if theme=='soil_orders' else 3
        colw=757/3
        for i,(label,color,symbol) in enumerate(items):
            col=i//nrows;row=i%nrows;x=42+col*colw;y=1001+row*14
            pg.rect(x,y,10,7.4,color,(.58,.61,.57),.35)
            pg.text(x+15,y+6.4,label,23,'AtlasSans',INK,width=colw-22)
        if theme=='soil_orders':
            pg.text(42,1080,'OUTRAS FEIÇÕES',14,'AtlasSemi',MUTED,tracking=.9)
            for i,(label,color,symbol) in enumerate(other):
                x=42+i*757/4;pg.rect(x,1090,8,6,color,(.58,.61,.57),.35)
                pg.text(x+12,1095.3,label,17,'AtlasSans',INK,width=757/4-16)
        else:
            pg.rect(42,1052,10,7.4,flat(m08.NODATA),(.58,.61,.57),.35)
            pg.text(57,1058.4,'Sem classe litológica',21,'AtlasSans')
            pg.text(42,1091,'As cores distinguem grupos de rochas, não idades geológicas.',19,'AtlasSans',MUTED)

def footer(pg,theme,m_px,dpi):
    pg.line(42,1116,799,1116,width=.65)
    # fontes e metodo em ate 5 linhas de 15 pt, quebradas na largura de 548 mm
    yy=1129
    for s in THEMES[theme]['sources']+[CRS_LINE]:
        for ln in wrap_lines(s,'AtlasSans',15,548):pg.text(42,yy,ln,15,'AtlasSans',MUTED,width=548);yy+=7.2
    assert yy<=1166.5,('fontes passam do rodape',theme,yy)
    # escala tirada do tamanho real do mapa na folha
    denominator=m_px*dpi/.0254
    w_mm=500000/(denominator/1000);x=799-w_mm;y=1132
    pg.text(799,1128,'ESCALA GRÁFICA',13,'AtlasSemi',MUTED,'right',tracking=.7)
    for i in range(2):pg.rect(x+i*w_mm/2,y,w_mm/2,1.8,INK if i==0 else PAPER,INK,.5)
    for km in [0,250,500]:
        xx=x+w_mm*km/500;pg.text(xx,1143,str(km),15,'AtlasSans',MUTED,'center')
    pg.text(799,1154,'km',13,'AtlasSans',MUTED,'right')
    pg.text(799,1163,f'1:{round(denominator/100000)*100000:,}'.replace(',','.')+' · A0',14,'AtlasSans',MUTED,'right')
    pg.text(42,1173,f'ELABORAÇÃO: {AUTHOR.upper()}  ·  {AFFIL.upper()}',13,'AtlasSemi',MUTED,tracking=.5,width=548)
    pg.text(799,1173,f'SÉRIE BRASIL   /   {THEMES[theme]["index"]}   /   2026',13,'AtlasSans',MUTED,'right',tracking=.5)
    return denominator

# prancha ------------------------------------------------------------------------------

def brazil_frac(m09):
    maskfile=CACHE/'frac480.npy'
    if maskfile.exists():return np.load(maskfile)
    with open(m09.BLOCKS,encoding='utf-8-sig') as f:ids=[b['block_id'] for b in csv.DictReader(f,delimiter=';') if b['has_brazil'].upper()=='TRUE']
    frac=np.zeros((9216,9216),dtype='float32')
    with ThreadPoolExecutor(max_workers=6) as pool:
        for bid,a in pool.map(m09.brazil_frac_480,ids):
            r,c=int(bid[1:3]),int(bid[5:7]);frac[r*512:(r+1)*512,c*512:(c+1)*512]=a
    np.save(maskfile,frac);return frac

def map_asset(theme,dpi,m09,m08,frac,maxpx):
    # imagem do mapa (09.map_image) em cache: 300 dpi serve ao 10 e ao 11
    factor=32 if dpi<200 else 8
    mapfile=CACHE/f'{theme}_map_{dpi}.png';metafile=CACHE/f'{theme}_map_{dpi}.json'
    from atlas_cache import source_signature
    vrt=m09.DIR_30M/f'brazil_{theme}_{m09.PRES}_30m.vrt'
    paths=[vrt]
    if theme in m08.CLASS_SRC:
        paths.append(m09.DIR_03/'tables'/f'{m08.CLASS_SRC[theme][0]}_classes.csv')
    signature=source_signature(*paths,settings=(dpi,factor,maxpx))
    metadata=json.loads(metafile.read_text()) if metafile.exists() else {}
    if not mapfile.exists() or metadata.get('source_signature')!=signature:
        mp,m_px,origin,fb=m09.map_image(theme,frac,m08,factor,maxpx,maxpx)
        mp.save(mapfile,compress_level=4)
        metafile.write_text(json.dumps(dict(size=mp.size,m_px=m_px,origin=origin,source_overview_m=factor*30,source_signature=signature),indent=2))
        del mp,fb
    return mapfile,json.loads(metafile.read_text())

def make(theme,dpi,m09,m08,frac,directory):
    t=time.time();info=THEMES[theme];directory.mkdir(parents=True,exist_ok=True)
    mapfile,data=map_asset(theme,dpi,m09,m08,frac,round(785/25.4*dpi));size=data['size'];m_px=data['m_px']
    mm_w=size[0]*25.4/dpi;mm_h=size[1]*25.4/dpi;mx=(841-mm_w)/2;my=164+(785-mm_h)/2
    file=directory/f'brazil_{theme}_a0.pdf';pg=Plate(file)
    pg.c.setTitle(f'Brasil | {info["title"]}');pg.c.setSubject('Mapa equilibrado sobre relevo sombreado; prancha A0 vertical')
    pg.c.setAuthor(AUTHOR);pg.c.setCreator('Atlas Brasil · composição cartográfica')
    pg.text(42,48,'BRASIL',26,'AtlasSemi',INK,tracking=5.8)
    pg.text(799,46,'CARTOGRAFIA DO TERRITÓRIO',14,'AtlasSans',MUTED,'right',tracking=1.5)
    pg.text(42,107,info['title'],112,'AtlasSerif',INK)
    pg.text(42,132,info['subtitle'],24,'AtlasLight',MUTED)
    pg.line(776,77,799,77,color=rgbhex(info['accent']),width=2)
    pg.text(799,104,info['index'],42,'AtlasLight',rgbhex(info['accent']),'right')
    pg.text(799,122,f'/ {N_SERIES}',16,'AtlasSans',MUTED,'right')
    pg.image(mapfile,mx,my,mm_w,mm_h)
    r0,c0=data['origin']
    arrow_x=2744310+c0*480+(776-mx)*dpi/25.4*m_px
    arrow_y=10637160-r0*480-(192-my)*dpi/25.4*m_px
    lon,lat=transform('EPSG:5880','EPSG:4326',[arrow_x],[arrow_y]);pg.north(776,192,lon[0],lat[0])
    legend(pg,theme,m09,m08);den=footer(pg,theme,m_px,dpi)
    pg.c.showPage();pg.c.save()
    preview(file,directory/f'brazil_{theme}_a0_preview.jpg',1981)
    data.update(dict(theme=theme,dpi=dpi,page_mm=PAGE,map_mm=[mx,my,mm_w,mm_h],scale_denominator=den,
                     source=str(PROJECT/f'data/final/30m/brazil_{theme}_balanced_30m.vrt'),text_boxes=pg.boxes))
    (directory/f'brazil_{theme}_a0_layout.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    esc=f'{round(den/100000)*100000:,}'.replace(',','.')
    print(f'{theme}: {file.name} ({file.stat().st_size/1e6:.0f} MB), escala 1:{esc}, {time.time()-t:.0f} s',flush=True)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--draft',action='store_true');ap.add_argument('--theme',default='all',choices=['all',*THEMES]);args=ap.parse_args()
    CACHE.mkdir(parents=True,exist_ok=True)
    fonts();m09,m08=helpers();frac=brazil_frac(m09)
    dpi=100 if args.draft else 300;directory=DRAFT if args.draft else OUT
    print(f"\n# 10 atlas plates {'-' * 57}\n{dpi} dpi; saida em {directory}",flush=True)
    for theme in THEMES if args.theme=='all' else [args.theme]:make(theme,dpi,m09,m08,frac,directory)

if __name__=='__main__':main()
