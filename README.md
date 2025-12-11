# Media:list Intranet - Kompletní struktura pro nahrání

## 📋 Obsah této složky

Tato složka obsahuje **kompletní čistou strukturu** pro nahrání na GitHub Pages (cdn.medialist.cz).

### Struktura souborů:

```
/
├── index.html                    # Hlavní rozcestník intranet
├── favicon.ico                   # Favicon
├── inventura-notebook3.ps1       # PowerShell script pro Windows inventuru
│
├── Assets (ikony a loga):
│   ├── ml_logo.png
│   ├── Phone.png
│   ├── Mail.png
│   ├── web.png
│   └── LinkedIN.png
│
├── inventura/                    # Inventura zařízení
│   ├── index.html               # OS rozcestník
│   ├── index_windows.html       # Windows inventura
│   └── mac.html                 # Mac inventura
│
├── podpis/                       # E-mailový podpis
│   └── index.html               # Generátor podpisů
│
└── profil/                       # Profilové fotky (42 ks)
    └── ML_1080x1080px_*.png
```

## 🚀 Jak nahrát na GitHub:

### Varianta 1: Smazat a nahrát vše (doporučeno)

```bash
# 1. Klonuj si repo lokálně (pokud ještě nemáš)
git clone https://github.com/pepino-nojgic/podpis.git
cd podpis

# 2. Smaž veškerý obsah
git rm -rf .
git add .
git commit -m "Clean repository"

# 3. Zkopíruj vše z cdn_upload složky
cp -r /cesta/k/cdn_upload/* .

# 4. Nahraj na GitHub
git add .
git commit -m "Upload clean intranet structure"
git push origin main
```

### Varianta 2: Přes GitHub web interface

1. Otevři https://github.com/pepino-nojgic/podpis
2. Smaž všechny soubory (klikni na každý soubor → 3 tečky → Delete)
3. Klikni "Add file" → "Upload files"
4. Přetáhni všechny soubory z `cdn_upload/` složky
5. Commit changes

## ⚙️ Co udělat PO nahrání:

### 1. Nastav Google Forms URL v PowerShell scriptu

Soubor: `inventura-notebook3.ps1`

```powershell
# Řádek 181 - změň na svůj Google Forms URL
$formUrl = "https://docs.google.com/forms/d/e/YOUR_FORM_ID/formResponse"

# Řádky 184-194 - nastav správné entry ID z tvého formuláře
'entry.123456789' = $userName       # Jméno a příjmení
'entry.234567890' = $manufacturer   # Výrobce
# ... atd.
```

**Jak zjistit entry ID:**
1. Otevři svůj Google Form v edit módu
2. Pravé tlačítko myši → Prozkoumat (Inspect)
3. V HTML kódu najdi `<input name="entry.xxxxxxxx">`
4. Zkopíruj čísla entry pro každé pole

### 2. Ověř funkčnost

- Hlavní stránka: https://cdn.medialist.cz/
- Inventura Windows: https://cdn.medialist.cz/inventura/index_windows.html
- Inventura Mac: https://cdn.medialist.cz/inventura/mac.html
- Generátor podpisů: https://cdn.medialist.cz/podpis/

### 3. Testuj

1. **Inventura Windows**: Zkopíruj PowerShell příkaz a spusť ho
2. **Inventura Mac**: Vyplň Google Form
3. **Generátor podpisů**: Vytvoř testovací podpis
4. **Fotky**: Zkontroluj, že se načítají z `/profil/`

## 🔒 Další kroky (Security)

- [ ] Nastav Cloudflare před cdn.medialist.cz
- [ ] Přidej Google OAuth autentizaci
- [ ] Nastav Access Control v Cloudflare

## 📝 Poznámky

- Všechny HTML soubory mají `noindex, nofollow` meta tagy
- Favicon a assety jsou referencovány přes `https://cdn.medialist.cz/`
- PowerShell script používá WinForms GUI
- Profilové fotky jsou ve formátu `ML_1080x1080px_[Prijmeni].png`

---

**Vytvořeno:** 2025-12-11
**Verze:** 1.0 (Clean structure)
