# Adds "Shorts Clipper" (start + open dashboard) and "Stop Shorts Clipper" to the Start menu, so the app can be
# found with Windows search. Re-run this if you move the project folder.
$root = Split-Path -Parent $PSScriptRoot
$menu = [Environment]::GetFolderPath("Programs")
$shell = New-Object -ComObject WScript.Shell

foreach ($s in @(
    @{ Name = "Shorts Clipper"; Bat = "start.bat"; Info = "Start Shorts Clipper and open the dashboard" },
    @{ Name = "Stop Shorts Clipper"; Bat = "stop.bat"; Info = "Stop the Shorts Clipper backend and dashboard" }
)) {
    $lnk = $shell.CreateShortcut((Join-Path $menu ($s.Name + ".lnk")))
    $lnk.TargetPath = Join-Path $root $s.Bat
    $lnk.WorkingDirectory = $root
    $lnk.IconLocation = (Join-Path $PSScriptRoot "shorts-clipper.ico") + ",0"
    $lnk.Description = $s.Info
    $lnk.WindowStyle = 7  # minimized: the launcher console stays out of the way
    $lnk.Save()
    Write-Host "Created $($s.Name) in the Start menu"
}
