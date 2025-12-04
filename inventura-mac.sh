{\rtf1\ansi\ansicpg1252\cocoartf2822
\cocoatextscaling0\cocoaplatform0{\fonttbl\f0\fswiss\fcharset0 Helvetica;}
{\colortbl;\red255\green255\blue255;}
{\*\expandedcolortbl;;}
\paperw11900\paperh16840\margl1440\margr1440\vieww11520\viewh8400\viewkind0
\pard\tx720\tx1440\tx2160\tx2880\tx3600\tx4320\tx5040\tx5760\tx6480\tx7200\tx7920\tx8640\pardirnatural\partightenfactor0

\f0\fs24 \cf0 #!/bin/bash\
\
# URL tve Google Apps Script webove aplikace\
ENDPOINT_URL="https://script.google.com/macros/s/AKfycbwZyogSAjYa8bH3l9sLKN5WfygyK7GjOnTcTHwoIZBDH-xJ37YdHsFGew5KSnkm7nKl/exec"\
\
# ---- Sber informaci o zarizeni ----\
\
USER_LOGIN="$USER"\
DEVICE_NAME="$(scutil --get ComputerName 2>/dev/null || hostname)"\
OS_NAME="$(sw_vers -productName) $(sw_vers -productVersion)"\
MANUFACTURER="Apple"\
\
MODEL="$(sysctl -n hw.model 2>/dev/null)"\
\
SERIAL="$(system_profiler SPHardwareDataType 2>/dev/null | awk -F': ' '/Serial Number/\{print $2; exit\}')"\
\
# ---- Dialogy pro uzivatele (osascript) ----\
\
FULLNAME="$(osascript <<'EOF'\
set dlg to display dialog "Zadej prosim sve jmeno a prijmeni:" default answer "" buttons \{"OK"\} default button 1\
text returned of dlg\
EOF\
)"\
\
# kdyby uzivatel klikl Cancel (v jinem dialogu), vracime se; tady je jen OK\
if [ -z "$FULLNAME" ]; then\
  osascript -e 'display alert "Inventura ukoncena" message "Jmeno a prijmeni musi byt vyplnene." as warning'\
  exit 1\
fi\
\
OWNER_CHOICE="$(osascript <<'EOF'\
set dlg to display dialog "Vyber typ zarizeni:" buttons \{"Firemni", "Osobni"\} default button "Firemni"\
button returned of dlg\
EOF\
)"\
\
if [ "$OWNER_CHOICE" = "Osobni" ]; then\
  OWNER_TYPE="osobni"\
else\
  OWNER_TYPE="firemni"\
fi\
\
NOTES="$(osascript <<'EOF'\
set dlg to display dialog "Poznamka (napr. rozbite tlacitko, nepouzivany atd.):" default answer "" buttons \{"OK"\} default button 1\
text returned of dlg\
EOF\
)"\
\
# ---- Lehke escapovani uvozovek, aby to nerozbilo JSON ----\
FULLNAME_ESC=$\{FULLNAME//\\"/\\'\}\
NOTES_ESC=$\{NOTES//\\"/\\'\}\
\
# ---- JSON payload ----\
\
read -r -d '' JSON <<EOF\
\{\
  "user": "$USER_LOGIN",\
  "fullName": "$FULLNAME_ESC",\
  "ownerType": "$OWNER_TYPE",\
  "deviceName": "$DEVICE_NAME",\
  "os": "$OS_NAME",\
  "manufacturer": "$MANUFACTURER",\
  "model": "$MODEL",\
  "serialNumber": "$SERIAL",\
  "notes": "$NOTES_ESC"\
\}\
EOF\
\
# ---- Odeslani na Google Apps Script ----\
\
RESPONSE=$(curl -s -X POST -H "Content-Type: application/json" -d "$JSON" "$ENDPOINT_URL")\
\
if echo "$RESPONSE" | grep -q "OK"; then\
  osascript -e 'display alert "Hotovo" message "Data byla uspesne odeslana. Dekuji." as informational'\
  exit 0\
else\
  osascript -e 'display alert "Chyba" message "Nepodarilo se odeslat data. Zkus to prosim znovu nebo kontaktuj IT." as warning'\
  exit 1\
fi}