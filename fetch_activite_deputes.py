#!/usr/bin/env python3
"""
Récupère l'activité parlementaire des 28 députés normands depuis les fiches
officielles de l'Assemblée nationale (assemblee-nationale.fr) : questions
écrites, rapports, propositions de loi, et positions de vote.

Sources par député (17e législature) :
  - Questions écrites : /dyn/deputes/{PA}/questions
  - Rapports          : /dyn/deputes/{PA}/documents?typeDocument=rapport
  - Propositions      : /dyn/deputes/{PA}/documents?typeDocument=proposition
  - Positions de vote : /dyn/deputes/{PA}/positions-de-vote

Usage :
    pip install requests beautifulsoup4 --break-system-packages
    python3 fetch_activite_deputes.py

Sortie :
    activite-data.json — à placer à côté de veille-deputes-normandie.html

À planifier en tâche quotidienne (cron / tâche planifiée). Le site de l'AN
n'envoie pas d'en-têtes CORS : ce script doit tourner côté serveur, pas dans
le navigateur.

Note sur "Propositions" : le filtre "Proposition" de l'AN renvoie les
propositions de loi/résolution dont le député est un des auteurs (pas les
simples cosignataires, sauf coche "Cosignataire" côté formulaire — non
répliquée ici pour rester sur l'info la plus éditorialement pertinente :
qui est à l'origine du texte).

Note sur "Positions de vote" : la page liste TOUS les scrutins (y compris les
votes très techniques sur des amendements en série), pas seulement les votes
solennels sur un texte. Le script ne récupère que la première page (10 votes
les plus récents) par défaut — largement suffisant pour une veille, mais pas
un historique complet. Augmentez VOTES_MAX_PAGES si besoin.
"""

import json
import re
import sys
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "VeilleDeputesNormandie/1.0 (usage redaction locale ; contact: redaction@example.fr)"
}

DEPUTES = [
    {"nom": "Joël Bruneau", "dept": "14", "circo": "Calvados 1re circ.", "pa": "PA840817"},
    {"nom": "Arthur Delaporte", "dept": "14", "circo": "Calvados 2e circ.", "pa": "PA793394"},
    {"nom": "Jérémie Patrier-Leitus", "dept": "14", "circo": "Calvados 3e circ.", "pa": "PA793398"},
    {"nom": "Christophe Blanchet", "dept": "14", "circo": "Calvados 4e circ.", "pa": "PA719024"},
    {"nom": "Bertrand Bouyx", "dept": "14", "circo": "Calvados 5e circ.", "pa": "PA719032"},
    {"nom": "Élisabeth Borne", "dept": "14", "circo": "Calvados 6e circ.", "pa": "PA717161"},
    {"nom": "Christine Loir", "dept": "27", "circo": "Eure 1re circ.", "pa": "PA793672"},
    {"nom": "Katiana Levavasseur", "dept": "27", "circo": "Eure 2e circ.", "pa": "PA793608"},
    {"nom": "Kévin Mauvieux", "dept": "27", "circo": "Eure 3e circ.", "pa": "PA793616"},
    {"nom": "Philippe Brun", "dept": "27", "circo": "Eure 4e circ.", "pa": "PA793624"},
    {"nom": "Timothée Houssin", "dept": "27", "circo": "Eure 5e circ.", "pa": "PA793632"},
    {"nom": "Philippe Gosselin", "dept": "50", "circo": "Manche 1re circ.", "pa": "PA266797"},
    {"nom": "Bertrand Sorre", "dept": "50", "circo": "Manche 2e circ.", "pa": "PA720190"},
    {"nom": "Stéphane Travert", "dept": "50", "circo": "Manche 3e circ.", "pa": "PA607395"},
    {"nom": "Anna Pic", "dept": "50", "circo": "Manche 4e circ.", "pa": "PA794270"},
    {"nom": "Chantal Jourdan", "dept": "61", "circo": "Orne 1re circ.", "pa": "PA643192"},
    {"nom": "Thierry Liger", "dept": "61", "circo": "Orne 2e circ.", "pa": "PA794750"},
    {"nom": "Cendrine Chazé", "dept": "61", "circo": "Orne 3e circ.", "pa": "PA841595"},
    {"nom": "Florence Herouin-Léautey", "dept": "76", "circo": "Seine-Maritime 1re circ.", "pa": "PA841813"},
    {"nom": "Annie Vidal", "dept": "76", "circo": "Seine-Maritime 2e circ.", "pa": "PA722102"},
    {"nom": "Édouard Bénard", "dept": "76", "circo": "Seine-Maritime 3e circ.", "pa": "PA796106"},
    {"nom": "Alma Dufour", "dept": "76", "circo": "Seine-Maritime 4e circ.", "pa": "PA795200"},
    {"nom": "Gérard Leseul", "dept": "76", "circo": "Seine-Maritime 5e circ.", "pa": "PA774958"},
    {"nom": "Patrice Martin", "dept": "76", "circo": "Seine-Maritime 6e circ.", "pa": "PA841825"},
    {"nom": "Agnès Firmin Le Bodo", "dept": "76", "circo": "Seine-Maritime 7e circ.", "pa": "PA267780"},
    {"nom": "Jean-Paul Lecoq", "dept": "76", "circo": "Seine-Maritime 8e circ.", "pa": "PA335612"},
    {"nom": "Marie-Agnès Poussier-Winsback", "dept": "76", "circo": "Seine-Maritime 9e circ.", "pa": "PA795270"},
    {"nom": "Robert Le Bourgeois", "dept": "76", "circo": "Seine-Maritime 10e circ.", "pa": "PA841837"},
]

