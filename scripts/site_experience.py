"""Camada de apresentação do atlas; reutiliza mapas e legendas já gerados."""
import json
import re

THEMES = dict(hypsometry='Relevo', geology='Geologia', soil_orders='Solos',
              soil_diversity='Diversidade pedológica', lithology_diversity='Diversidade litológica')

CSS = '''
.site-head{display:flex;justify-content:space-between;align-items:center;gap:20px;border-bottom:1px solid var(--rule);padding-bottom:14px}.site-head nav{margin:0;gap:16px}.site-head a,.theme-strip a{border:0;padding:8px 0}.site-head strong{font-size:14px;letter-spacing:.13em}.site-head a:hover,.theme-strip a:hover{background:none;color:var(--ink);text-decoration:underline}
.hero{display:grid;grid-template-columns:1fr 1.17fr;gap:clamp(15px,4vw,72px);align-items:center;padding:26px 0}.hero h1{font-size:clamp(48px,5.7vw,90px);letter-spacing:-.035em;margin:14px 0 24px}.hero p{max-width:36ch}.hero img{display:block;width:100%;height:auto;max-height:700px;object-fit:contain}.primary{background:#31574b;color:white;border-color:#31574b}.hero-credit{font-size:14px;letter-spacing:.07em}.theme-strip{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;border-top:1px solid var(--rule);border-bottom:1px solid var(--rule);margin:0 0 48px}.theme-strip a{display:flex;align-items:center;gap:10px;padding:10px 4px;font-size:15px;line-height:1.25}.theme-strip img{width:clamp(32px,5vw,78px);height:auto}.theme-strip span{display:block;color:var(--muted);font-size:12px}.section h2,.plate h2{overflow-wrap:anywhere}.plate h2{font-size:clamp(36px,5vw,60px)}
.compare-controls{display:flex;gap:14px;flex-wrap:wrap;margin:20px 0}.compare-controls label{flex:1 1 225px;font-size:15px}.compare-controls select{display:block;width:100%;max-width:100%;background:var(--paper);border:1px solid var(--rule);color:var(--ink);font:inherit;padding:11px}.pair{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}.pair figure{margin:0}.pair img{display:block;width:100%;height:auto}.pair figcaption{font-size:18px;margin:10px 0}.pair details{font-size:16px}.pair summary,.viewer-legend summary{cursor:pointer;font-weight:600;padding:12px 0}.pair li,.viewer-legend li{font-size:16px}.pair-tabs{display:none}.diversity-note{font-size:16px;max-width:70ch}
#viewer{position:relative}.zoom-frame{position:relative}.zoom-fallback{display:block;width:100%;height:100%;object-fit:contain}.zoom-frame[data-ready=true] .zoom-fallback{display:none}.zoom-frame[data-ready=false] #viewer{display:none}.zoom-toolbar{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.zoom-toolbar button{font-size:15px}.viewer-legend{padding:0 18px;border:1px solid var(--rule);margin:14px 0}.viewer-legend .legend-body{padding:12px 0}.viewer-legend .ramp{max-width:540px}.viewer-legend .ticks{max-width:540px}#zoom-status{min-height:1.5em;font-size:15px}.themes button[aria-pressed=true],.pair-tabs button[aria-pressed=true]{background:#31574b;color:white}:focus-visible{outline:3px solid #517e71;outline-offset:3px}
@media(max-width:760px){.site-head{align-items:flex-start}.site-head nav{gap:7px 12px;justify-content:flex-end}.site-head a{flex:none;font-size:13px}.hero{grid-template-columns:1fr;gap:5px;padding:24px 0}.hero h1{font-size:clamp(38px,9vw,62px);margin:8px 0 14px}.hero .links{margin:17px 0}.hero img{max-height:55vh}.theme-strip{grid-template-columns:repeat(2,minmax(0,1fr));margin-bottom:25px;gap:3px 9px}.theme-strip img{width:42px}.theme-strip a{font-size:14px}.pair{display:block}.pair-tabs{display:flex;gap:8px;margin:12px 0}.pair figure[data-mobile-hidden=true]{display:none}.compare-controls{gap:9px}.compare-controls label{flex-basis:145px}.zoom-toolbar button,.themes button{padding:8px 12px}.viewer-legend{padding:0 12px}}
.zoom-frame[data-ready=false] #viewer{display:block;position:absolute;inset:0;visibility:hidden;pointer-events:none}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
'''

