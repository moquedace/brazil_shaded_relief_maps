# brazil_shaded_relief_maps - 11 atlas multiformato (A0 conjunto, telas, HTML) -----
#
# Python 3.13 com numpy, rasterio, Pillow, reportlab e PyMuPDF. PowerShell,
# depois do 10 (usa o mesmo cache de mapas a 300 dpi):
#   python "<projeto>\scripts\11_atlas_multiformat.py"
#
# layout definido em 10/11/2026 (atlas multiformato), escolhido pelo
# Cassio (log 21). Adaptado ao projeto com o desenho igual; mudou so:
#   - caminhos do projeto e importacao do 10
#   - os PNG das telas e a previa do A0 sao rasterizados aqui (PyMuPDF)
#   - readme com os caminhos do projeto; o ZIP so com --zip
#   - nomes de arquivo limpos, minusculos e em ingles (log 23); antes
#     BRASIL_*, DIGITAL_*, ABRIR_ATLAS, LEIA_ME
#   - log 25: telas e HTML tambem para os 2 mapas de diversidade (pedologica e
#     litologica, pranchas 04 e 05 do 10); o A0 conjunto e a tela conjunta
#     continuam com os 3 mapas (relevo, geologia, solos)
#
# saida em data/final/atlas/multiformat/:
#   brazil_three_maps_a0.pdf              A0 deitado, os 3 mapas na mesma escala
#   brazil_<tema>_screen.pdf/.png         telas 1920 x 1440 (4:3)
#   brazil_three_maps_screen.pdf/.png     tela 3840 x 2160 (16:9)
#   brazil_atlas.html + assets/           consulta local, sem internet
#   brazil_three_maps_a0_preview.jpg, layout_manifest.json, verification.json, readme.md

from pathlib import Path
import sys,json,csv,math,time,html,zipfile,importlib.util,argparse
import numpy as np
from rasterio.warp import transform
from PIL import Image
Image.MAX_IMAGE_PIXELS=None

