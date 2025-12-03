# URL tvé Apps Script webové aplikace
$endpointUrl = "https://script.google.com/macros/s/AKfycbzoQNRRCsISGMU3NjWmfykQxXRcuUgumeBdF-F5MfbxjXlvSECOECV8tPpdIq3eDJfI/exec"

# ----- Sber HW informaci -----
$cs     = Get-CimInstance -ClassName Win32_ComputerSystem
$bios   = Get-CimInstance -ClassName Win32_BIOS
$prod   = Get-CimInstance -ClassName Win32_ComputerSystemProduct
$osInfo = Get-CimInstance -ClassName Win32_OperatingSystem

$user       = $env:USERNAME
$deviceName = $env:COMPUTERNAME
$os         = $osInfo.Caption

$manufacturer = $cs.Manufacturer
$model        = $cs.Model

$serial = $bios.SerialNumber
if ([string]::IsNullOrWhiteSpace($serial)) {
    $serial = $prod.IdentifyingNumber
}

# ----- GUI okno pro jmeno / typ / poznamku -----

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$form = New-Object System.Windows.Forms.Form
$form.Text = "Inventura notebooku Media:list"
$form.Size = New-Object System.Drawing.Size(430, 330)
$form.StartPosition = "CenterScreen"

# Label s informaci o zarizeni
$lblDevice = New-Object System.Windows.Forms.Label
$lblDevice.Text = "Zarizeni: $manufacturer $model (SN: $serial)"
$lblDevice.AutoSize = $true
$lblDevice.Location = New-Object System.Drawing.Point(10, 10)
$form.Controls.Add($lblDevice)

# Jmeno a prijmeni
$lblName = New-Object System.Windows.Forms.Label
$lblName.Text = "Jmeno a prijmeni:"
$lblName.AutoSize = $true
$lblName.Location = New-Object System.Drawing.Point(10, 40)
$form.Controls.Add($lblName)

$txtName = New-Object System.Windows.Forms.TextBox
$txtName.Size = New-Object System.Drawing.Size(380, 20)
$txtName.Location = New-Object System.Drawing.Point(10, 60)
$form.Controls.Add($txtName)

# Typ zarizeni (firemni / osobni)
$lblType = New-Object System.Windows.Forms.Label
$lblType.Text = "Typ zarizeni:"
$lblType.AutoSize = $true
$lblType.Location = New-Object System.Drawing.Point(10, 95)
$form.Controls.Add($lblType)

$rbFiremni = New-Object System.Windows.Forms.RadioButton
$rbFiremni.Text = "Firemni"
$rbFiremni.Location = New-Object System.Drawing.Point(20, 115)
$rbFiremni.Checked = $true
$form.Controls.Add($rbFiremni)

$rbOsobni = New-Object System.Windows.Forms.RadioButton
$rbOsobni.Text = "Osobni"
$rbOsobni.Location = New-Object System.Drawing.Point(120, 115)
$form.Controls.Add($rbOsobni)

# Poznamka
$lblNotes = New-Object System.Windows.Forms.Label
$lblNotes.Text = "Poznamka (napr. rozbite tlacitko, nepouzivany atd.):"
$lblNotes.AutoSize = $true
$lblNotes.Location = New-Object System.Drawing.Point(10, 145)
$form.Controls.Add($lblNotes)

$txtNotes = New-Object System.Windows.Forms.TextBox
$txtNotes.Multiline = $true
$txtNotes.ScrollBars = "Vertical"
$txtNotes.Size = New-Object System.Drawing.Size(380, 90)
$txtNotes.Location = New-Object System.Drawing.Point(10, 165)
$form.Controls.Add($txtNotes)

# Tlacitka OK / Zrusit
$btnOK = New-Object System.Windows.Forms.Button
$btnOK.Text = "Odeslat"
$btnOK.Size = New-Object System.Drawing.Size(80, 30)
$btnOK.Location = New-Object System.Drawing.Point(230, 265)
$btnOK.Add_Click({
    $form.Tag = "OK"
    $form.Close()
})
$form.Controls.Add($btnOK)

$btnCancel = New-Object System.Windows.Forms.Button
$btnCancel.Text = "Zrusit"
$btnCancel.Size = New-Object System.Drawing.Size(80, 30)
$btnCancel.Location = New-Object System.Drawing.Point(320, 265)
$btnCancel.Add_Click({
    $form.Tag = "CANCEL"
    $form.Close()
})
$form.Controls.Add($btnCancel)

# Zobrazit formular
[void]$form.ShowDialog()

if ($form.Tag -ne "OK") {
    Write-Host "Inventura byla zrusena uzivatelem."
    return
}

$fullName = $txtName.Text.Trim()
$ownerType = if ($rbOsobni.Checked) { "osobni" } else { "firemni" }
$notes = $txtNotes.Text.Trim()

# ----- JSON payload -----

$body = @{
    user         = $user
    fullName     = $fullName
    ownerType    = $ownerType
    deviceName   = $deviceName
    os           = $os
    manufacturer = $manufacturer
    model        = $model
    serialNumber = $serial
    notes        = $notes
} | ConvertTo-Json -Depth 4

try {
    $response = Invoke-RestMethod -Uri $endpointUrl -Method Post -Body $body -ContentType "application/json"
    Write-Host "Hotovo - data odeslana." -ForegroundColor Green
}
catch {
    Write-Host "Chyba pri odesilani dat do Google Sheets." -ForegroundColor Red
    Write-Host $_.Exception.Message
}