JS = r'''
const keys = Object.keys(atlasThemes);
const imagePath = t => 'assets/map_' + t + '.jpg';
const legend = t => document.querySelector('#' + t + ' aside').innerHTML;
const selects = [...document.querySelectorAll('.compare-controls select')];
const figures = [...document.querySelectorAll('.pair figure')];
const tabs = [...document.querySelectorAll('.pair-tabs button')];
let shown = 0;
function renderPair(){
  figures.forEach((f,i)=>{
    const t=selects[i].value;
    f.querySelector('img').src=imagePath(t);
    f.querySelector('img').alt=atlasThemes[t]+' do Brasil';
    f.querySelector('figcaption').textContent=atlasThemes[t];
    f.querySelector('.legend-body').innerHTML=legend(t);
    f.dataset.mobileHidden=String(i!==shown);
    tabs[i].textContent=atlasThemes[t];tabs[i].setAttribute('aria-pressed',String(i===shown));
  });
}
selects.forEach((s,i)=>s.addEventListener('change',()=>{shown=i;renderPair()}));
tabs.forEach((b,i)=>b.addEventListener('click',()=>{shown=i;renderPair()}));
const comparison=document.querySelector('#comparar');
let compared=false;
function prepareComparison(){if(!compared){compared=true;renderPair()}}
document.querySelectorAll('a[href="#comparar"]').forEach(a=>a.addEventListener('click',prepareComparison));
if(location.hash==='#comparar')prepareComparison();
if('IntersectionObserver' in window){const io=new IntersectionObserver(es=>{if(es.some(e=>e.isIntersecting)){prepareComparison();io.disconnect()}},{rootMargin:'250px'});io.observe(comparison)}else prepareComparison();

let viewer, currentItem, current='hypsometry', desired=current, sequence=0;
const status=document.getElementById('zoom-status');
const frame=document.querySelector('.zoom-frame');
const fallback=frame.querySelector('img');
const themeButtons=[...document.querySelectorAll('#zoomthemes button')];
function showTheme(t){
  current=t;
  themeButtons.forEach((b,i)=>{b.classList.remove('active');b.setAttribute('aria-pressed',String(keys[i]===t))});
  document.querySelector('.viewer-legend .legend-body').innerHTML=legend(t);
  document.querySelector('.viewer-legend summary').textContent='Legenda · '+atlasThemes[t];
  fallback.src=imagePath(t);fallback.alt=atlasThemes[t]+' do Brasil';
}
function openTheme(t){
  desired=t;
  if(!viewer){showTheme(t);return}
  const id=++sequence;
  if(currentItem && t===current){status.textContent='';return}
  status.textContent='Carregando '+atlasThemes[t]+'…';
  viewer.addTiledImage({tileSource:'zoom/'+t+'.dzi',opacity:0,
    success(e){
      if(id!==sequence){viewer.world.removeItem(e.item);return}
      const old=currentItem;
      if(old)e.item.setWidth(old.getBounds().width,true);
      e.item.setOpacity(1);currentItem=e.item;
      if(old)viewer.world.removeItem(old);
      else {frame.dataset.ready='true';viewer.viewport.goHome(true)}
      showTheme(t);status.textContent='';
    },error(){if(id===sequence)status.textContent='Não foi possível carregar o zoom deste tema. Tente novamente ou consulte a prancha.'}
  });
}
showTheme(current);
themeButtons.forEach((b,i)=>b.addEventListener('click',()=>{desired=keys[i];if(viewer)openTheme(desired);else {startZoom();if(!viewer)showTheme(desired)}}));
function startZoom(){
  if(viewer || !window.OpenSeadragon)return;
  OpenSeadragon.setImageFormatsSupported({webp:true});
  viewer=OpenSeadragon({id:'viewer',showNavigationControl:false,showNavigator:true,
    navigatorPosition:'BOTTOM_RIGHT',maxZoomPixelRatio:2,visibilityRatio:1,
    constrainDuringPan:true,gestureSettingsMouse:{clickToZoom:false,scrollToZoom:false}});
  openTheme(desired);
}
window.addEventListener('load',()=>{if(!window.OpenSeadragon)status.textContent='Zoom indisponível. A prévia e as pranchas continuam disponíveis.'});
if('IntersectionObserver' in window){const io=new IntersectionObserver(es=>{if(es.some(e=>e.isIntersecting)){startZoom();io.disconnect()}},{rootMargin:'250px'});io.observe(frame)}else startZoom();
document.querySelectorAll('.zoom-toolbar button').forEach(b=>b.addEventListener('click',()=>{
  startZoom();if(!currentItem)return;
  const action=b.dataset.zoom;
  if(action==='home')viewer.viewport.goHome();
  else if(action==='full')viewer.setFullScreen(!viewer.isFullScreen());
  else {viewer.viewport.zoomBy(action==='in'?1.5:1/1.5);viewer.viewport.applyConstraints()}
}));
'''

