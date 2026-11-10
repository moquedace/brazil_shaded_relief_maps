# brazil_shaded_relief_maps - publica o site e os PDFs A0 originais no GitHub ---
#
# PowerShell, depois do 12 (log 25):
#   powershell -ExecutionPolicy Bypass -File "<projeto>\scripts\tools\publish_site.ps1"
#   ... -Tag v1.1    nova versao dos PDFs (a pagina aponta sempre para a ultima release)
#   ... -SiteOnly    so a pagina, sem mexer na release
#
# 1. data/final/site -> ramo gh-pages de moquedace/brazil_shaded_relief_maps,
#    num commit unico refeito a cada publicacao (push forcado), para o
#    historico nao acumular as versoes dos tiles do zoom
# 2. PDFs A0 originais (5 pranchas do 10 + A0 conjunto do 11; 60-120 MB, acima
#    do limite de 100 MB do git) como arquivos da release <Tag>: cria a
#    release ou substitui os arquivos (--clobber)
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

# 1. site no ramo gh-pages ---------------------------------------------------
$gitdir = Join-Path $env:TEMP "brazil_site_publish.git"
if (Test-Path $gitdir) { Remove-Item -Recurse -Force $gitdir }
$g = @("--git-dir=$gitdir", "--work-tree=$site")
git @g init -q -b gh-pages; Check "git init"
git @g config core.autocrlf false
git @g add -A; Check "git add"
git @g commit -q -m "site: serie Brasil $(Get-Date -Format yyyy-MM-dd)"; Check "git commit"
Write-Host "enviando o site para gh-pages ..."
git @g push -f "https://github.com/$repo.git" gh-pages; Check "git push"
Remove-Item -Recurse -Force $gitdir

# 2. release com os PDFs originais ------------------------------------------
if (-not $SiteOnly) {
    $files = @(Get-ChildItem (Join-Path $proj "data\final\atlas\plates_a0") -Filter "brazil_*_a0.pdf" | ForEach-Object { $_.FullName })
    $files += (Join-Path $proj "data\final\atlas\multiformat\brazil_three_maps_a0.pdf")
    Write-Host ("release " + $Tag + ": " + $files.Count + " PDFs")
    cmd /c "gh release view $Tag -R $repo >nul 2>&1"
    if ($LASTEXITCODE -eq 0) {
        gh release upload $Tag @files -R $repo --clobber; Check "gh release upload"
    } else {
        $notes = "Pranchas A0 originais (PDF, imagem sem recompressao) para impressao em grafica. Site: https://moquedace.github.io/brazil_shaded_relief_maps/"
        gh release create $Tag @files -R $repo --title "Serie Brasil $Tag" --notes $notes; Check "gh release create"
    }
}

# 3. GitHub Pages ------------------------------------------------------------
cmd /c "gh api repos/$repo/pages >nul 2>&1"
if ($LASTEXITCODE -ne 0) {
    gh api -X POST "repos/$repo/pages" -f "source[branch]=gh-pages" -f "source[path]=/"; Check "ativar o Pages"
}
Write-Host "pronto: https://moquedace.github.io/brazil_shaded_relief_maps/ (o GitHub leva alguns minutos para publicar)"
