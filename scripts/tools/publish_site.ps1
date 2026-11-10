# brazil_shaded_relief_maps - publica o site e os PDFs A0 originais no GitHub ---
#
# PowerShell, depois do 12 (log 25):
#   powershell -ExecutionPolicy Bypass -File "<projeto>\scripts\tools\publish_site.ps1"
#   ... -Tag v1.1    nova versao dos PDFs (gere o 12 com --release-tag v1.1)
#   ... -SiteOnly    so a pagina, sem mexer na release
#
# 1. data/final/site -> ramo gh-pages de moquedace/brazil_shaded_relief_maps,
#    num commit unico refeito a cada publicacao (push forcado), para o
#    historico nao acumular as versoes dos tiles do zoom; o git do site fica
#    em data/intermediate/12_site/gh_pages.git e so o que mudou e enviado
# 2. PDFs A0 originais (5 pranchas do 10 + A0 conjunto do 11; 60-120 MB, acima
#    do limite de 100 MB do git) como arquivos da release <Tag>: cria a
#    release nova; tags publicadas nao sao sobrescritas
# 3. GitHub Pages servindo o gh-pages (so na primeira vez)
# precisa do git e do gh logados na conta moquedace. Sem acentos neste
# arquivo: o PowerShell 5.1 le .ps1 sem BOM como ANSI

param([string]$Tag = "v1.0", [switch]$SiteOnly)
$ErrorActionPreference = "Continue"
$proj = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$site = Join-Path $proj "data\final\site"
$repo = "moquedace/brazil_shaded_relief_maps"

function Check($what) {
    if ($LASTEXITCODE -ne 0) { Write-Host "falhou: $what (codigo $LASTEXITCODE)"; exit 1 }
}

if (-not (Test-Path (Join-Path $site "index.html"))) { Write-Host "falta o site: rode o 12 antes"; exit 1 }

if ($Tag -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') { throw "Tag invalida" }
$html = Get-Content (Join-Path $site "index.html") -Raw
if (-not $SiteOnly -and -not $html.Contains("/releases/download/$Tag/")) {
    throw "Gere o site com --release-tag $Tag antes de publicar."
}
# 2. release com os PDFs originais ------------------------------------------
if (-not $SiteOnly) {
    $files = @(Get-ChildItem (Join-Path $proj "data\final\atlas\plates_a0") -Filter "brazil_*_a0.pdf" | ForEach-Object { $_.FullName })
    $files += (Join-Path $proj "data\final\atlas\multiformat\brazil_three_maps_a0.pdf")
    Write-Host ("release " + $Tag + ": " + $files.Count + " PDFs")
    gh release view $Tag -R $repo 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { throw "A release $Tag ja existe. Use -SiteOnly ou uma tag nova." }
    $notes = "Pranchas A0 originais para impressao em grafica. Site: https://moquedace.github.io/brazil_shaded_relief_maps/"
    gh release create $Tag @files -R $repo --title "Serie Brasil $Tag" --notes $notes; Check "gh release create"
}

# 1. site no ramo gh-pages ---------------------------------------------------
# repositorio git so do site, guardado entre publicacoes (data/ fica fora do
# git do projeto): o push manda so os arquivos que mudaram. Cada publicacao
# e um commit novo sem pai (commit-tree) com push forcado, para o historico
# do gh-pages nao acumular versoes do zoom. Antes (10/11/2026) o repositorio
# era temporario e cada correcao reenviava os 0,8 GB do site
$gitdir = Join-Path $proj "data\intermediate\12_site\gh_pages.git"
$g = @("--git-dir=$gitdir", "--work-tree=$site")
if (-not (Test-Path $gitdir)) {
    git @g init -q -b gh-pages; Check "git init"
    git @g config core.autocrlf false
    git @g remote add origin "https://github.com/$repo.git"; Check "git remote"
}
git @g add -A; Check "git add"
$tree = git @g write-tree; Check "git write-tree"
$commit = git @g commit-tree $tree -m "site: serie Brasil $(Get-Date -Format yyyy-MM-dd)"; Check "git commit-tree"
Write-Host "enviando o site para gh-pages ($commit) ..."
git @g push -f origin "${commit}:refs/heads/gh-pages"; Check "git push"
git @g update-ref refs/heads/gh-pages $commit

# 3. GitHub Pages ------------------------------------------------------------
cmd /c "gh api repos/$repo/pages >nul 2>&1"
if ($LASTEXITCODE -ne 0) {
    gh api -X POST "repos/$repo/pages" -f "source[branch]=gh-pages" -f "source[path]=/"; Check "ativar o Pages"
}
Write-Host "pronto: https://moquedace.github.io/brazil_shaded_relief_maps/ (o GitHub leva alguns minutos para publicar)"