def enhance(page, release_tag='v1.0'):
    """Aplica a experiência pública ao HTML base do gerador 12."""
    strip=''.join(f'<a href="#{t}"><img src="assets/plate_{t}.jpg" width="72" height="102" loading="lazy" alt=""><div><span>{i:02d}</span>{name}</div></a>' for i,(t,name) in enumerate(THEMES.items(),1))
    hero=f'''<header class="site-head"><strong>ATLAS DO BRASIL</strong><nav aria-label="Navegação principal"><a href="#plates">Mapas</a><a href="#comparar">Comparar</a><a href="#fontes">Método</a><a href="#downloads">Downloads</a></nav></header>
<section class="hero"><div><div class="kicker">Série cartográfica · 2026</div><h1>Brasil em cinco leituras</h1><p>Relevo, geologia, solos e diversidade do território sobre o mesmo relevo sombreado.</p><div class="links"><a class="primary" href="#explorar">Explorar os mapas</a><a href="#downloads">Baixar pranchas</a></div><p class="hero-credit">CÁSSIO MOQUEDACE · ESALQ/USP</p></div><img src="assets/map_hypsometry.jpg" width="2320" height="2316" fetchpriority="high" alt="Mapa hipsométrico do Brasil sobre relevo sombreado"></section>
<nav class="theme-strip" aria-label="Cinco temas">{strip}</nav>'''
    options=''.join(f'<option value="{t}">{name}</option>' for t,name in THEMES.items())
    controls=''.join(f'<label>Mapa {i+1}<select>{options.replace(f"value=\"{t}\"",f"value=\"{t}\" selected")}</select></label>' for i,t in enumerate(('soil_diversity','lithology_diversity')))
    figures=''.join('<figure><img width="2320" height="2316" loading="lazy" alt=""><figcaption></figcaption><details><summary>Legenda</summary><div class="legend-body"></div></details></figure>' for _ in range(2))
    compare=f'''<section class="section" id="comparar"><div class="kicker">Comparação</div><h2>Um território, duas leituras</h2><p>Escolha dois temas no mesmo enquadramento. No celular, alterne entre eles sem sair da seção.</p><div class="compare-controls">{controls}</div><div class="pair-tabs" aria-label="Mapa exibido no celular"><button type="button">Mapa 1</button><button type="button">Mapa 2</button></div><div class="pair">{figures}</div><noscript><p>A comparação interativa precisa de JavaScript. Os cinco mapas e suas legendas estão abaixo.</p></noscript></section>'''
    zoom='''<div class="zoom-toolbar" aria-label="Controles do mapa"><button type="button" data-zoom="in" aria-label="Aproximar">+</button><button type="button" data-zoom="out" aria-label="Afastar">−</button><button type="button" data-zoom="home">Enquadrar Brasil</button><button type="button" data-zoom="full">Tela cheia</button></div><p id="zoom-status" role="status"></p><div class="zoom-frame" data-ready="false"><img class="zoom-fallback" src="assets/map_hypsometry.jpg" loading="lazy" alt="Prévia do relevo do Brasil"><div id="viewer" aria-label="Mapa com zoom"></div></div><details class="viewer-legend" open><summary>Legenda · Relevo</summary><div class="legend-body"></div></details><p class="diversity-note">Nas diversidades, a contagem descreve a unidade de mapeamento. As bases temáticas são de 1:250.000; os 30 m referem-se ao relevo. A pirâmide do visualizador usa imagens de até 120 m por pixel.</p>'''
    page,n=re.subn(r'<div class="kicker">Série cartográfica · Brasil · .*?(?=<section id="plates">)',lambda _:hero+compare+'\n',page,count=1,flags=re.S)
    if n!=1:raise ValueError('Estrutura de abertura inesperada')
    page=page.replace('</style></head>',CSS+'</style></head>',1)
    page=page.replace('<div id="viewer"></div></section>',zoom+'</section>',1)
    page=page.replace('Arraste para mover e use a roda do mouse ou o gesto de pinça para aproximar. O zoom vai até 120 m por pixel; os mapas foram compostos a 30 m, e as pranchas usam essa base reduzida ao tamanho de impressão.','Arraste para mover. Use + e − ou o gesto de pinça para aproximar e afastar. Troque o tema mantendo o enquadramento.')
    page=page.replace('/releases/latest/download/',f'/releases/download/{release_tag}/')
    page,n=re.subn(r'<script>\s*function view\(j\).*?</script>',lambda _:'<script>\nconst atlasThemes='+json.dumps(THEMES,ensure_ascii=False)+';\n'+JS+'</script>',page,count=1,flags=re.S)
    if n!=1 or page.count('id="viewer"')!=1:raise ValueError('Estrutura do visualizador inesperada')
    return page
