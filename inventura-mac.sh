#!/bin/bash

# URL tve Google Apps Script webove aplikace
ENDPOINT_URL="https://script.google.com/macros/s/AKfycbx7F64sEtLJuhtr88vkpcHUKcDz2kkk6w70CwbwtD-NiGP642liYrmnKo7ucLB6Nng/exec"

# ---- Sber informaci o zarizeni ----

USER_LOGIN="$USER"
DEVICE_NAME="$(scutil --get ComputerName 2>/dev/null || hostname)"
OS_NAME="$(sw_vers -productName) $(sw_vers -productVersion)"
MANUFACTURER="Apple"

MODEL="$(sysctl -n hw.model 2>/dev/null)"

SERIAL="$(system_profiler SPHardwareDataType 2>/dev/null | awk -F': ' '/Serial Number/{print $2; exit}')"

# ---- Dialogy pro uzivatele (osascript) ----

FULLNAME="$(osascript <<'EOF'
set dlg to display dialog "Zadej prosim sve jmeno a prijmeni:" default answer "" buttons {"OK"} default button 1
text returned of dlg
EOF
)"

# kdyby uzivatel klikl Cancel (v jinem dialogu), vracime se; tady je jen OK
if [ -z "$FULLNAME" ]; then
  osascript -e 'display alert "Inventura ukoncena" message "Jmeno a prijmeni musi byt vyplnene." as warning'
  exit 1
fi

OWNER_CHOICE="$(osascript <<'EOF'
set dlg to display dialog "Vyber typ zarizeni:" buttons {"Firemni", "Osobni"} default button "Firemni"
button returned of dlg
EOF
)"

if [ "$OWNER_CHOICE" = "Osobni" ]; then
  OWNER_TYPE="osobni"
else
  OWNER_TYPE="firemni"
fi

NOTES="$(osascript <<'EOF'
set dlg to display dialog "Poznamka (napr. rozbite tlacitko, nepouzivany atd.):" default answer "" buttons {"OK"} default button 1
text returned of dlg
EOF
)"

# ---- Lehke escapovani uvozovek, aby to nerozbilo JSON ----
FULLNAME_ESC=${FULLNAME//\"/\'}
NOTES_ESC=${NOTES//\"/\'}

# ---- JSON payload ----

read -r -d '' JSON <<EOF
{
  "user": "$USER_LOGIN",
  "fullName": "$FULLNAME_ESC",
  "ownerType": "$OWNER_TYPE",
  "deviceName": "$DEVICE_NAME",
  "os": "$OS_NAME",
  "manufacturer": "$MANUFACTURER",
  "model": "$MODEL",
  "serialNumber": "$SERIAL",
  "notes": "$NOTES_ESC"
}
EOF

# ---- Odeslani na Google Apps Script ----

RESPONSE=$(curl -s -X POST -H "Content-Type: application/json" -d "$JSON" "$ENDPOINT_URL")

if echo "$RESPONSE" | grep -q "OK"; then
  osascript -e 'display alert "Hotovo" message "Data byla uspesne odeslana. Dekuji." as informational'
  exit 0
else
  osascript -e 'display alert "Chyba" message "Nepodarilo se odeslat data. Zkus to prosim znovu nebo kontaktuj IT." as warning'
  exit 1
fi
