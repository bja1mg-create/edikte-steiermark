import requests, re, os, smtplib, json, time
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import gspread
from google.oauth2.service_account import Credentials

BASE_URL = "https://edikte.justiz.gv.at"
LIST_URL = f"{BASE_URL}/edikte/ex/exedi3.nsf/suchedi?SearchView&subf=eex&SearchOrder=4&SearchMax=4999&query=([BL]=(5))"

def get_edikte():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    r = s.get(LIST_URL, timeout=20)
    soup = BeautifulSoup(r.text, "lxml")
    ergebnisse = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue
        typ = tds[0].get_text(" ", strip=True)
        adresse = tds[1].get_text(" ", strip=True)
        a = tr.find("a", href=True)
        if not a:
            continue
        link = BASE_URL + a["href"] if a["href"].startswith("/") else a["href"]
        if "Versteigerung" not in typ:
            continue

        datum = ""
        schaetzwert = "k.A."
        fotos = []
        try:
            d = s.get(link, timeout=15)
            s_soup = BeautifulSoup(d.text, "lxml")
            txt = s_soup.get_text(" ", strip=True)

            m_datum = re.search(r"(\d{2}\.\d{2}\.\d{4})", typ)
            if m_datum:
                datum = m_datum.group(1)

            for pat in [r"Schätzwert.*?([\d\.\,]+\s*EUR)", r"Schätzwert.*?([\d\.\,]+)", r"Verkehrswert.*?([\d\.\,]+\s*EUR)"]:
                m = re.search(pat, txt, re.I)
                if m:
                    schaetzwert = m.group(1)
                    if "EUR" not in schaetzwert:
                        schaetzwert += " EUR"
                    break

            # FOTOS FINDEN
            for img in s_soup.find_all("img", src=True):
                src = img["src"]
                if any(x in src.lower() for x in [".jpg", ".jpeg", ".png", "foto", "bild", "lichtbild"]):
                    full_img = BASE_URL + src if src.startswith("/") else src
                    if full_img.startswith("http"):
                        fotos.append(full_img)

            for link_tag in s_soup.find_all("a", href=True):
                href = link_tag["href"]
                text = link_tag.get_text().lower()
                if any(x in href.lower() for x in [".jpg", ".jpeg", ".png", ".pdf"]) or any(x in text for x in ["foto", "bild", "gutachten", "lichtbild", "expose"]):
                    full = BASE_URL + href if href.startswith("/") else href
                    if full.startswith("http") and full not in fotos:
                        fotos.append(full)

            time.sleep(0.3)
        except Exception as e:
            print(f"Fehler {link}: {e}")

        ergebnisse.append({
            "datum": datum,
            "typ": typ,
            "adresse": adresse,
            "schaetzwert": schaetzwert,
            "link": link,
            "fotos": ", ".join(fotos[:5]) if fotos else "keine Fotos" # max 5 Fotos
        })

    return list({e["link"]: e for e in ergebnisse}.values())

def save_to_sheet(edikte):
    creds = Credentials.from_service_account_info(json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON")), scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(os.getenv("GOOGLE_SHEET_ID")).sheet1
    vals = ws.get_all_values()
    if not vals:
        ws.append_row(["Datum", "Typ", "Adresse", "Schätzwert", "Link", "Fotos"])
        vals = []
    vorhanden = [row[4] if len(row)>4 else "" for row in vals]
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
    msg["Subject"] = f"{len(neue)} neue Versteigerungen Stmk mit Fotos"
    body = ""
    for n in neue:
        body += f"{n['datum']} | {n['schaetzwert']}\n{n['adresse']}\n{n['link']}\nFotos: {n['fotos']}\n\n---\n\n"
    msg.attach(MIMEText(body, "plain", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(os.getenv("EMAIL_FROM"), os.getenv("APP_PASSWORD"))
        server.send_message(msg)

if __name__ == "__main__":
    ed = get_edikte()
    print(f"{len(ed)} gefunden")
    for e in ed[:2]:
        print(e["adresse"], "| Fotos:", e["fotos"][:100])
    neue = save_to_sheet(ed)
    print(f"{len(neue)} neu")
    send_email(neue)
