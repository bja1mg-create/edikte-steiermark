import requests, re, os, smtplib
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import gspread
from google.oauth2.service_account import Credentials
import json

# CONFIG
BASE_URL = "https://edikte.justiz.gv.at"
SEARCH_URL = f"{BASE_URL}/edikte/exekution/exe-0.2/search"
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

def get_edikte():
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    # Nur Steiermark + nur Versteigerung
    data = {
        "bundesland": "4", # Steiermark
        "art": "4", # Versteigerung
    }
    r = session.post(SEARCH_URL, data=data)
    soup = BeautifulSoup(r.text, "lxml")
    
    ergebnisse = []
    for row in soup.select("tr"):
        text = row.get_text(" ", strip=True)
        if not text or "Aktenzeichen" in text:
            continue
        # Nur Versteigerungstermine behalten
        if "Versteigerung" not in text and "Zwangsversteigerung" not in text and "Versteigerungstermin" not in text:
            # Trotzdem nehmen, weil Filter art=4 schon gesetzt, aber zur Sicherheit
            pass

        link_tag = row.find("a")
        link = BASE_URL + link_tag["href"] if link_tag else ""
        
        # Schätzwert extrahieren
        schaetzwert = "k.A."
        m = re.search(r"Schätzwert.*?([\d\.\,]+.*?EUR)", text, re.IGNORECASE)
        if m:
            schaetzwert = m.group(1)
        else:
            m2 = re.search(r"(\d{1,3}(?:\.\d{3})*,\d{2}\s*EUR)", text)
            if m2:
                schaetzwert = m2.group(1)

        # Details holen für besseren Schätzwert
        if link:
            try:
                d = session.get(link, timeout=10)
                ds = BeautifulSoup(d.text, "lxml").get_text(" ", strip=True)
                m3 = re.search(r"Schätzwert.*?(\d[\d\.\,]*\s*EUR)", ds, re.IGNORECASE)
                if m3:
                    schaetzwert = m3.group(1)
            except:
                pass

        ergebnisse.append({
            "text": text[:500],
            "link": link,
            "schaetzwert": schaetzwert
        })
    return ergebnisse

def save_to_sheet(edikte):
    creds_dict = json.loads(CREDS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.sheet1
    
    # Header setzen falls leer
    if not ws.get_all_values():
        ws.append_row(["Datum", "Objekt", "Schätzwert", "Link"])
    
    vorhanden = ws.col_values(4) # Links vergleichen
    neu = []
    for e in edikte:
        if e["link"] not in vorhanden:
            ws.append_row(["", e["text"], e["schaetzwert"], e["link"]])
            neu.append(e)
    return neu

def send_email(neue):
    if not neue:
        print("Keine neuen Edikte")
        return
    msg = MIMEMultipart()
    msg["From"] = os.getenv("EMAIL_FROM")
    msg["To"] = os.getenv("EMAIL_TO")
    msg["Subject"] = f"{len(neue)} neue Versteigerungen Steiermark"
    
    body = "Neue Versteigerungen gefunden:\n\n"
    for n in neue:
        body += f"- Schätzwert: {n['schaetzwert']}\n  {n['text']}\n  {n['link']}\n\n"
    
    msg.attach(MIMEText(body, "plain", "utf-8"))
    
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(os.getenv("EMAIL_FROM"), os.getenv("APP_PASSWORD"))
        server.send_message(msg)
    print(f"Email mit {len(neue)} Edikten gesendet")

if __name__ == "__main__":
    print("Suche starte...")
    edikte = get_edikte()
    print(f"{len(edikte)} gefunden")
    neue = save_to_sheet(edikte)
    send_email(neue)
