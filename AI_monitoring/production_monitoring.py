"""
AI Monitoring Automation
Automatický monitoring reputace klientů na AI platformách (ChatGPT, Perplexity, Gemini)
s automatickým zápisem do Google Sheets a uploadem screenshotů na Google Drive.
Sentiment analýza a komentáře pomocí Gemini API.

Browser: Selenium + undetected-chromedriver (obchází Cloudflare bot detekci)
"""

import json
import logging
import os
import re
import smtplib
import subprocess
import tempfile
import time
from datetime import datetime
from email.mime.text import MIMEText

from google import genai
import gspread
import undetected_chromedriver as uc
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from config import (
    CLIENTS,
    DAY_NAMES,
    HEADER_COLOR,
    KEYWORD_CONTEXT,
    PLATFORMS,
    SHEET_HEADERS,
    WORKSHEET_NAMES,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]

SENTIMENT_PROMPT = """Jsi analytik reputace značek. Analyzuj odpověď AI platformy o firmě/značce.

Platforma: {platform_name}
Dotaz: "{keyword}"
Odpověď platformy:
---
{response_text}
---

Vrať POUZE validní JSON (bez markdown, bez ```):
{{
  "sentiment": "Negativní" nebo "Neutrální / pozitivní",
  "komentar": "stručný český komentář max 150 znaků",
  "zdroje": "URL adresy z odpovědi oddělené čárkou, nebo prázdný řetězec"
}}

Pravidla pro sentiment:
- "Negativní" = AI platforma zobrazuje varování, negativní recenze, podvod, scam, riziko, problémy
- "Neutrální / pozitivní" = AI platforma zobrazuje neutrální nebo pozitivní informace

Pravidla pro komentář:
- Piš česky, stručně, jako zkušený analytik
- Shrň CO KONKRÉTNĚ AI říká o značce (ne že "odpověď je negativní")
- Příklady dobrých komentářů: "celkově hodnotí rizikově", "zmiňuje podvodné klony a varování", "ok, bez negativních zmínek", "odkazuje na negativní recenze na Trustpilot", "nerozpoznává značku, zaměňuje s jinou firmou"
- Pokud AI zmiňuje konkrétní zdroje nebo weby, uveď je v komentáři
- Pokud sentiment neutrální a není co dodat, napiš krátce "ok" nebo "bez negativních zmínek"

Pravidla pro zdroje (DŮLEŽITÉ):
- Extrahuj VŠECHNY URL adresy zmíněné v odpovědi (celé URL začínající http/https)
- Hledej i názvy webů bez URL (např. "Trustpilot", "Finparáda") a uveď je
- Pokud AI cituje nebo odkazuje na jakýkoliv zdroj, MUSÍ být v poli zdroje
- Odděl čárkou, max 5 zdrojů
"""


