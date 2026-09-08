import requests, re, os, smtplib, json, time
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import gspread
from google.oauth2.service_account import Credentials

BASE_URL = "https://edikte.justiz.gv.at"
LIST_URL = f"{BASE_URL}/edikte/ex/exedi3.nsf/suchedi?SearchView&subf=eex&SearchOrder=4&SearchMax=4999&retfields=~BL=5&ftquery=&query=([BL]=(5))"

def get_edikte():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    print(f"Lade Liste: {LIST_URL}")
    r = s.get(LIST_URL, timeout=20)
    soup = BeautifulSoup(r.text, "lxml")

    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "exedi3.nsf" in href and ("0/" in href or "exekution" in href.lower() or len(href)>20):
            full = BASE_URL + href if href.startswith("/") else href
            if full not in links:
                links.append(full)

    print(f"{len(links)} Detail-Links gefunden")
    ergebnisse = []
    for link in links[:100]: # max 100 zum testen
        try:
            d = s.get(link, timeout=15)
            if "Versteigerung" not in d.text and "versteigerung" not in d.text.lower():
                continue
            # Nur Versteigerung, keine Meistbot etc wenn du willst:
            if "Versteigerung (" not in d.text and "Versteigerungstermin" not in d.text:
                # trotzdem nehmen, aber du kannst hier filtern
                pass

            txt = BeautifulSoup(d.text, "lxml").get_text(" ", strip=True)

            # Schätzwert - 5 Varianten
            schaetzwert = "k.A."
            pats = [
                r"Schätzwert\s*[:\-]?\s*EUR\s*([\d\.\,]+)",
                r"Schätzwert.*?([\d\.\,]+\s*EUR)",
                r"Schätzwert.*?([\d]{1,3}(?:\.\d{3})*(?:,\d{2})?)",
                r"Verkehrswert.*?([\d\.\,]+\s*EUR)",
                r"geringstes Gebot.*?([\d\.\,]+\s*EUR)",
            ]
            for pat in pats:
                m = re.search(pat, txt, re.IGNORECASE)
                if m:
                    schaetzwert = m.group(1)
                    if "EUR" not in schaetzwert:
                        schaetzwert += " EUR"
                    break

            # Titel / Adresse aus Detail
            title = txt[:500]

            # Datum finden
            datum_match = re.search(r"Versteigerung\s*\((\d{2}\.\d{2}\.\d{4})\)", txt)
            datum = datum_match.group(1) if datum_match else ""

            ergebnisse.append({
                "text": title,
                "link": link,
                "schaetzwert": schaetzwert,
                "datum": datum
            })
            time.sleep(0.3)
        except Exception as e:
            print(f"Fehler {link}: {e}")
            continue

    # Duplikate nach Link
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
        ws.append_row(["Datum", "Objekt", "Schätzwert", "Link"])
        vals = []

    vorhanden = [row[2] if len(row)>2 else "" for row in vals]
    neu = []
    for e in edikte:
        if e["link"] not in vorhanden:
            ws.append_row([e["datum"], e["text"], e["schaetzwert"], e["link"]])
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
    body = "Neue Versteigerungen Steiermark (nur Versteigerungstermine):\n\n"
    for n in neue:
        body += f"Datum: {n['datum']}\nSchätzwert: {n['schaetzwert']}\n{n['text'][:300]}\n{n['link']}\n\n---\n\n"
    msg.attach(MIMEText(body, "plain", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(os.getenv("EMAIL_FROM"), os.getenv("APP_PASSWORD"))
        server.send_message(msg)
    print(f"Email mit {len(neue)} gesendet")

if __name__ == "__main__":
    ed = get_edikte()
    print(f"GEFUNDEN: {len(ed)}")
    for x in ed[:3]:
        print(x["datum"], x["schaetzwert"])
    neue = save_to_sheet(ed)
    print(f"NEU: {len(neue)}")
    send_email(neue)