QUESTIONS_MAX_PAGES = 2   # 10 résultats/page
DOCUMENTS_MAX_PAGES = 1   # rapports / propositions : peu fréquents, 1 page suffit en veille
VOTES_MAX_PAGES = 1       # positions de vote : très nombreuses, 1 page = 10 votes les plus récents
REQUEST_DELAY = 1.0       # secondes entre deux requêtes (politesse envers le serveur de l'AN)

DATE_RE = re.compile(
    r"(\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|"
    r"septembre|octobre|novembre|décembre)\s+\d{4})"
)


def get(url):
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


# ---------- Questions écrites ----------

NUM_Q_RE = re.compile(r"(Question (?:écrite|au Gouvernement|orale) n°\s*\d+)")
RUBRIQUE_RE = re.compile(r"Rubrique\s*:\s*(.+)")
TITRE_RE = re.compile(r"Titre\s*:\s*(.+)")
STATUT_Q_RE = re.compile(r"(Question sans réponse|Réponse publiée le [^\n]+|Question posée en séance)")


def fetch_questions(pa_id):
    results = []
    seen = set()
    for page in range(1, QUESTIONS_MAX_PAGES + 1):
        url = f"https://www.assemblee-nationale.fr/dyn/deputes/{pa_id}/questions"
        if page > 1:
            url += f"?page={page}&limit=10"
        try:
            soup = get(url)
        except requests.RequestException as e:
            print(f"    ! questions page {page}: {e}", file=sys.stderr)
            break

        links = soup.select("a[href*='/questions/QANR']")
        page_count = 0
        for link in links:
            href = link.get("href", "")
            if href in seen:
                continue
            seen.add(href)
            block = link
            text = ""
            for _ in range(5):
                if block.parent is None:
                    break
                block = block.parent
                text = block.get_text("\n", strip=True)
                if RUBRIQUE_RE.search(text) and TITRE_RE.search(text):
                    break
            titre_m = TITRE_RE.search(text)
            if not titre_m:
                continue
            date_m = DATE_RE.search(text)
            num_m = NUM_Q_RE.search(text)
            rub_m = RUBRIQUE_RE.search(text)
            statut_m = STATUT_Q_RE.search(text)
            results.append({
                "numero": num_m.group(1) if num_m else None,
                "date": date_m.group(1) if date_m else None,
                "rubrique": rub_m.group(1).strip() if rub_m else None,
                "titre": titre_m.group(1).strip(),
                "statut": statut_m.group(1).strip() if statut_m else None,
                "url": href if href.startswith("http") else f"https://www.assemblee-nationale.fr{href}",
            })
            page_count += 1
        if page_count == 0:
            break
        time.sleep(REQUEST_DELAY)
    return results


