# check_04_render.ps1 ------------------------------------------------------
# estado do render completo do 04 ou do 07 (Blender), so leitura: conta os PNG
# do estilo, confere se cada um tem world file e termina no bloco IEND (PNG
# inteiro), ve se o Blender do --mode full ainda esta vivo e ha quanto tempo
# saiu o ultimo bloco. Escrito em 09/11/2026 para vigiar a madrugada do E8;
# -Step 07 (09/11/2026, log 16) vigia o render hibrido do 07 (outra pasta,
# outro processo e o render_log.csv dentro da pasta do estilo).
#
# uso (PowerShell):
#   powershell -NoProfile -ExecutionPolicy Bypass -File <este arquivo> [-Step 04|07] [-Style ...] [-Expected 183]
#
# status na primeira linha:
#   OK            rodando normal
#   TRAVADO       Blender vivo, mas nenhum bloco novo ha mais de StallMin min
#   PAROU         Blender morto antes de completar os blocos
#   ARQUIVO_RUIM  PNG truncado/vazio ou sem .pgw (o 04 pularia esse bloco)
#   TERMINOU      todos os blocos presentes e inteiros, Blender encerrado

param(
  [ValidateSet("04", "07")][string]$Step = "04",
  [string]$Style = "",
  [int]$Expected = 183,
  [int]$StallMin = 20
)

$inter = "D:\usuario_armazenamento\cassio\projects\brazil_shaded_relief_maps\data\intermediate"
if ($Step -eq "04") {
  $root = Join-Path $inter "04_relief_renders"
  if (-not $Style) { $Style = "e8_az315_el45_p100" }
  $proc_pattern = "*04_render_relief.py*--mode full*"
  $log_file = Join-Path $root "render_log.csv"
} else {
  $root = Join-Path $inter "07_hybrid_renders"
  if (-not $Style) { $Style = "h128_8_s2000_az315_el45_ang90_ctx5000_fd1" }
  $proc_pattern = "*07_render_hybrid.py*--mode full*"
  $log_file = Join-Path (Join-Path $root $Style) "render_log.csv"
}
$dir  = Join-Path $root $Style
$now  = Get-Date

# arquivos ---------------------------------------------------------------------
$png  = @(Get-ChildItem $dir -Filter "relief_*.png" -ErrorAction SilentlyContinue)
$npgw = @(Get-ChildItem $dir -Filter "relief_*.pgw" -ErrorAction SilentlyContinue).Count
$last = $png | Sort-Object LastWriteTime | Select-Object -Last 1
$idle = if ($last) { ($now - $last.LastWriteTime).TotalMinutes } else { 9999 }

# PNG inteiro termina em IEND + CRC (AE 42 60 82); arquivo mexido ha menos de
# 2 min pode estar sendo gravado agora e fica de fora da conferencia
$bad = @()
foreach ($f in $png) {
  if (($now - $f.LastWriteTime).TotalMinutes -lt 2) { continue }
  $why = $null
  if ($f.Length -lt 1MB) {
    $why = "tamanho $($f.Length) bytes"
  } else {
    $fs = [System.IO.File]::OpenRead($f.FullName)
    try {
      [void]$fs.Seek(-8, [System.IO.SeekOrigin]::End)
      $buf = New-Object byte[] 8
      [void]$fs.Read($buf, 0, 8)
    } finally { $fs.Close() }
    $tail = [System.Text.Encoding]::ASCII.GetString($buf, 0, 4)
    if ($tail -ne "IEND") { $why = "sem IEND no fim (truncado)" }
  }
  if (-not $why -and -not (Test-Path ($f.FullName -replace '\.png$', '.pgw'))) {
    $why = "sem .pgw"
  }
  if ($why) { $bad += "$($f.Name): $why" }
}

# processo ---------------------------------------------------------------------
$proc = @(Get-CimInstance Win32_Process -Filter "Name='blender.exe'" |
  Where-Object { $_.CommandLine -like $proc_pattern })

# ritmo ------------------------------------------------------------------------
$mean_s = $null
if (Test-Path $log_file) {
  $log = Import-Csv $log_file -Delimiter ";" | Where-Object { $_.file -like "*\$Style\*" }
  if ($log) {
    $mean_s = ($log | ForEach-Object { [double]($_.seconds -replace ",", ".") } |
      Measure-Object -Average).Average
  }
}
$left = $Expected - $png.Count
$eta = if ($mean_s -and $left -gt 0) { $now.AddSeconds($left * ($mean_s + 10)) } else { $null }

# status -----------------------------------------------------------------------
$status =
  if ($bad.Count -gt 0) { "ARQUIVO_RUIM" }
  elseif ($png.Count -ge $Expected -and $proc.Count -eq 0) { "TERMINOU" }
  elseif ($proc.Count -eq 0) { "PAROU" }
  elseif ($idle -gt $StallMin) { "TRAVADO" }
  else { "OK" }

$d = Get-PSDrive D
"status: $status"
"hora: $($now.ToString('dd/MM/yyyy HH:mm'))"
"blocos: $($png.Count) de $Expected (pgw $npgw) | ultimo $(if ($last) { $last.BaseName -replace 'relief_', '' }) ha $([math]::Round($idle, 1)) min"
if ($proc.Count -gt 0) {
  $p = Get-Process -Id $proc[0].ProcessId -ErrorAction SilentlyContinue
  "blender: pid $($proc[0].ProcessId), $([math]::Round($p.WorkingSet64 / 1GB, 1)) GB de RAM, desde $($p.StartTime.ToString('dd/MM HH:mm'))"
} else {
  "blender: nenhum --mode full rodando"
}
if ($mean_s) { "render medio: $([math]::Round($mean_s)) s | faltam $left$(if ($eta) { " -> termina ~$($eta.ToString('dd/MM HH:mm'))" })" }
"disco D: $([math]::Round($d.Free / 1GB)) GB livres"
if ($bad.Count -gt 0) { "problemas:"; $bad | ForEach-Object { "  $_" } } else { "problemas: nenhum" }
