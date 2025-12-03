# URL tvé Apps Script webové aplikace
$endpointUrl = "https://script.google.com/macros/s/AKfycbzoQNRRCsISGMU3NjWmfykQxXRcuUgumeBdF-F5MfbxjXlvSECOECV8tPpdIq3eDJfI/exec"

# Ziskani informaci z WMI
$cs   = Get-CimInstance -ClassName Win32_ComputerSystem
$bios = Get-CimInstance -ClassName Win32_BIOS
$prod = Get-CimInstance -ClassName Win32_ComputerSystemProduct
$osInfo = Get-CimInstance -ClassName Win32_OperatingSystem

$user       = $env:USERNAME
$deviceName = $env:COMPUTERNAME
$os         = $osInfo.Caption

$manufacturer = $cs.Manufacturer
$model        = $cs.Model

# Serial number: prefer BIOS, fallback na ComputerSystemProduct
$serial = $bios.SerialNumber
if ([string]::IsNullOrWhiteSpace($serial)) {
    $serial = $prod.IdentifyingNumber
}

# Jednoducha poznamka bez diakritiky
$notes = Read-Host "Poznamka (napr. 'firemni' / 'soukromy' - muzes nechat prazdne)"

# JSON payload
$body = @{
    user         = $user
    deviceName   = $deviceName
    os           = $os
    manufacturer = $manufacturer
    model        = $model
    serialNumber = $serial
    notes        = $notes
} | ConvertTo-Json -Depth 3

try {
    $response = Invoke-RestMethod -Uri $endpointUrl -Method Post -Body $body -ContentType "application/json"
    Write-Host "Hotovo - data odeslana." -ForegroundColor Green
    Write-Host "Zarizeni: $manufacturer $model (SN: $serial)"
}
catch {
    Write-Host "Chyba pri odesilani dat do Google Sheets." -ForegroundColor Red
    Write-Host $_.Exception.Message
}