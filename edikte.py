import requests, re, os, smtplib, json
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import gspread
from google.oauth2.service_account import Credentials

BASE_URL = "https://edikte.justiz.gv.at"
SEARCH_URL = f"{BASE_URL}/edikte/exekution/exe-0.2/search"

def get_edikte():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    # Steiermark holen
    r = s.get("https://edikte.justiz.gv.at/edikte/exekution/exe-0.2/search")
    soup = BeautifulSoup(r.text, "lxml")

    # Alle Zeilen mit Versteigerung Steiermark
    ergebnisse = []
    # Suche direkt alle Versteigerungen
    payload = {
        "bundesland": "4",
    }
    r2 = s.post(SEARCH_URL, data=payload)
    soup2 = BeautifulSoup(r2.text, "lxml")

    for a in soup2.find_all("a", href=True):
        if "/edikte/exekution/" not in a["href"]:
            continue
        if "detail" not in a["href"] and "ansicht" not in a["href"]:
            continue

        link = BASE_URL + a["href"] if a["href"].startswith("/") else a["href"]
        try:
            d = s.get(link, timeout=15)
            txt = BeautifulSoup(d.text, "lxml").get_text(" ", strip=True)

            # Nur wenn Steiermark drin
            if "Steiermark" not in txt and "Stmk" not in txt:
                # Trotzdem nehmen wenn bundesland=4, manchmal steht es nicht im Detail
                pass

            # Schätzwert suchen - alle Varianten
            schaetzwert = "k.A."
            patterns = [
                r"Schätzwert[^:]*:\s*([0-9\.\,]+\s*EUR)",
                r"Schätzwert[^0-9]*([0-9\.\,]+\s*EUR)",
                r"Verkehrswert[^:]*:\s*([0-9\.\,]+\s*EUR)",
            ]
            for pat in patterns:
                m = re.search(pat, txt, re.IGNORECASE)
                if m:
                    schaetzwert = m.group(1)
                    break

            # Kurztitel
            kurz = txt[:400].replace("\n"," ")

            # Nur wenn wirklich Versteigerung
            if "Versteigerung" in txt or "Zwangsversteigerung" in txt:
                ergebnisse.append({
                    "text": kurz,
                    "link": link,
                    "schaetzwert": schaetzwert,
                    "full": txt
                })
        except Exception as e:
            print(f"Fehler bei {link}: {e}")
            continue

    # Duplikate entfernen nach Link
    uniq = {e["link"]: e for e in ergebnisse}.values()
    return list(uniq)

def save_to_sheet(edikte):
    creds_dict = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON"))
    creds = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(os.getenv("GOOGLE_SHEET_ID"))
    ws = sh.sheet1

    vals = ws.get_all_values()
    if not vals:
        ws.append_row(["Objekt", "Schätzwert", "Link", "Datum"])
        vals = []

    vorhanden_links = [row[2] if len(row)>2 else "" for row in vals]
    neu = []
    for e in edikte:
        if e["link"] not in vorhanden_links:
            ws.append_row([e["text"], e["schaetzwert"], e["link"], ""])
            neu.append(e)
    return neu

def send_email(neue):
    if not neue:
        print("Keine neuen")
        return
    msg = MIMEMultipart()
    msg["From"] = os.getenv("EMAIL_FROM")
    msg["To"] = os.getenv("EMAIL_TO")
    msg["Subject"] = f"{len(neue)} neue Versteigerungen Steiermark"
    body = "Neue Versteigerungen:\n\n"
    for n in neue:
        body += f"Schätzwert: {n['schaetzwert']}\n{n['text']}\n{n['link']}\n\n"
    msg.attach(MIMEText(body, "plain", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(os.getenv("EMAIL_FROM"), os.getenv("APP_PASSWORD"))
        server.send_message(msg)
    print("Email gesendet")

if __name__ == "__main__":
    ed = get_edikte()
    print(f"{len(ed)} gefunden")
    for x in ed[:3]:
        print(x["schaetzwert"], x["link"])
    neue = save_to_sheet(ed)
    print(f"{len(neue)} neu")
    send_email(neue)
