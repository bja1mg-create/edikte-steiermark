import requests, re, os, smtplib, json, time
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import gspread
from google.oauth2.service_account import Credentials

BASE_URL = "https://edikte.justiz.gv.at"
LIST_URL = "https://edikte.justiz.gv.at/edikte/ex/exedi3.nsf/suchedi?SearchView&subf=eex&SearchOrder=4&SearchMax=500&query=([BL]=(5))"

def get_edikte():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 Chrome"})
    print("Lade Liste...")
    r = s.get(LIST_URL, timeout=30)
    soup = BeautifulSoup(r.text, "lxml")

    ergebnisse = []
    for tr in soup.find_all("tr"):
        a = tr.find("a", href=True)
        if not a:
            continue
        if "alldoc" not in a["href"] and "exedi3.nsf" not in a["href"]:
            continue

        tds = tr.find_all("td")
        if len(tds) < 2:
            continue

        full_text = tr.get_text(" ", strip=True)

        # Datum
        m_datum = re.search(r"(\d{2}\.\d{2}\.\d{4})", full_text)
        datum = m_datum.group(1) if m_datum else ""

        # Typ
        if "Versteigerung" in full_text:
            typ = "Versteigerung"
        elif "Meistbot" in full_text:
            typ = "Meistbotsverteilung"
        elif "Verschiebung" in full_text:
            typ = "Verschiebung"
        else:
            typ = full_text.split(" ")[0]

        # Adresse = mittlere Spalte
        adresse = tds[1].get_text(" ", strip=True) if len(tds) > 1 else full_text

        # Link voll machen
        href = a["href"]
        if href.startswith("/"):
            link = BASE_URL + href
        else:
            link = BASE_URL + "/edikte/ex/exedi3.nsf/" + href

        # Nur Versteigerungen behalten? Wenn du alle willst, nächste 2 Zeilen löschen
        if "Versteigerung" not in full_text:
            continue

        # Detail holen für Schätzwert + Fotos
        schaetzwert = "k.A."
        fotos = []
        try:
            d = s.get(link, timeout=15)
            d_soup = BeautifulSoup(d.text, "lxml")
            txt = d_soup.get_text(" ", strip=True)

            m = re.search(r"Schätzwert.*?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?\s*EUR)", txt, re.I)
            if m:
                schaetzwert = m.group(1)
            else:
                m2 = re.search(r"(\d{1,3}(?:\.\d{3})+,\d{2}\s*EUR)", txt)
                if m2:
                    schaetzwert = m2.group(1)

            for img in d_soup.find_all("a", href=True):
                h = img["href"]
                if any(x in h.lower() for x in [".jpg", ".pdf", ".png"]) or "foto" in img.get_text().lower() or "gutachten" in img.get_text().lower():
                    full_f = BASE_URL + h if h.startswith("/") else h
                    if "edikte" in full_f:
                        fotos.append(full_f)

            time.sleep(0.4)
        except Exception as e:
            print(f"Detail Fehler: {e}")

        ergebnisse.append({
            "datum": datum,
            "typ": typ,
            "adresse": adresse,
            "schaetzwert": schaetzwert,
            "link": link,
            "fotos": ", ".join(fotos[:3]) if fotos else ""
        })

    # Duplikate entfernen
    uniq = {}
    for e in ergebnisse:
        uniq[e["link"]] = e
    return list(uniq.values())

def save_to_sheet(edikte):
    creds = Credentials.from_service_account_info(json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON")), scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(os.getenv("GOOGLE_SHEET_ID")).sheet1
    vals = ws.get_all_values()
    if not vals:
        ws.append_row(["Datum", "Typ", "Adresse", "Schätzwert", "Link", "Fotos"])
        vals = [ws.get_all_values()[0]]

    vorhanden = [row[4] for row in vals if len(row) > 4]
    neu = []
    for e in edikte:
        if e["link"] not in vorhanden:
            ws.append_row([e["datum"], e["typ"], e["adresse"], e["schaetzwert"], e["link"], e["fotos"]])
            neu.append(e)
    return neu

def send_email(neue):
    if not neue:
        print("Keine neuen")
        return
    msg = MIMEMultipart()
    msg["From"] = os.getenv("EMAIL_FROM")
    msg["To"] = os.getenv("EMAIL_TO")
    msg["Subject"] = f"🏠 {len(neue)} neue Versteigerungen Steiermark"
    body = f"Hallo,\n\n{len(neue)} neue Versteigerungen in der Steiermark:\n\n"
    for n in neue:
        body += f"📅 {n['datum']} | 💰 {n['schaetzwert']}\n📍 {n['adresse']}\n🔗 {n['link']}\n"
        if n['fotos']:
            body += f"📸 Fotos/Gutachten: {n['fotos']}\n"
        body += "\n---\n\n"
    body += "Liebe Grüße\nDein Edikte-Bot"
    msg.attach(MIMEText(body, "plain", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(os.getenv("EMAIL_FROM"), os.getenv("APP_PASSWORD"))
        server.send_message(msg)
    print("Email gesendet")

if __name__ == "__main__":
    ed = get_edikte()
    print(f"{len(ed)} Versteigerungen gefunden")
    neue = save_to_sheet(ed)
    print(f"{len(neue)} neu ins Sheet")
    send_email(neue)