# ---------- Rapports & propositions (documents?typeDocument=...) ----------

def fetch_documents(pa_id, type_document, max_pages=DOCUMENTS_MAX_PAGES):
    results = []
    for page in range(1, max_pages + 1):
        url = f"https://www.assemblee-nationale.fr/dyn/deputes/{pa_id}/documents?typeDocument={type_document}"
        if page > 1:
            url += f"&page={page}&limit=10"
        try:
            soup = get(url)
        except requests.RequestException as e:
            print(f"    ! documents({type_document}) page {page}: {e}", file=sys.stderr)
            break

        # Chaque document a un lien "Accéder à la page du document"
        items = soup.select("a[href]")
        found_this_page = 0
        seen_urls = set()
        for a in items:
            href = a.get("href", "")
            text = a.get_text(strip=True)
            if not href.startswith("/dyn/17/") or "textes" not in href and "rapports" not in href:
                continue
            if href in seen_urls:
                continue
            seen_urls.add(href)
            # Remonte au bloc contenant le titre complet + la date de dépôt
            block = a
            block_text = ""
            for _ in range(4):
                if block.parent is None:
                    break
                block = block.parent
                block_text = block.get_text("\n", strip=True)
                if DATE_RE.search(block_text) and len(block_text) > len(text):
                    break
            date_m = DATE_RE.search(block_text)
            # Le titre le plus long trouvé dans le bloc est en général le libellé complet du document
            lines = [l.strip() for l in block_text.split("\n") if l.strip()]
            titre = max(lines, key=len) if lines else text
            results.append({
                "date": date_m.group(1) if date_m else None,
                "titre": titre,
                "url": href if href.startswith("http") else f"https://www.assemblee-nationale.fr{href}",
            })
            found_this_page += 1
        if found_this_page == 0:
            break
        time.sleep(REQUEST_DELAY)
    return results


# ---------- Positions de vote ----------

POSITION_RE = re.compile(r"^(Pour|Contre|Abstention)$", re.MULTILINE)
SCRUTIN_RE = re.compile(r"(Scrutin public n°\s*\d+ sur [^\n]+?)\s*(?:\n|$)")
RESULT_RE = re.compile(r"(L'Assemblée nationale a adopté|L'Assemblée nationale n'a pas adopté)")


def fetch_votes(pa_id, max_pages=VOTES_MAX_PAGES):
    results = []
    for page in range(1, max_pages + 1):
        url = f"https://www.assemblee-nationale.fr/dyn/deputes/{pa_id}/positions-de-vote"
        if page > 1:
            url += f"?page={page}&limit=10"
        try:
            soup = get(url)
        except requests.RequestException as e:
            print(f"    ! positions-de-vote page {page}: {e}", file=sys.stderr)
            break

        links = soup.select("a[href*='/scrutins/']")
        seen = set()
        found = 0
        for link in links:
            href = link.get("href", "")
            if "scrutins/" not in href or href in seen:
                continue
            seen.add(href)
            block = link
            text = ""
            for _ in range(6):
                if block.parent is None:
                    break
                block = block.parent
                text = block.get_text("\n", strip=True)
                if RESULT_RE.search(text):
                    break

            scrutin_m = SCRUTIN_RE.search(text) or re.search(r"(Scrutin public n°\s*\d+[^\n]*)", text)
            date_m = DATE_RE.search(text)
            pos_m = POSITION_RE.search(text)
            result_m = RESULT_RE.search(text)

            results.append({
                "date": date_m.group(1) if date_m else None,
                "objet": scrutin_m.group(1).strip() if scrutin_m else link.get_text(strip=True),
                "position": pos_m.group(1) if pos_m else None,
                "resultat": ("Adopté" if result_m and "a adopté" in result_m.group(1) else
                             "Rejeté" if result_m else None),
                "url": href if href.startswith("http") else f"https://www.assemblee-nationale.fr{href}",
            })
            found += 1
        if found == 0:
            break
        time.sleep(REQUEST_DELAY)
    return results