class ProductionAIMonitoring:

    def __init__(self, spreadsheet_id: str, credentials_file: str,
                 drive_folder_id: str = None, gemini_api_key: str = None,
                 smtp_config: dict = None):
        self.spreadsheet_id = spreadsheet_id
        self.drive_folder_id = drive_folder_id
        self.smtp_config = smtp_config

        creds = Credentials.from_service_account_file(credentials_file, scopes=SCOPES)

        # Google Sheets client
        self.gc = gspread.authorize(creds)
        self.spreadsheet = self.gc.open_by_key(spreadsheet_id)

        # Google Drive client
        self.drive_service = build('drive', 'v3', credentials=creds)

        # Gemini AI client
        self.gemini_client = None
        if gemini_api_key:
            self.gemini_client = genai.Client(api_key=gemini_api_key)
            logger.info("Gemini API initialized (gemini-2.0-flash, new SDK)")
        else:
            logger.warning("Gemini API key not provided - using basic keyword sentiment analysis")

        # Results tracking
        self.results = []

        logger.info("Google API clients initialized successfully")

    def _get_chrome_version(self) -> int:
        """Zjistí hlavní verzi nainstalovaného Chrome (Windows registry)."""
        try:
            import winreg
            key_paths = [
                r"SOFTWARE\Google\Chrome\BLBeacon",
                r"SOFTWARE\WOW6432Node\Google\Chrome\BLBeacon",
            ]
            for key_path in key_paths:
                try:
                    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
                    version, _ = winreg.QueryValueEx(key, "version")
                    winreg.CloseKey(key)
                    major = int(version.split(".")[0])
                    logger.info(f"Detekována verze Chrome z registry: {major} ({version})")
                    return major
                except Exception:
                    continue
        except ImportError:
            pass
        logger.warning("Nepodařilo se detekovat verzi Chrome, undetected_chromedriver zvolí sám")
        return None

    def _detect_login_wall(self, driver, platform_name: str) -> bool:
        """Vrací True pokud platforma zobrazuje přihlašovací stránku místo chatu."""
        try:
            url = driver.current_url
            if platform_name == 'Gemini' and 'accounts.google.com' in url:
                return True
            if platform_name == 'ChatGPT' and any(x in url for x in ['/auth/', 'auth0.com']):
                return True
            login_selectors = {
                'ChatGPT': ['input[name="username"]', 'button[data-testid="login-button"]'],
                'Perplexity': ['button[data-testid="sign-in"]', 'a[href*="/login"]'],
                'Gemini': ['input[type="email"]'],
            }
            for sel in login_selectors.get(platform_name, []):
                if driver.find_elements(By.CSS_SELECTOR, sel):
                    return True
        except Exception:
            pass
        return False

    def _sheets_retry(self, func, *args, max_retries=3, **kwargs):
        """Opakuje Google Sheets/Drive API volání při dočasné chybě."""
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if attempt < max_retries - 1:
                    wait = 5 * (2 ** attempt)  # 5s, 10s, 20s
                    logger.warning(f"API chyba (pokus {attempt + 1}/{max_retries}): {e}. Čekám {wait}s...")
                    time.sleep(wait)
                else:
                    raise

    def _create_driver(self, headless: bool = False) -> uc.Chrome:
        """Vytvoří nový undetected Chrome driver."""
        user_data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.browser_data')
        os.makedirs(user_data_dir, exist_ok=True)

        options = uc.ChromeOptions()
        options.add_argument(f'--user-data-dir={user_data_dir}')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--lang=cs-CZ')
        if headless:
            options.add_argument('--headless=new')

        chrome_version = self._get_chrome_version()
        driver = uc.Chrome(options=options, version_main=chrome_version)
        driver.set_page_load_timeout(60)
        logger.info("Chrome driver created (undetected-chromedriver)")
        return driver

    def _send_email(self, subject: str, body: str):
        """Posle email notifikaci pres SMTP."""
        if not self.smtp_config:
            logger.warning("SMTP not configured - skipping email")
            return

        try:
            recipients = [e.strip() for e in self.smtp_config['notify_email'].split(',')]
            msg = MIMEText(body, 'plain', 'utf-8')
            msg['Subject'] = subject
            msg['From'] = self.smtp_config['email']
            msg['To'] = ', '.join(recipients)

            with smtplib.SMTP(self.smtp_config['host'], self.smtp_config['port']) as server:
                server.starttls()
                server.login(self.smtp_config['email'], self.smtp_config['password'])
                server.sendmail(self.smtp_config['email'], recipients, msg.as_string())

            logger.info(f"Email sent: {subject}")
        except Exception as e:
            logger.error(f"Email failed: {e}")

    def should_run_today(self) -> bool:
        """Vrací True pokud je Pondělí (0) nebo Čtvrtek (3)."""
        today = datetime.now().weekday()
        should_run = today in (0, 3)
        day_name = DAY_NAMES.get(today, '?')
        logger.info(f"Dnes je {day_name} (weekday={today}), run={should_run}")
        return should_run

    def get_or_create_worksheet(self, client_name: str):
        """Najde původní záložku s emoji nebo vytvoří novou."""
        worksheet_name = WORKSHEET_NAMES.get(client_name, client_name)
        try:
            worksheet = self.spreadsheet.worksheet(worksheet_name)
            logger.info(f"Worksheet '{worksheet_name}' nalezen")
            return worksheet
        except gspread.WorksheetNotFound:
            pass

        try:
            worksheet = self.spreadsheet.worksheet(client_name)
            logger.info(f"Worksheet '{client_name}' nalezen (bez emoji)")
            return worksheet
        except gspread.WorksheetNotFound:
            pass

        worksheet = self.spreadsheet.add_worksheet(
            title=worksheet_name, rows=1000, cols=10
        )
        worksheet.update(values=[SHEET_HEADERS], range_name='A1:G1')
        worksheet.format('A1:G1', {
            'backgroundColor': HEADER_COLOR,
            'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
            'horizontalAlignment': 'CENTER',
        })
        logger.info(f"Worksheet '{worksheet_name}' vytvořen s hlavičkou")
        return worksheet

    def analyze_with_gemini(self, response_text: str, platform_name: str, keyword: str) -> dict:
        """Analyzuje odpověď AI platformy pomocí Gemini API."""
        if not self.gemini_client:
            return self._analyze_basic(response_text)

        try:
            trimmed_text = response_text[:4000] if response_text else '(prázdná odpověď)'

            prompt = SENTIMENT_PROMPT.format(
                platform_name=platform_name,
                keyword=keyword,
                response_text=trimmed_text,
            )

            response = self.gemini_client.models.generate_content(
                model='gemini-2.0-flash', contents=prompt
            )
            raw = response.text.strip()

            if raw.startswith('```'):
                raw = raw.split('\n', 1)[1] if '\n' in raw else raw[3:]
                if raw.endswith('```'):
                    raw = raw[:-3]
                raw = raw.strip()

            result = json.loads(raw)

            sentiment = result.get('sentiment', 'Neutrální / pozitivní')
            if 'negativ' in sentiment.lower():
                sentiment = 'Negativní'
            else:
                sentiment = 'Neutrální / pozitivní'

            komentar = result.get('komentar', '').strip()
            zdroje = result.get('zdroje', '').strip()

            logger.info(f"Gemini analysis: {sentiment} | {komentar[:80]}")
            return {'sentiment': sentiment, 'komentar': komentar, 'zdroje': zdroje}

        except Exception as e:
            logger.warning(f"Gemini analysis failed: {e}, falling back to basic")
            return self._analyze_basic(response_text)

    def _analyze_basic(self, text: str) -> dict:
        """Základní keyword-based sentiment analýza (fallback)."""
        from config import NEGATIVE_KEYWORDS
        text_lower = text.lower()
        for kw in NEGATIVE_KEYWORDS:
            if kw.lower() in text_lower:
                return {'sentiment': 'Negativní', 'komentar': '', 'zdroje': ''}
        return {'sentiment': 'Neutrální / pozitivní', 'komentar': '', 'zdroje': ''}

    def extract_sources(self, driver, platform_name: str) -> str:
        """Extrahuje zdroje/linky z odpovědi AI platformy."""
        try:
            if platform_name == 'Perplexity':
                selectors = [
                    'cite a[href^="http"]',
                    '[class*="citation"] a[href^="http"]',
                    'a[class*="source"][href^="http"]',
                ]
            elif platform_name == 'ChatGPT':
                selectors = [
                    'div[data-message-author-role="assistant"] a[href^="http"]',
                ]
            else:
                selectors = [
                    '.model-response-text a[href^="http"]',
                    '.response-container a[href^="http"]',
                    'message-content a[href^="http"]',
                    '.markdown a[href^="http"]',
                    '.model-response a[href^="http"]',
                    '[data-test-id="model-response"] a[href^="http"]',
                ]

            for selector in selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    links = []
                    for el in elements:
                        href = el.get_attribute('href')
                        if href and href.startswith('http'):
                            links.append(href)
                    if links:
                        unique = list(dict.fromkeys(links))[:3]
                        return ', '.join(unique)
                except Exception:
                    continue

            # Gemini fallback — všechny linky mimo navigaci
            if platform_name == 'Gemini':
                elements = driver.find_elements(By.CSS_SELECTOR, 'a[href^="http"]')
                links = []
                exclude = ['google.com/intl', 'support.google', 'policies.google',
                           'accounts.google', 'myactivity.google']
                for el in elements:
                    href = el.get_attribute('href')
                    if href and href.startswith('http') and not any(ex in href for ex in exclude):
                        links.append(href)
                if links:
                    unique = list(dict.fromkeys(links))[:3]
                    return ', '.join(unique)

            return ''
        except Exception as e:
            logger.warning(f"Extrakce zdrojů selhala ({platform_name}): {e}")
            return ''

    def upload_screenshot_to_drive(self, file_path: str, client_name: str) -> str:
        """Uploadne screenshot na Google Drive a vrátí share link."""
        try:
            folder_name = f"AI_Monitoring_{client_name}"
            folder_id = self._get_or_create_drive_folder(folder_name)

            file_name = os.path.basename(file_path)
            file_metadata = {
                'name': file_name,
                'parents': [folder_id],
            }
            media = MediaFileUpload(file_path, mimetype='image/png')
            uploaded = self.drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink',
                supportsAllDrives=True,
            ).execute()

            self.drive_service.permissions().create(
                fileId=uploaded['id'],
                body={'type': 'anyone', 'role': 'reader'},
                supportsAllDrives=True,
            ).execute()

            link = uploaded.get('webViewLink', '')
            logger.info(f"Screenshot uploaded: {file_name} -> {link}")
            return link
        except Exception as e:
            logger.error(f"Upload screenshotu selhal: {e}")
            return ''

    def _get_or_create_drive_folder(self, folder_name: str) -> str:
        """Najde nebo vytvoří složku na Google Drive."""
        query = (
            f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' "
            f"and trashed=false"
        )
        if self.drive_folder_id:
            query += f" and '{self.drive_folder_id}' in parents"

        try:
            results = self.drive_service.files().list(
                q=query, spaces='drive', fields='files(id)',
                includeItemsFromAllDrives=True, supportsAllDrives=True,
            ).execute()
            files = results.get('files', [])
            if files:
                return files[0]['id']
        except Exception as e:
            logger.warning(f"Drive folder lookup failed: {e}")

        metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
        }
        if self.drive_folder_id:
            metadata['parents'] = [self.drive_folder_id]

        folder = self.drive_service.files().create(
            body=metadata, fields='id',
            supportsAllDrives=True,
        ).execute()
        logger.info(f"Drive folder created: {folder_name} (id: {folder['id']})")
        return folder['id']

    def _format_row(self, worksheet, row_number: int, platform_name: str, sentiment: str):
        """Aplikuje barevné formátování na řádek v Google Sheets."""
        platform = PLATFORMS[platform_name]

        worksheet.format(f'A{row_number}', {
            'backgroundColor': platform['color'],
            'textFormat': {
                'bold': True,
                'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}
            },
        })

        if sentiment == 'Negativní':
            bg = {'red': 1, 'green': 0, 'blue': 0}
            fg = {'red': 1, 'green': 1, 'blue': 1}
        else:
            bg = {'red': 0.7, 'green': 0.9, 'blue': 0.7}
            fg = {'red': 0, 'green': 0, 'blue': 0}

        worksheet.format(f'B{row_number}', {
            'backgroundColor': bg,
            'textFormat': {'bold': True, 'foregroundColor': fg},
        })

        today = datetime.now().weekday()
        if today in (0, 3):
            worksheet.format(f'D{row_number}', {
                'backgroundColor': {'red': 1, 'green': 0.9, 'blue': 0.4},
            })

    def _wait_for_response(self, driver, platform: dict, client_name: str, platform_name: str) -> str:
        """Čeká dokud AI platforma nenačte odpověď."""
        max_wait = 90
        poll_interval = 3
        stable_checks = 2

        prev_text = ''
        stable_count = 0
        elapsed = 0

        time.sleep(5)
        elapsed = 5

        selectors = [s.strip() for s in platform['response_selector'].split(', ')]

        while elapsed < max_wait:
            response_text = ''
            for selector in selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        texts = []
                        for el in elements:
                            t = el.text
                            if t and t.strip():
                                texts.append(t)
                        if texts:
                            response_text = '\n'.join(texts)
                            break
                except Exception:
                    continue

            if response_text and response_text == prev_text:
                stable_count += 1
                if stable_count >= stable_checks:
                    logger.info(f"[{client_name}] {platform_name}: Response loaded ({elapsed}s, {len(response_text)} chars)")
                    return response_text
            else:
                stable_count = 0

            prev_text = response_text
            time.sleep(poll_interval)
            elapsed += poll_interval

        if prev_text:
            logger.warning(f"[{client_name}] {platform_name}: Response timeout ({max_wait}s), using partial ({len(prev_text)} chars)")
        else:
            logger.error(f"[{client_name}] {platform_name}: No response after {max_wait}s")
        return prev_text

    def _dismiss_popups(self, driver, platform_name: str):
        """Zavře cookie/login popupy."""
        dismiss_texts = [
            "Stay logged out", "Zůstat odhlášený",
            "Odmítnout", "Reject", "Accept",
            "Přijmout vše", "Got it",
        ]
        for text in dismiss_texts:
            try:
                buttons = driver.find_elements(By.XPATH, f'//button[contains(text(), "{text}")]')
                for btn in buttons:
                    if btn.is_displayed():
                        btn.click()
                        time.sleep(1)
                        logger.info(f"{platform_name}: Dismissed popup '{text}'")
            except Exception:
                continue

        # Zavři X tlačítka na popupech
        try:
            close_selectors = [
                '[data-testid="close-button"]',
                'button[aria-label="Close"]',
                'button[aria-label="Zavřít"]',
            ]
            for sel in close_selectors:
                buttons = driver.find_elements(By.CSS_SELECTOR, sel)
                for btn in buttons:
                    if btn.is_displayed():
                        btn.click()
                        time.sleep(0.5)
        except Exception:
            pass

    def monitor_single_query(
        self, driver, platform_name: str, keyword: str,
        client_name: str, worksheet, retry_count: int = 0
    ):
        """Provede jeden dotaz na AI platformu a zapíše výsledek."""
        max_retries = 2
        platform = PLATFORMS[platform_name]

        try:
            # Přidej kontext k dotazu pokud platforma nezná značku
            query_keyword = keyword
            if 'Recenze' not in keyword:
                context_word = KEYWORD_CONTEXT.get(platform_name, {}).get(client_name)
                if context_word:
                    query_keyword = f"{keyword} {context_word}"

            logger.info(f"[{client_name}] {platform_name} <- '{query_keyword}'" +
                         (f" (sheet: '{keyword}')" if query_keyword != keyword else '') +
                         (f" (retry {retry_count})" if retry_count > 0 else ''))

            # Načti platformu
            driver.get(platform['url'])
            time.sleep(5)

            # Detect login wall
            if self._detect_login_wall(driver, platform_name):
                raise Exception(f"LOGIN_WALL: {platform_name} vyžaduje ruční přihlášení")

            # Dismiss popupy
            self._dismiss_popups(driver, platform_name)

            # Najdi input field
            input_el = None
            for selector in platform['input_selector'].split(', '):
                try:
                    input_el = WebDriverWait(driver, 10).until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, selector.strip()))
                    )
                    if input_el:
                        break
                except Exception:
                    continue

            if not input_el:
                raise Exception("Input field nenalezen")

            # Zadej keyword
            input_el.click()
            time.sleep(0.5)
            try:
                input_el.clear()
                input_el.send_keys(query_keyword)
            except Exception:
                # Fallback pro contenteditable elementy (Gemini)
                driver.execute_script(
                    "arguments[0].innerText = arguments[1]", input_el, query_keyword
                )
            time.sleep(0.5)

            # Odešli
            submitted = False
            if platform['submit_selector']:
                for selector in platform['submit_selector'].split(', '):
                    try:
                        submit_btn = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, selector.strip()))
                        )
                        if submit_btn:
                            submit_btn.click()
                            submitted = True
                            break
                    except Exception:
                        continue
            if not submitted:
                input_el.send_keys(Keys.RETURN)

            # Počkej na odpověď
            logger.info(f"[{client_name}] {platform_name}: Waiting for response...")
            response_text = self._wait_for_response(driver, platform, client_name, platform_name)

            # Prázdná odpověď → retry
            if not response_text.strip():
                raise Exception("Prázdná odpověď")

            # Screenshot
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            safe_keyword = keyword.replace(' ', '_').replace('/', '_')
            screenshot_name = f"{platform_name}_{safe_keyword}_{timestamp}.png"
            screenshot_path = os.path.join(tempfile.gettempdir(), screenshot_name)
            driver.save_screenshot(screenshot_path)

            # Sentiment analýza pomocí Gemini AI
            analysis = self.analyze_with_gemini(response_text, platform_name, keyword)
            sentiment = analysis['sentiment']
            komentar = analysis['komentar']
            zdroje_gemini = analysis['zdroje']
            logger.info(f"[{client_name}] {platform_name} '{keyword}': {sentiment}")

            # Extrakce zdrojů z DOM
            page_sources = self.extract_sources(driver, platform_name)
            sources = page_sources or zdroje_gemini

            # Upload screenshotu
            screenshot_link = self.upload_screenshot_to_drive(screenshot_path, client_name)

            # Zápis do Google Sheets
            now = datetime.now()
            day_name = DAY_NAMES.get(now.weekday(), '?')
            date_str = f"{now.day}.{now.month}.{now.year}"

            row = [
                platform_name,       # A: AI
                sentiment,           # B: negativní / neutrální výsledek
                keyword,             # C: Klíčové slovo
                day_name,            # D: Den
                date_str,            # E: Datum
                sources,             # F: Web/Zdroj
                komentar,            # G: Komentáře
                screenshot_link,     # H: Odkaz na screen
            ]
            self._sheets_retry(worksheet.append_row, row, value_input_option='USER_ENTERED')
            row_number = len(worksheet.get_all_values())

            # Formátování
            self._format_row(worksheet, row_number, platform_name, sentiment)

            logger.info(f"[{client_name}] {platform_name} '{keyword}': Row written (row {row_number})")

            # Track result
            self.results.append({
                'client': client_name,
                'platform': platform_name,
                'keyword': keyword,
                'sentiment': sentiment,
                'komentar': komentar,
                'status': 'OK',
            })

            # Cleanup temp screenshot
            try:
                os.remove(screenshot_path)
            except OSError:
                pass

        except Exception as e:
            logger.error(f"[{client_name}] {platform_name} '{keyword}': ERROR - {e}", exc_info=True)
            # Retry
            if retry_count < max_retries:
                logger.info(f"[{client_name}] {platform_name}: Retry {retry_count + 1}/{max_retries}...")
                time.sleep(5)
                self.monitor_single_query(
                    driver, platform_name, keyword,
                    client_name, worksheet, retry_count=retry_count + 1,
                )
                return
            self.results.append({
                'client': client_name,
                'platform': platform_name,
                'keyword': keyword,
                'sentiment': '',
                'komentar': '',
                'status': f'CHYBA: {e} (po {max_retries + 1} pokusech)',
            })

    def _build_summary_email(self, start_time: datetime, error: str = None) -> tuple:
        """Sestavi subject a body pro completion email."""
        end_time = datetime.now()
        duration = end_time - start_time
        minutes = int(duration.total_seconds() // 60)

        ok_count = sum(1 for r in self.results if r['status'] == 'OK')
        fail_count = sum(1 for r in self.results if r['status'] != 'OK')
        neg_count = sum(1 for r in self.results if r['sentiment'] == 'Negativní')
        pos_count = sum(1 for r in self.results if r['sentiment'] == 'Neutrální / pozitivní')

        total = len(CLIENTS) * len(PLATFORMS) * 2
        status = 'OK' if fail_count == 0 and not error else 'CHYBA'

        subject = f"AI Monitoring {end_time.strftime('%d.%m.%Y')} - {status} ({ok_count}/{total})"

        lines = [
            f"AI Monitoring - {end_time.strftime('%d.%m.%Y %H:%M')}",
            f"Status: {status}",
            f"Doba behu: {minutes} min",
            f"Dotazu: {ok_count} OK / {fail_count} chyb (z {total})",
            f"Sentiment: {neg_count}x Negativni, {pos_count}x Neutralni/pozitivni",
            "",
        ]

        if error:
            lines.append(f"KRITICKA CHYBA: {error}")
            lines.append("")

        for client_name in CLIENTS:
            client_results = [r for r in self.results if r['client'] == client_name]
            if not client_results:
                continue

            lines.append(f"--- {client_name} ---")
            for r in client_results:
                status_icon = 'OK' if r['status'] == 'OK' else 'FAIL'
                sentiment_short = 'NEG' if r['sentiment'] == 'Negativní' else 'OK'
                comment = r['komentar'][:80] if r['komentar'] else ''
                lines.append(f"  [{status_icon}] {r['platform']} | {r['keyword']} | {sentiment_short} | {comment}")
                if r['status'] != 'OK':
                    lines.append(f"         {r['status']}")
            lines.append("")

        login_walls = [r for r in self.results if 'LOGIN_WALL' in r['status']]
        if login_walls:
            platforms = list(dict.fromkeys(r['platform'] for r in login_walls))
            lines.append("=== NUTNÁ RUČNÍ AKCE ===")
            for p in platforms:
                lines.append(f"  ⚠️  Přihlaste se ručně na {p} v prohlížeči na monitorovacím PC")
            lines.append("")

        errors = [r for r in self.results if r['status'] != 'OK' and 'LOGIN_WALL' not in r['status']]
        if errors:
            lines.append("=== CHYBY ===")
            for r in errors:
                lines.append(f"  {r['client']} / {r['platform']} / {r['keyword']}: {r['status']}")
            lines.append("")

        sheet_url = f"https://docs.google.com/spreadsheets/d/{self.spreadsheet_id}/edit"
        lines.append(f"Google Sheets: {sheet_url}")

        body = '\n'.join(lines)
        return subject, body

    def run_monitoring(self, force: bool = False, start_from: str = None):
        """Hlavní metoda - spustí celý monitoring cyklus."""
        logger.info("=" * 60)
        logger.info("AI Monitoring started")
        logger.info("=" * 60)

        if not force and not self.should_run_today():
            logger.info("Dnes není monitorovací den (Po/Čt). Ukončuji. (použij --force pro přeskočení)")
            return

        if force:
            logger.info("FORCE mode - přeskakuji day check")

        # Error recovery: --start-from KlientName
        skip = start_from is not None
        if skip:
            if start_from not in CLIENTS:
                available = ', '.join(CLIENTS.keys())
                logger.error(f"Klient '{start_from}' neexistuje. Dostupní: {available}")
                return
            logger.info(f"START-FROM mode - přeskakuji klienty před '{start_from}'")

        # Reset results
        self.results = []
        start_time = datetime.now()

        # Start email
        total = len(CLIENTS) * len(PLATFORMS) * 2
        clients_list = ', '.join(CLIENTS.keys())
        sheet_url = f"https://docs.google.com/spreadsheets/d/{self.spreadsheet_id}/edit"
        start_info = (
            f"AI Monitoring zahajen - {start_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"Klienti: {clients_list}\n"
            f"Platformy: {', '.join(PLATFORMS.keys())}\n"
            f"Celkem dotazu: {total}\n"
        )
        if start_from:
            start_info += f"Start od: {start_from}\n"
        start_info += f"\nGoogle Sheets: {sheet_url}\n"
        self._send_email(
            f"AI Monitoring zahajen - {start_time.strftime('%d.%m.%Y %H:%M')}",
            start_info,
        )

        critical_error = None
        headless = os.getenv('HEADLESS', 'False').lower() == 'true'
        driver = None

        try:
            driver = self._create_driver(headless=headless)

            for client_name, keywords in CLIENTS.items():
                if skip:
                    if client_name == start_from:
                        skip = False
                    else:
                        logger.info(f"--- Skipping: {client_name} ---")
                        continue

                logger.info(f"--- Client: {client_name} ---")
                worksheet = self.get_or_create_worksheet(client_name)

                for platform_name in PLATFORMS:
                    for keyword in keywords:
                        self.monitor_single_query(
                            driver, platform_name, keyword,
                            client_name, worksheet
                        )
                        time.sleep(3)

        except Exception as e:
            critical_error = str(e)
            logger.error(f"Critical error: {e}", exc_info=True)
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

        # Completion email
        subject, body = self._build_summary_email(start_time, critical_error)
        self._send_email(subject, body)

        logger.info("=" * 60)
        logger.info("AI Monitoring completed")
        logger.info("=" * 60)


if __name__ == "__main__":
    import sys

    # Načti .env soubor pokud existuje
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())

    SPREADSHEET_ID = os.getenv(
        'SPREADSHEET_ID',
        '1PO2aa4mkgHUg4H9WgTog5H5CUVELkKgOgiotHOwiyIA'
    )
    CREDENTIALS_FILE = os.getenv(
        'CREDENTIALS_FILE',
        'ai-monitoring-487818-214afcbd4ff6.json'
    )
    DRIVE_FOLDER_ID = os.getenv(
        'DRIVE_FOLDER_ID',
        '189Bitp73y8h8Pt6T8LbYVdBMefYMmf1_'
    )
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')

    # SMTP konfigurace pro email notifikace
    smtp_config = None
    smtp_email = os.getenv('SMTP_EMAIL', '')
    smtp_password = os.getenv('SMTP_PASSWORD', '')
    if smtp_email and smtp_password and 'DOPLNIT' not in smtp_email:
        smtp_config = {
            'host': os.getenv('SMTP_HOST', 'smtp.gmail.com'),
            'port': int(os.getenv('SMTP_PORT', '587')),
            'email': smtp_email,
            'password': smtp_password,
            'notify_email': os.getenv('NOTIFY_EMAIL', 'ai-monitoring@medialist.cz'),
        }

    force = '--force' in sys.argv

    # --start-from KlientName (error recovery)
    start_from = None
    for i, arg in enumerate(sys.argv):
        if arg == '--start-from' and i + 1 < len(sys.argv):
            start_from = sys.argv[i + 1]
            break

    monitor = ProductionAIMonitoring(
        spreadsheet_id=SPREADSHEET_ID,
        credentials_file=CREDENTIALS_FILE,
        drive_folder_id=DRIVE_FOLDER_ID,
        gemini_api_key=GEMINI_API_KEY,
        smtp_config=smtp_config,
    )

    monitor.run_monitoring(force=force, start_from=start_from)