PROJECT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('atlas10',PROJECT/'scripts/10_atlas_plates.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab import rl_config
rl_config.useA85=0

O=PROJECT/'data/final/atlas/multiformat'
A=O/'assets';CACHE=base.CACHE
THEMES=list(base.THEMES)                       # telas, HTML e mapas: os 5
JOINT=['hypsometry','geology','soil_orders']   # A0 conjunto e tela conjunta
MM=72/25.4;PAPER=base.PAPER;INK=base.INK;MUTED=base.MUTED;RULE=base.RULE
META={};BOXES={};m09=None;m08=None

# folha -------------------------------------------------------------------------------

class Board:
    def __init__(self,file,w,h,unit=1):
        self.w,self.h,self.u=w,h,unit;self.boxes=[]
        self.c=canvas.Canvas(str(file),pagesize=(w*unit,h*unit),pageCompression=1)
        self.c.setFillColorRGB(*PAPER);self.c.rect(0,0,w*unit,h*unit,fill=1,stroke=0)
        self.c.setAuthor(base.AUTHOR);self.c.setCreator('Atlas Brasil · composição multiformato')
    def text(self,x,y,s,size=24,font='AtlasSans',color=INK,align='left',tracking=0,maxw=None):
        tw=pdfmetrics.stringWidth(s,font,size)+max(0,len(s)-1)*tracking
        if maxw is not None:assert tw/self.u<=maxw+.5,(s,tw/self.u,maxw)
        xx=x*self.u-(tw if align=='right' else tw/2 if align=='center' else 0)
        self.c.setFillColorRGB(*color);t=self.c.beginText();t.setFont(font,size);t.setCharSpace(tracking)
        t.setTextOrigin(xx,(self.h-y)*self.u);t.textOut(s);self.c.drawText(t)
        assert xx>=-.5 and xx+tw<=self.w*self.u+.5,(s,'horizontal page overflow')
        assert 0<y<self.h,(s,'vertical page overflow')
        self.boxes.append(dict(text=s,x=x,y=y,size_pt=size,font=font,width=tw/self.u))
    def wrap(self,x,y,s,width,size=24,lead=34,font='AtlasSans',color=MUTED):
        words=s.split();lines=[];cur=''
        for word in words:
            cand=(cur+' '+word).strip()
            if pdfmetrics.stringWidth(cand,font,size)/self.u<=width or not cur:cur=cand
            else:lines.append(cur);cur=word
        if cur:lines.append(cur)
        for line in lines:self.text(x,y,line,size,font,color,maxw=width);y+=lead
        return y
    def line(self,x1,y1,x2,y2,color=RULE,width=.6):
        self.c.setStrokeColorRGB(*color);self.c.setLineWidth(width)
        self.c.line(x1*self.u,(self.h-y1)*self.u,x2*self.u,(self.h-y2)*self.u)
    def rect(self,x,y,w,h,fill,stroke=None,width=.4):
        self.c.setFillColorRGB(*fill)
        if stroke:self.c.setStrokeColorRGB(*stroke);self.c.setLineWidth(width)
        self.c.rect(x*self.u,(self.h-y-h)*self.u,w*self.u,h*self.u,fill=1,stroke=bool(stroke))
    def image(self,path,x,y,w,h):self.c.drawImage(str(path),x*self.u,(self.h-y-h)*self.u,w*self.u,h*self.u)
    def close(self):self.c.showPage();self.c.save()

def ensure_assets():
    global m09,m08
    base.fonts();m09,m08=base.helpers();A.mkdir(parents=True,exist_ok=True);CACHE.mkdir(parents=True,exist_ok=True)
    frac=base.brazil_frac(m09)
    for theme in THEMES:
        file,META[theme]=base.map_asset(theme,300,m09,m08,frac,9272)
        with Image.open(file) as im:
            for target,tag in [(4241,'print'),(2320,'digital')]:
                dst=A/f'map_{theme}_{tag}.png'
                if not dst.exists() or dst.stat().st_mtime_ns<file.stat().st_mtime_ns:
                    im.resize((target,round(im.height*target/im.width)),Image.Resampling.LANCZOS).save(dst,compress_level=4)
        print('mapa pronto',theme,flush=True)

def map_image(pg,theme,x,y,w,h,quality='digital'):
    file=A/f'map_{theme}_{quality}.png'
    with Image.open(file) as im:ar=im.width/im.height
    ww=min(w,h*ar);hh=ww/ar;xx=x+(w-ww)/2;yy=y+(h-hh)/2
    pg.image(file,xx,yy,ww,hh)
    info=META[theme];meters_per_unit=info['size'][0]*info['m_px']/ww
    return dict(x=xx,y=yy,w=ww,h=hh,mpu=meters_per_unit)

def north(pg,theme,box,x,y,digital=True):
    info=META[theme];r,c=info['origin'];wx=2744310+c*480+(x-box['x'])*box['mpu'];wy=10637160-r*480-(y-box['y'])*box['mpu']
    lon,lat=transform('EPSG:5880','EPSG:4326',[wx],[wy]);xx,yy=transform('EPSG:4326','EPSG:5880',[lon[0],lon[0]],[lat[0],lat[0]+.1])
    ang=math.degrees(math.atan2(xx[1]-xx[0],yy[1]-yy[0]));u=pg.u;sz=19 if digital else 5
    c=pg.c;c.saveState();c.translate(x*u,(pg.h-y)*u);c.rotate(-ang)
    c.setStrokeColorRGB(*MUTED);c.setFillColorRGB(*INK);c.setLineWidth(.8 if digital else .6)
    c.line(0,-sz*u,0,sz*u);p=c.beginPath();p.moveTo(0,(sz+3)*u);p.lineTo(-sz*.17*u,sz*.55*u);p.lineTo(sz*.17*u,sz*.55*u);p.close();c.drawPath(p,fill=1,stroke=0);c.restoreState()
    pg.text(x,y-sz-12 if digital else y-sz-4,'N',22 if digital else 12,'AtlasSemi',MUTED,'center')

def scale(pg,x,y,box,digital=True,km=1000,numeric=False):
    bw=km*1000/box['mpu'];bh=4 if digital else 1.5;fs=24 if digital else 12
    pg.text(x,y-(16 if digital else 5),'ESCALA GRÁFICA',20 if digital else 11,'AtlasSemi',MUTED,tracking=.6)
    for i in range(2):pg.rect(x+bw*i/2,y,bw/2,bh,INK if i==0 else PAPER,INK,.6)
    for i in [0,1,2]:
        lab=f'{int(km*i/2):,}'.replace(',','.')+(' km' if i==2 else '')
        pg.text(x+bw*i/2,y+(38 if digital else 9),lab,fs,'AtlasSans',MUTED,'center')
    if numeric:pg.text(x+bw,y+18,f'1:{round(box["mpu"]*1000/100000)*100000:,}'.replace(',','.')+' · A0',12,'AtlasSans',MUTED,'right')
    return bw

def chip(pg,x,y,label,color,sw=27,sh=23,size=30,rowwidth=570,symbol=''):
    pg.rect(x,y,sw,sh,color,(.57,.61,.57),.5)
    pg.text(x+sw+(18 if pg.u==1 else 4),y+sh*.87,label,size,'AtlasSans',INK,maxw=rowwidth-sw-(20 if pg.u==1 else 5))

def gradient(pg,x,y,w,h,ticks,vertical=False):
    n=1800
    z=np.interp(np.linspace(0,len(ticks)-1,n),np.arange(len(ticks)),ticks)
    lut=m08.hypso_lut();rgb=np.uint8((lut[np.rint(z).astype(int)]/255)**1.3*255+.5)
    a=np.repeat(rgb[:,None,:],32,axis=1) if vertical else np.repeat(rgb[None,:,:],32,axis=0)
    file=A/f'ramp_{"v" if vertical else "h"}_{len(ticks)}.png';Image.fromarray(a).save(file)
    pg.image(file,x,y,w,h)

def discrete(theme):return base.legend_data(theme,m09,m08)

# A0 conjunto -------------------------------------------------------------------------

def print_legend(pg,theme,x,y,w):
    accent=base.rgbhex(base.THEMES[theme]['accent']);pg.line(x,y-12,x+w,y-12,width=.65)
    pg.text(x,y,base.THEMES[theme]['legend'],16,'AtlasSemi',accent,tracking=.8)
    if theme=='hypsometry':
        ticks=[0,100,300,500,900,1600,3000];gradient(pg,x,y+15,w,7,ticks)
        for i,z in enumerate(ticks):
            xx=x+i*w/(len(ticks)-1);pg.line(xx,y+23,xx,y+25,width=.5);pg.text(xx,y+34,f'{z:,}'.replace(',','.'),14,'AtlasSans',INK,'center')
        pg.text(x,y+53,'Altitude (m) · intervalos cromáticos não lineares.',13,'AtlasSans',MUTED,maxw=w)
        pg.wrap(x,y+83,'Cores representam a altitude. O sombreado evidencia as formas do terreno.',w,18,10,'AtlasLight',MUTED)
    else:
        items,other=discrete(theme)
        if theme=='geology':items=items+[('Sem classe litológica',base.flat(m08.NODATA),'')]
        nr=7 if theme=='soil_orders' else 5;cw=w/2
        for i,(label,color,symbol) in enumerate(items):
            chip(pg,x+(i//nr)*cw,y+15+(i%nr)*12,label,color,6,5.8,17,cw)
        if theme=='soil_orders':
            yy=y+111;pg.text(x,yy,'OUTRAS FEIÇÕES',12,'AtlasSemi',MUTED,tracking=.6)
            for i,(label,color,symbol) in enumerate(other):chip(pg,x+(i%2)*cw,yy+9+(i//2)*11,label,color,5.5,5,14,cw)
        else:pg.wrap(x,y+102,'Grupos litológicos, não idades geológicas. As cores-base são moduladas pelo sombreado.',w,16,9,'AtlasLight',MUTED)

def make_print():
    file=O/'brazil_three_maps_a0.pdf';pg=Board(file,1189,841,MM);pg.c.setTitle('Brasil | Relevo, geologia e solos | A0')
    pg.c.setSubject('Prancha conjunta A0 horizontal, 1189 × 841 mm; impressão')
    pg.text(32,27,'SÉRIE CARTOGRÁFICA',16,'AtlasSemi',MUTED,tracking=2)
    pg.text(32,66,'Brasil',80,'AtlasSerif')
    pg.text(32,91,'Relevo, geologia e solos',28,'AtlasLight',MUTED)
    pg.text(1157,35,'MESMO ENQUADRAMENTO E ESCALA',14,'AtlasSans',MUTED,'right',tracking=.8)
    pg.text(1157,56,'SIRGAS 2000 / POLICÔNICA',15,'AtlasSans',MUTED,'right')
    pg.text(1157,83,'2026',25,'AtlasLight',MUTED,'right');pg.line(32,112,1157,112,width=.8)
    boxes=[]
    for i,t in enumerate(JOINT):
        x=32+i*383;w=359;info=base.THEMES[t]
        pg.text(x,141,info['title'],37,'AtlasSerif')
        pg.text(x+w,139,info['index'],18,'AtlasSemi',base.rgbhex(info['accent']),'right')
        box=map_image(pg,t,x,160,w,359,'print');boxes.append(box);north(pg,t,box,x+w-12,188,False)
        print_legend(pg,t,x,556,w)
        # fontes do tema (versao curta do 10), quebradas na largura da coluna
        yy=748
        for s in base.THEMES[t]['short']:
            for ln in base.wrap_lines(s,'AtlasSans',13,w):pg.text(x,yy,ln,13,'AtlasSans',MUTED,maxw=w);yy+=6.6
        assert yy<=781,('fontes passam da coluna',t,yy)
    pg.line(32,785,1157,785,width=.7)
    pg.text(32,805,f'ELABORAÇÃO: {base.AUTHOR.upper()}  ·  {base.AFFIL.upper()}  ·  {base.YEAR}',12,'AtlasSemi',MUTED,tracking=.5)
    pg.text(32,821,'SIRGAS 2000 · PROJEÇÃO POLICÔNICA · EPSG:5880 · CORES-BASE MODULADAS PELO SOMBREADO · RELEVO COM EXAGERO 128× / 8×',12,'AtlasSans',MUTED)
    bw=1000000/boxes[0]['mpu'];scale(pg,1150-bw,800,boxes[0],False,1000,True)
    pg.close();BOXES['print']=pg.boxes
    print('A0 conjunto pronto',flush=True)

# telas ---------------------------------------------------------------------------------

def digital_legend(pg,theme,x,y,w):
    info=base.THEMES[theme];pg.text(x,y,info['legend'],29,'AtlasSemi',base.rgbhex(info['accent']),tracking=1)
    if theme in base.DIVERSITY:
        # faixas com % da area e unidades (log 25)
        pg.text(x,y+38,base.TAG[theme],20,'AtlasSans',MUTED,tracking=.6,maxw=w)
        for i,(label,color,pct,nu) in enumerate(base.diversity_rows(theme,m09)):
            yy=y+86+i*64;chip(pg,x,yy,label,color,29,25,31,w*.45)
            pg.text(x+w,yy+22,f'{pct} · {nu} unid.',24,'AtlasSans',MUTED,'right')
        yy=y+86+6*64+14;pg.line(x,yy,x+w,yy,color=(.75,.78,.74),width=.8)
        pg.rect(x,yy+30,29,25,base.flat(m08.DIV_NODATA),(.57,.61,.57),.5)
        y2=pg.wrap(x+47,yy+52,info['extra'],w-47,25,36,'AtlasSans',INK)
        pg.wrap(x,y2+40,info['note'],w,25,36)
        return
    if theme=='hypsometry':
        pg.text(x,y+38,'METROS ACIMA DO NÍVEL DO MAR',20,'AtlasSans',MUTED,tracking=.6)
        ticks=list(reversed(m08.Z_BREAKS))
        gradient(pg,x,y+86,40,660,ticks,True)
        for i,z in enumerate(ticks):
            yy=y+86+660*i/(len(ticks)-1);pg.line(x+44,yy,x+55,yy,width=.8);pg.text(x+74,yy+10,f'{z:,}'.replace(',','.'),31)
        pg.wrap(x,y+822,'Cotas em metros; intervalos cromáticos não lineares.',w,25,36)
        pg.wrap(x,y+927,'A luminosidade varia com o sombreado. As cores-base representam a altitude.',w,25,36)
    else:
        items,other=discrete(theme)
        if theme=='geology':items=items+[('Sem classe litológica',base.flat(m08.NODATA),'')]
        step=48 if theme=='soil_orders' else 54
        for i,(label,color,symbol) in enumerate(items):chip(pg,x,y+75+i*step,label,color,29,25,31,w)
        if theme=='soil_orders':
            yy=y+75+len(items)*step+28;pg.text(x,yy,'OUTRAS FEIÇÕES',24,'AtlasSemi',MUTED,tracking=.8)
            for i,(label,color,symbol) in enumerate(other):chip(pg,x,yy+30+i*43,label,color,26,23,27,w)
        else:pg.wrap(x,y+720,'Grupos de rochas, não idades geológicas. Cores-base moduladas pelo sombreado.',w,27,39)

def make_digital_single(theme):
    file=O/f'brazil_{theme}_screen.pdf';pg=Board(file,1920,1440);info=base.THEMES[theme]
    pg.c.setTitle(f'Brasil | {info["title"]} | Digital');pg.c.setSubject('Versão para tela, 1920 × 1440; textos e legendas ampliados')
    pg.text(64,48,'BRASIL',24,'AtlasSemi',tracking=5)
    pg.text(64,135,info['title'],84,'AtlasSerif')
    # subtitulo depois do titulo (os da diversidade sao longos e cobriam o x
    # fixo de 500 do layout original; log 25)
    sx=max(500,64+pdfmetrics.stringWidth(info['title'],'AtlasSerif',84)+40)
    pg.text(sx,132,info['subtitle'],28,'AtlasLight',MUTED,maxw=1760-sx)
    pg.text(1856,69,info['index'],42,'AtlasLight',base.rgbhex(info['accent']),'right');pg.text(1856,105,f'/ {base.N_SERIES}',20,'AtlasSans',MUTED,'right')
    pg.line(64,172,1856,172,width=1)
    box=map_image(pg,theme,44,210,1160,1112);north(pg,theme,box,1140,274,True)
    scale(pg,104,1252,box,True,1000)
    pg.line(1225,228,1225,1280,color=(.75,.78,.74),width=.8)
    digital_legend(pg,theme,1270,260,586)
    pg.line(64,1354,1856,1354,width=1)
    pg.text(64,1391,info['screen'],23,'AtlasSans',MUTED,maxw=1250)
    pg.text(1856,1391,'SIRGAS 2000 / POLICÔNICA · EPSG:5880',20,'AtlasSans',MUTED,'right')
    pg.text(64,1424,'Relevo com exagero em duas escalas (128× / 8×). Dados nativos de 30 m.',20,'AtlasSans',MUTED)
    pg.text(1856,1424,f'Elaboração: {base.AUTHOR} · ESALQ/USP · {base.YEAR}',20,'AtlasSans',MUTED,'right')
    pg.close();BOXES[f'digital_{theme}']=pg.boxes;print('tela pronta',theme,flush=True)

def joint_digital_legend(pg,theme,x,y,w):
    info=base.THEMES[theme];pg.line(x,y-28,x+w,y-28,width=1)
    pg.text(x,y,info['legend'],31,'AtlasSemi',base.rgbhex(info['accent']),tracking=.9)
    if theme=='hypsometry':
        ticks=[0,100,300,500,900,1600,3000];gradient(pg,x,y+48,w,35,ticks)
        for i,z in enumerate(ticks):
            xx=x+w*i/6;pg.line(xx,y+89,xx,y+100,width=.8);pg.text(xx,y+141,f'{z:,}'.replace(',','.'),32,'AtlasSans',INK,'center')
        pg.text(x,y+204,'Altitude (m) · intervalos não lineares.',28,'AtlasSans',MUTED)
        pg.wrap(x,y+295,'Cores representam a altitude. O sombreado evidencia as formas do terreno.',w,33,46,'AtlasLight')
    else:
        items,other=discrete(theme)
        if theme=='geology':items=items+[('Sem classe litológica',base.flat(m08.NODATA),'')]
        nr=7 if theme=='soil_orders' else 5;cw=w/2
        for i,(label,color,symbol) in enumerate(items):chip(pg,x+(i//nr)*cw,y+48+(i%nr)*43,label,color,27,24,31,cw)
        if theme=='soil_orders':
            yy=y+371;pg.text(x,yy,'OUTRAS FEIÇÕES',24,'AtlasSemi',MUTED,tracking=.6)
            for i,(label,color,symbol) in enumerate(other):chip(pg,x+(i%2)*cw,yy+25+(i//2)*40,label,color,24,22,26,cw)
        else:pg.wrap(x,y+341,'Grupos litológicos, não idades geológicas. Cores-base moduladas pelo sombreado.',w,30,43,'AtlasLight')

def make_digital_joint():
    file=O/'brazil_three_maps_screen.pdf';pg=Board(file,3840,2160);pg.c.setTitle('Brasil | Relevo, geologia e solos | Digital')
    pg.c.setSubject('Versão conjunta para tela, 3840 × 2160; formato 16:9')
    pg.text(96,69,'BRASIL',35,'AtlasSemi',tracking=6)
    pg.text(96,185,'Relevo, geologia e solos',94,'AtlasSerif')
    pg.text(3744,83,'MESMO ENQUADRAMENTO E ESCALA',27,'AtlasSans',MUTED,'right',tracking=1)
    pg.text(3744,134,'SIRGAS 2000 / POLICÔNICA',28,'AtlasSans',MUTED,'right');pg.text(3744,185,'2026',33,'AtlasLight',MUTED,'right')
    pg.line(96,232,3744,232,width=1.3);boxes=[]
    for i,t in enumerate(JOINT):
        x=96+i*1248;w=1152;info=base.THEMES[t]
        pg.text(x,311,info['title'],57,'AtlasSerif');pg.text(x+w,308,info['index'],35,'AtlasLight',base.rgbhex(info['accent']),'right')
        box=map_image(pg,t,x,350,w,1152);boxes.append(box);north(pg,t,box,x+w-44,417,True)
        joint_digital_legend(pg,t,x,1550,w)
    pg.line(96,2057,3744,2057,width=1)
    pg.text(96,2103,'Altimetria: GEDTM30 v1.2 (Ho et al., 2025) · Geologia: SGB/CPRM, 1:250.000, nove classes de rocha (DPS/UFV) · Solos: IBGE/BDiA Pedologia, 1:250.000 (2023), SiBCS 6ª ed. (Santos et al., 2025).',25,'AtlasSans',MUTED,maxw=3120)
    pg.text(96,2145,f'Elaboração: {base.AUTHOR} ({base.AFFIL}), {base.YEAR} · SIRGAS 2000, projeção policônica (EPSG:5880) · Relevo com exagero em duas escalas (128× / 8×).',23,'AtlasSans',MUTED,maxw=3120)
    bw=1000000/boxes[0]['mpu'];scale(pg,3730-bw,2083,boxes[0],True,1000)
    pg.close();BOXES['digital_joint']=pg.boxes;print('tela conjunta pronta',flush=True)

# rasterizacao, HTML e conferencia (antes package_multiformat.py) ---------------------

def rasterize():
    import fitz
    for f in sorted(O.glob('*_screen.pdf')):
        doc=fitz.open(f);doc[0].get_pixmap(matrix=fitz.Matrix(1,1)).save(f.with_suffix('.png'));doc.close()
    base.preview(O/'brazil_three_maps_a0.pdf',O/'brazil_three_maps_a0_preview.jpg',2800)

def color(c):return '#'+''.join(f'{round(v*255):02x}' for v in c)
def html_legend(t):
    if t in base.DIVERSITY:
        rows=''.join(f'<li><i style="background:{color(c)}"></i>{html.escape(n)} <small>{pct} · {nu} unidades</small></li>' for n,c,pct,nu in base.diversity_rows(t,m09))
        inf=base.THEMES[t]
        return (f'<h3>{inf["legend"].capitalize()}</h3><ul>{rows}</ul><h4>Sem contagem</h4><ul><li><i style="background:{color(base.flat(m08.DIV_NODATA))}"></i>'
                f'{html.escape(inf["extra"])}</li></ul><p>{html.escape(inf["note"])}</p>')
    if t=='hypsometry':
        return '<h3>Altitude <small>m</small></h3><img class="ramp" src="assets/ramp_h_7.png" alt="Rampa de altitude"><div class="ticks"><span>0</span><span>100</span><span>300</span><span>500</span><span>900</span><span>1.600</span><span>3.000</span></div><p>Intervalos cromáticos não lineares. As cores-base representam a altitude; a luminosidade varia com o sombreado.</p>'
    items,other=discrete(t)
    if t=='geology':items+=[('Sem classe litológica',base.flat(m08.NODATA),'')]
    def rows(entries):return '<ul>'+''.join(f'<li><i style="background:{color(c)}"></i>{html.escape(n)}</li>' for n,c,_ in entries)+'</ul>'
    return '<h3>'+base.THEMES[t]['legend'].capitalize()+'</h3>'+rows(items)+('<h4>Outras feições</h4>'+rows(other) if other else '<p>Grupos litológicos, não idades geológicas.</p>')

CSS=""":root{--paper:#eeede9;--ink:#27302b;--muted:#59645c;--rule:#b9bfb7}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font:18px/1.5 'Segoe UI',sans-serif}main{max-width:1720px;margin:auto;padding:48px 4vw}h1,h2{font-family:Georgia,serif;font-weight:400;line-height:1.08}h1{font-size:clamp(50px,6vw,90px);margin:16px 0}h2{font-size:60px;margin:8px 0}h3{font-size:20px;letter-spacing:.04em;margin:0 0 26px;text-transform:uppercase}h4{font-size:17px;letter-spacing:.04em;margin:24px 0 12px;text-transform:uppercase}p{color:var(--muted)}.kicker{text-transform:uppercase;letter-spacing:.22em;font-size:15px}nav,.links{display:flex;gap:12px;flex-wrap:wrap;margin:28px 0}a,button{color:var(--ink);border:1px solid var(--rule);padding:10px 17px;text-decoration:none;border-radius:2px;background:transparent;font:inherit;cursor:pointer}a:hover,button:hover,button.active{background:var(--ink);color:var(--paper)}.plate{border-top:1px solid var(--rule);padding:30px 0 38px;margin:34px 0}.plate header p{margin:12px 0 28px}.index{float:right;font-size:30px;font-weight:300;color:#65766b}.body{display:grid;grid-template-columns:minmax(0,1.9fr) minmax(320px,1fr);gap:40px;align-items:start}.map img{display:block;width:100%;height:auto}.map{min-width:0}aside{border-left:1px solid var(--rule);padding:26px 0 0 32px}ul{list-style:none;padding:0;margin:0;display:grid;gap:12px}li{display:flex;gap:14px;align-items:center;font-size:21px;line-height:1.3}li i{display:inline-block;flex:0 0 23px;height:23px;border:1px solid #a7ada4}aside p{font-size:17px;margin-top:28px}.ramp{width:100%;height:24px;display:block}.ticks{display:flex;justify-content:space-between;font-size:14px;margin-top:9px}.plate footer{font-size:16px;border-top:1px solid var(--rule);padding-top:18px;margin-top:24px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}.plate footer p{flex:1 1 100%;margin:0 0 8px}.joint{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:36px}.joint .body{display:block}.joint aside{border:0;border-top:1px solid var(--rule);padding:28px 0 0}.joint h2{font-size:40px}.joint li{font-size:18px}.joint .plate header p{min-height:54px;font-size:17px}.joint .plate footer{display:block}.joint .plate footer a{display:inline-block;margin:6px 4px 6px 0;font-size:14px}.joint .plate footer p{min-height:80px}.preview{display:block;width:100%;height:auto}.section{border-top:1px solid var(--rule);padding-top:32px;margin-top:45px}.note{font-size:16px;max-width:1000px}small{font-size:.75em}.end{border-top:1px solid var(--rule);margin-top:40px;padding-top:25px;font-size:15px}
@media(max-width:1100px){.joint{grid-template-columns:1fr}.joint .body{display:grid}.joint .plate header p,.joint .plate footer p{min-height:0}.joint h2{font-size:60px}.joint li{font-size:21px}.joint aside{border-top:0;border-left:1px solid var(--rule);padding:26px 0 0 32px}}@media(max-width:760px){main{padding:28px 20px}.body,.joint .body{grid-template-columns:1fr;gap:12px}aside,.joint aside{border-left:0;border-top:1px solid var(--rule);padding:25px 0 0}li,.joint li{font-size:20px}h2,.joint h2{font-size:48px}.plate{margin:22px 0}nav a{flex:1;text-align:center}button{font-size:16px}.joint{gap:0}.ticks{font-size:12px}}"""

def write_html():
    cards=[]
    for t in THEMES:
        inf=base.THEMES[t]
        cards.append(f'''<article id="{t}" class="plate"><header><span class="index">{inf['index']}</span><h2>{inf['title']}</h2><p>{inf['subtitle']}</p></header><div class="body"><div class="map"><img src="assets/map_{t}_digital.png" alt="Mapa do Brasil: {inf['title'].lower()} na versão equilibrada"></div><aside>{html_legend(t)}</aside></div><footer><p>{html.escape(' '.join(inf['sources']))}</p><a download href="brazil_{t}_screen.png">PNG · 1920 × 1440</a><a href="brazil_{t}_screen.pdf">PDF digital</a></footer></article>''')
    page=('<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Brasil — relevo, geologia, solos e diversidade</title><style>'+CSS+'</style><main><div class="kicker">Série cartográfica · versão equilibrada</div><h1>Brasil</h1><p>Relevo, geologia, solos e diversidade — uma série, cinco leituras do território.</p><nav><a href="#hypsometry">Relevo</a><a href="#geology">Geologia</a><a href="#soil_orders">Solos</a><a href="#soil_diversity">Diversidade pedológica</a><a href="#lithology_diversity">Diversidade litológica</a><a href="#conjunto">Pranchas conjuntas</a></nav><div class="links"><button id="single" class="active" onclick="view(false)">Leitura individual</button><button id="joint" onclick="view(true)">Comparar os mapas</button></div><p class="note">As legendas desta página são texto e se reorganizam conforme a largura da tela. Para norte, escala gráfica e composição cartográfica completa, use as pranchas PNG ou PDF abaixo.</p><section id="plates">'
          +''.join(cards)+
          '</section><section class="section" id="conjunto"><div class="kicker">Composições conjuntas</div><h2>Três mapas, lado a lado</h2><p>O mesmo enquadramento e a mesma escala em toda a série.</p><div class="links"><a href="brazil_three_maps_screen.png" download>PNG digital · 3840 × 2160</a><a href="brazil_three_maps_screen.pdf">PDF digital conjunto</a><a href="brazil_three_maps_a0.pdf">A0 conjunto · 1189 × 841 mm</a></div><img class="preview" src="brazil_three_maps_screen.png" alt="Prancha digital conjunta com os três mapas e legendas"><h3 style="margin-top:36px">Prancha A0</h3><a style="padding:0;border:0;display:block" href="brazil_three_maps_a0.pdf"><img class="preview" src="brazil_three_maps_a0_preview.jpg" alt="Prévia da prancha A0 conjunta"></a></section><div class="end"><p>'+html.escape(base.CREDIT)+'</p><p>SIRGAS 2000 · Projeção Policônica · EPSG:5880. Produto equilibrado, com dados altimétricos nativos de 30 m. Exagero em duas escalas: 128× / 8×. Cores-base moduladas pelo sombreado.</p><p>As pranchas digitais usam escala gráfica; seu tamanho físico varia com a tela. Imprima a prancha A0 em 100%, sem ajustar à página, para conservar a escala física indicada.</p><a href="readme.md">Notas técnicas e reprodução</a></div></main><script>function view(j){document.getElementById(\'plates\').classList.toggle(\'joint\',j);document.getElementById(\'single\').classList.toggle(\'active\',!j);document.getElementById(\'joint\').classList.toggle(\'active\',j);document.getElementById(\'single\').setAttribute(\'aria-pressed\',!j);document.getElementById(\'joint\').setAttribute(\'aria-pressed\',j)}</script></html>')
    (O/'brazil_atlas.html').write_text(page,encoding='utf-8')

def verify():
    # tamanho da pagina, 1 pagina, todas as classes no texto do PDF, PNG no tamanho
    import fitz
    results={}
    for f in sorted(O.glob('*.pdf')):
        doc=fitz.open(f);p=doc[0];w,h=p.rect.width,p.rect.height
        expected=(1189*MM,841*MM) if f.name.endswith('_a0.pdf') else ((3840,2160) if 'three_maps' in f.name else (1920,1440))
        assert len(doc)==1 and abs(w-expected[0])<.02 and abs(h-expected[1])<.02,(f.name,w,h)
        text=p.get_text()
        if 'soil_orders' in f.name or 'three_maps' in f.name:
            for label,_,_ in sum((list(v) for v in discrete('soil_orders')),[]):assert label in text,(f.name,label)
        if 'geology' in f.name or 'three_maps' in f.name:
            for label,_,_ in discrete('geology')[0]:assert label in text,(f.name,label)
        for t in base.DIVERSITY:
            if t in f.name:
                for label,_,_,_ in base.diversity_rows(t,m09):assert label in text,(f.name,label)
        if f.name.endswith('_screen.pdf'):
            with Image.open(f.with_suffix('.png')) as im:assert im.size==expected,(f.name,im.size)
        results[f.name]={'pages':len(doc),'size_pt':[w,h],'labels_checked':True,'bytes':f.stat().st_size};doc.close()
    (O/'verification.json').write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
    return results

README='''# Brasil — série multiformato

Composição multiformato do atlas (10/11/2026, log 21). Os mapas equilibrados, suas cores, classes e relevo vêm de data/final/30m sem alteração.

## Arquivos

- brazil_three_maps_a0.pdf: A0 horizontal, 1189 × 841 mm; três mapas com enquadramento e escala iguais; imagens a aproximadamente 300 dpi no tamanho impresso, títulos e legendas vetoriais. Imprimir a 100%, sem ajustar à página.
- brazil_hypsometry_screen, brazil_geology_screen, brazil_soil_orders_screen, brazil_soil_diversity_screen e brazil_lithology_diversity_screen: PNG e PDF de 1920 × 1440, proporção 4:3.
- brazil_three_maps_screen: PNG e PDF de 3840 × 2160, proporção 16:9.
- brazil_atlas.html: consulta local, sem internet, com legendas em texto e visualização individual ou comparada. Manter a pasta assets ao lado do HTML.
- As cinco pranchas A0 verticais individuais (relevo, geologia, solos, diversidade pedológica e diversidade litológica) ficam em ../plates_a0 (script 10).

Os pontos dos PDFs digitais correspondem aos pixels de suas exportações em 72 dpi: são arquivos para tela. O texto cartográfico é vetorial nos PDFs.

## Autoria

Elaboração: Cássio Moquedace (Departamento de Ciência do Solo, ESALQ/USP), 2026.

## Fontes

- Relevo: GEDTM30 v1.2, 30 m (Ho et al., 2025, PeerJ 13:e19673, https://doi.org/10.7717/peerj.19673), renderizado no Blender 4.5 (Cycles), luz a noroeste (azimute 315°, elevação 45°), exagero vertical em duas escalas (128× nas formas amplas, 8× no detalhe).
- Geologia: Serviço Geológico do Brasil (SGB/CPRM), mapa litoestratigráfico, 1:250.000. Unidades agrupadas em nove classes de rocha no Departamento de Solos da UFV (Edgar Batista de Medeiros Júnior, Gabriel Palucci Rosa, Alex Pinheiro, Cássio Moquedace e Clara Baldi); nomenclatura segundo a IUGS (Le Maitre et al., 2002; Fettes & Desmons, 2007) e o Glossário Geológico do SGB (Winge et al., 2001). Paleta inspirada no Mapa Geológico do Brasil de Lamego (1960).
- Solos: IBGE, Banco de Dados e Informações Ambientais (BDiA), Pedologia, 1:250.000, versão 2023 (https://bdiaweb.ibge.gov.br). Classes harmonizadas até o 3º nível categórico e atualizadas para o Sistema Brasileiro de Classificação de Solos, 6ª edição (Santos et al., 2025, Embrapa).
- Diversidade pedológica: número de componentes (classe dominante, subdominantes e inclusões) de cada unidade de mapeamento do IBGE/BDiA Pedologia, 1:250.000 (2023); tipos de terreno sem contagem.
- Diversidade litológica: número de litologias descritas em cada unidade do mapa litoestratigráfico do SGB/CPRM, 1:250.000, na base harmonizada no Departamento de Solos da UFV.
- Sistema de referência SIRGAS 2000; projeção policônica (EPSG:5880).

Resolução nativa dos dados: 30 m. As pranchas usam a overview de 240 m dos produtos finais, reamostrada ao tamanho de saída. As amostras da legenda são as cores-base em áreas planas; o sombreado altera a luminosidade observada.

## Reprodução

scripts/10_atlas_plates.py (pranchas A0 verticais) e scripts/11_atlas_multiformat.py (este conjunto), no projeto brazil_shaded_relief_maps. Python com numpy, scipy, rasterio, Pillow, reportlab e PyMuPDF; fontes Georgia e Segoe UI. Cache dos mapas em data/intermediate/10_atlas/layout_assets (apagar se os rasters do 08 mudarem).
'''

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--zip',action='store_true');args=ap.parse_args()
    t=time.time();O.mkdir(parents=True,exist_ok=True)
    print(f"\n# 11 atlas multiformat {'-' * 52}\nsaida em {O}",flush=True)
    ensure_assets();make_print()
    for theme in THEMES:make_digital_single(theme)
    make_digital_joint();rasterize();write_html()
    (O/'layout_manifest.json').write_text(json.dumps(dict(source_project=str(PROJECT),native_m=30,print_page_mm=[1189,841],digital_single_px=[1920,1440],digital_joint_px=[3840,2160],sources=META,text_elements=BOXES,source_maps_unchanged=True,seconds=time.time()-t),ensure_ascii=False,indent=2),encoding='utf-8')
    (O/'readme.md').write_text(README,encoding='utf-8')
    res=verify()
    for k,v in res.items():print(f'  {k}: {v["size_pt"][0]:.0f} x {v["size_pt"][1]:.0f} pt, {v["bytes"]/1e6:.1f} MB, classes ok')
    if args.zip:
        with zipfile.ZipFile(O/'brazil_atlas_multiformat.zip','w',zipfile.ZIP_DEFLATED,compresslevel=5) as z:
            for f in O.rglob('*'):
                if f.is_file() and f.suffix!='.zip':z.write(f,f.relative_to(O))
    print(f'fim em {(time.time()-t)/60:.1f} min',flush=True)

if __name__=='__main__':main()
