
KROKY – Netlify Drop (nejjednodušší varianta)

1) Na počítači vytvoř složku `signature/` a dovnitř dej:
   - Phone.png, Mail.png, LinkedIN.png, web.png, ml_logo.png
   - složku `profil/` a do ní profilové fotky (např. ML_1080x1080px_Kacena.png)

2) Do té stejné složky `signature/` ulož i přiložený soubor `index.html` (tenhle).
   – Díky němu po deploy uvidíš náhledy a ověříš, že cesty jsou správně.

3) Otevři https://app.netlify.com/drop a přetáhni celou složku `signature/` do okna.

4) Po nahrání dostaneš URL ve tvaru https://<něco>.netlify.app
   – Otevři https://<něco>.netlify.app/index.html a uvidíš všechny náhledy.
   – Přímé cesty pak budou např.:
     https://<něco>.netlify.app/profil/ML_1080x1080px_Kacena.png
     https://<něco>.netlify.app/Phone.png

5) Tuto URL (BASE_URL) pak použij v e‑mailovém podpisu:
   <img src="BASE_URL/profil/ML_1080x1080px_Kacena.png" ...>
   <img src="BASE_URL/Phone.png" ...>