HTML_FILE = "index.html"
START_MARKER = "// __ACTIVITY_DATA_START__"
END_MARKER = "// __ACTIVITY_DATA_END__"


def inject_into_html(data):
    """Réécrit le bloc ACTIVITY_DATA dans le fichier HTML avec les données
    fraîchement récupérées, pour qu'un simple double-clic sur le fichier
    affiche toujours les dernières données — sans avoir besoin de serveur
    ni de connaissances techniques pour le consulter."""
    try:
        with open(HTML_FILE, "r", encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        print(f"  ! {HTML_FILE} introuvable dans ce dossier : le bloc de données n'a "
              f"pas pu être mis à jour dans le dashboard (activite-data.json a bien "
              f"été écrit, mais il faudra le charger manuellement).", file=sys.stderr)
        return False

    if START_MARKER not in html or END_MARKER not in html:
        print(f"  ! Marqueurs {START_MARKER}/{END_MARKER} introuvables dans {HTML_FILE} : "
              f"le fichier a peut-être été modifié. Mise à jour automatique annulée.",
              file=sys.stderr)
        return False

    before, rest = html.split(START_MARKER, 1)
    _, after = rest.split(END_MARKER, 1)

    js_data = json.dumps(data, ensure_ascii=False, indent=2)
    new_block = f"{START_MARKER}\nconst ACTIVITY_DATA = {js_data};\n{END_MARKER}"

    new_html = before + new_block + after

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(new_html)

    return True


def main():
    output = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "note": "",
        "sources": {
            "questions": "https://www.assemblee-nationale.fr/dyn/deputes/{PA}/questions",
            "rapports": "https://www.assemblee-nationale.fr/dyn/deputes/{PA}/documents?typeDocument=rapport",
            "propositions": "https://www.assemblee-nationale.fr/dyn/deputes/{PA}/documents?typeDocument=proposition",
            "votes": "https://www.assemblee-nationale.fr/dyn/deputes/{PA}/positions-de-vote",
        },
        "deputes": {},
    }

    for depute in DEPUTES:
        print(f"→ {depute['nom']} ({depute['circo']})")
        questions = fetch_questions(depute["pa"])
        print(f"    {len(questions)} question(s) écrite(s)")
        rapports = fetch_documents(depute["pa"], "rapport")
        print(f"    {len(rapports)} rapport(s)")
        propositions = fetch_documents(depute["pa"], "proposition")
        print(f"    {len(propositions)} proposition(s)")
        votes = fetch_votes(depute["pa"])
        print(f"    {len(votes)} position(s) de vote (page la plus récente)")

        output["deputes"][depute["pa"]] = {
            "nom": depute["nom"],
            "dept": depute["dept"],
            "circo": depute["circo"],
            "questions": questions,
            "rapports": rapports,
            "propositions": propositions,
            "votes": votes,
        }

    with open("activite-data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("\n✓ Écrit dans activite-data.json")

    if inject_into_html(output):
        print(f"✓ {HTML_FILE} mis à jour avec les nouvelles données — "
              f"il suffit de l'ouvrir (ou de rafraîchir la page si déjà ouverte).")


if __name__ == "__main__":
    main()
