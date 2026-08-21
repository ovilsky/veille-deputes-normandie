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
    {"nom": "Joël Bruneau", "dept": "14", "circo": "Calvados 1re circ.", "pa": "PA840817", "groupe": "Libertés, Indépendants, Outre-mer et Territoires"},
    {"nom": "Arthur Delaporte", "dept": "14", "circo": "Calvados 2e circ.", "pa": "PA793394", "groupe": "Socialistes et apparentés"},
    {"nom": "Jérémie Patrier-Leitus", "dept": "14", "circo": "Calvados 3e circ.", "pa": "PA793398", "groupe": "Horizons & Indépendants"},
    {"nom": "Christophe Blanchet", "dept": "14", "circo": "Calvados 4e circ.", "pa": "PA719024", "groupe": "Les Démocrates"},
    {"nom": "Bertrand Bouyx", "dept": "14", "circo": "Calvados 5e circ.", "pa": "PA719032", "groupe": "Horizons & Indépendants"},
    {"nom": "Élisabeth Borne", "dept": "14", "circo": "Calvados 6e circ.", "pa": "PA717161", "groupe": "Ensemble pour la République"},
    {"nom": "Christine Loir", "dept": "27", "circo": "Eure 1re circ.", "pa": "PA793672", "groupe": "Rassemblement National"},
    {"nom": "Katiana Levavasseur", "dept": "27", "circo": "Eure 2e circ.", "pa": "PA793608", "groupe": "Rassemblement National"},
    {"nom": "Kévin Mauvieux", "dept": "27", "circo": "Eure 3e circ.", "pa": "PA793616", "groupe": "Rassemblement National"},
    {"nom": "Philippe Brun", "dept": "27", "circo": "Eure 4e circ.", "pa": "PA793624", "groupe": "Socialistes et apparentés"},
    {"nom": "Timothée Houssin", "dept": "27", "circo": "Eure 5e circ.", "pa": "PA793632", "groupe": "Rassemblement National"},
    {"nom": "Philippe Gosselin", "dept": "50", "circo": "Manche 1re circ.", "pa": "PA266797", "groupe": "Droite Républicaine"},
    {"nom": "Bertrand Sorre", "dept": "50", "circo": "Manche 2e circ.", "pa": "PA720190", "groupe": "Ensemble pour la République"},
    {"nom": "Stéphane Travert", "dept": "50", "circo": "Manche 3e circ.", "pa": "PA607395", "groupe": "Ensemble pour la République"},
    {"nom": "Anna Pic", "dept": "50", "circo": "Manche 4e circ.", "pa": "PA794270", "groupe": "Socialistes et apparentés"},
    {"nom": "Chantal Jourdan", "dept": "61", "circo": "Orne 1re circ.", "pa": "PA643192", "groupe": "Socialistes et apparentés"},
    {"nom": "Thierry Liger", "dept": "61", "circo": "Orne 2e circ.", "pa": "PA794750", "groupe": "Droite Républicaine"},
    {"nom": "Cendrine Chazé", "dept": "61", "circo": "Orne 3e circ.", "pa": "PA841595", "groupe": "Droite Républicaine"},
    {"nom": "Florence Herouin-Léautey", "dept": "76", "circo": "Seine-Maritime 1re circ.", "pa": "PA841813", "groupe": "Socialistes et apparentés"},
    {"nom": "Annie Vidal", "dept": "76", "circo": "Seine-Maritime 2e circ.", "pa": "PA722102", "groupe": "Ensemble pour la République"},
    {"nom": "Édouard Bénard", "dept": "76", "circo": "Seine-Maritime 3e circ.", "pa": "PA796106", "groupe": "Gauche Démocrate et Républicaine"},
    {"nom": "Alma Dufour", "dept": "76", "circo": "Seine-Maritime 4e circ.", "pa": "PA795200", "groupe": "La France insoumise - Nouveau Front Populaire"},
    {"nom": "Gérard Leseul", "dept": "76", "circo": "Seine-Maritime 5e circ.", "pa": "PA774958", "groupe": "Socialistes et apparentés"},
    {"nom": "Patrice Martin", "dept": "76", "circo": "Seine-Maritime 6e circ.", "pa": "PA841825", "groupe": "Rassemblement National"},
    {"nom": "Agnès Firmin Le Bodo", "dept": "76", "circo": "Seine-Maritime 7e circ.", "pa": "PA267780", "groupe": "Horizons & Indépendants"},
    {"nom": "Jean-Paul Lecoq", "dept": "76", "circo": "Seine-Maritime 8e circ.", "pa": "PA335612", "groupe": "Gauche Démocrate et Républicaine"},
    {"nom": "Marie-Agnès Poussier-Winsback", "dept": "76", "circo": "Seine-Maritime 9e circ.", "pa": "PA795270", "groupe": "Horizons & Indépendants"},
    {"nom": "Robert Le Bourgeois", "dept": "76", "circo": "Seine-Maritime 10e circ.", "pa": "PA841837", "groupe": "Rassemblement National"},
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

DOC_NUM_RE = re.compile(r"n°\s*(\d+)")


TITLE_SUFFIX_RE = re.compile(r"\s-\s\d+e législature\s-\s")

# Repère une référence courte sans thème ("Proposition n° 1234", "Rapport
# n°1996 - Annexe 33", "Proposition de loi n° 827 rectifiée"...) — dans ce
# cas on ira chercher le vrai thème sur la page du document lui-même.
SHORT_REF_RE = re.compile(
    r"^(Proposition(\s+de\s+loi|\s+de\s+résolution)?|Rapport)\s*n[°o]\s*\d+"
    r"(\s*-\s*Annexe\s*\d+)?\s*(rectifi[ée]e?)?\s*$",
    re.IGNORECASE
)


def fetch_document_theme(url):
    """Pour un document (rapport ou proposition) dont le libellé sur la page
    de dépôts n'est qu'une référence courte, va chercher le vrai thème sur la
    page du document lui-même : son <title> le contient toujours (ex.
    "Proposition de loi visant à moderniser la lutte contre la contrefaçon,
    n° 827 - 17e législature - Assemblée nationale", ou "Annexe 33 -
    Participations financières de l'État : ... - 17e législature -
    Assemblée nationale")."""
    try:
        soup = get(url)
    except requests.RequestException:
        return None
    if not soup.title or not soup.title.string:
        return None
    raw = soup.title.string.strip()
    theme = TITLE_SUFFIX_RE.split(raw)[0].strip()
    theme = re.sub(r"\s-\sAssemblée nationale\s*$", "", theme).strip()
    if not theme or theme.lower() in ("documents", "rapport", "proposition"):
        return None
    return theme


def fetch_documents(pa_id, type_document, max_pages=DOCUMENTS_MAX_PAGES):
    results = []
    seen_keys = set()
    for page in range(1, max_pages + 1):
        url = f"https://www.assemblee-nationale.fr/dyn/deputes/{pa_id}/documents?typeDocument={type_document}"
        if page > 1:
            url += f"&page={page}&limit=10"
        try:
            soup = get(url)
        except requests.RequestException as e:
            print(f"    ! documents({type_document}) page {page}: {e}", file=sys.stderr)
            break

        # Chaque document a un lien de référence courte ("Rapport n°704") et,
        # quand elle existe, une description complète juste à côté en texte
        # simple ("Rapport sur la proposition de loi ... n° 704") — pas
        # toujours présente (ex. annexes budgétaires "Rapport n°1996 - Annexe
        # 33" n'ont souvent pas de description). Chaque item a aussi 2 liens de
        # navigation redondants ("Accéder à la page du document", "Accéder au
        # document au format pdf") qu'il faut ignorer, sinon ils sont comptés
        # comme des documents distincts avec un "titre" inutile.
        items = soup.select("a[href]")
        found_this_page = 0
        for a in items:
            href = a.get("href", "")
            titre = a.get_text(strip=True)
            if not href.startswith("/dyn/17/") or ("textes" not in href and "rapports" not in href):
                continue
            if not titre or len(titre) < 4:
                continue
            if titre.strip().lower().startswith(("accéder", "voir ", "partager")):
                continue  # lien de navigation redondant, pas le vrai document

            num_m = DOC_NUM_RE.search(titre)
            dedup_key = num_m.group(1) if num_m else titre
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            # Remonte au bloc parent pour trouver la date de dépôt et, si elle
            # existe, une ligne de description plus complète que la référence
            # courte du lien.
            block = a
            block_text = ""
            for _ in range(4):
                if block.parent is None:
                    break
                block = block.parent
                block_text = block.get_text("\n", strip=True)
                if DATE_RE.search(block_text):
                    break
            date_m = DATE_RE.search(block_text)
            date_val = date_m.group(1) if date_m else None

            def is_noise(line):
                l = line.strip()
                ll = l.lower()
                return (not l or l == titre or DATE_RE.search(l) or ll == "partager"
                        or ll.startswith(("accéder", "http", "voir ")))

            candidates = [l.strip() for l in block_text.split("\n") if not is_noise(l)]
            titre_complet = max(candidates, key=len) if candidates else titre

            doc_url = href if href.startswith("http") else f"https://www.assemblee-nationale.fr{href}"

            # Pas de vrai thème trouvé sur la page de listing — juste une
            # référence courte (fréquent pour les rapports budgétaires par
            # annexe, et pour certaines propositions) : on va le chercher sur
            # la page du document lui-même. Une requête de plus, mais
            # seulement pour les documents qui en ont besoin.
            if SHORT_REF_RE.match(titre_complet):
                theme = fetch_document_theme(doc_url)
                if theme:
                    titre_complet = f"{theme} ({titre})"
                time.sleep(REQUEST_DELAY)

            results.append({
                "date": date_val,
                "titre": titre_complet,
                "url": doc_url,
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

# Cache en mémoire : un même scrutin est souvent partagé par plusieurs
# députés normands dans une même exécution, pas la peine de le refetcher.
_scrutin_group_cache = {}

GROUP_POSITION_LINE_RE = re.compile(r"^(Pour|Contre|Abstention|Non votant)\s*:\s*(\d+)$")


def fetch_scrutin_group_breakdown(scrutin_url):
    """Récupère, pour un scrutin donné, le nombre de voix Pour/Contre/Abstention
    par groupe politique (section "Votes des groupes" de la page d'analyse du
    scrutin). Résultat mis en cache pour ne pas refetcher deux fois le même
    scrutin. Retourne {nom_du_groupe: {"Pour": N, "Contre": N, ...}}."""
    if scrutin_url in _scrutin_group_cache:
        return _scrutin_group_cache[scrutin_url]

    result = {}
    try:
        soup = get(scrutin_url)
        text = soup.get_text("\n")
        lines = [l.strip() for l in text.split("\n")]
        start_idx = next((i for i, l in enumerate(lines) if l == "Votes des groupes"), None)
        if start_idx is not None:
            current_group = None
            for line in lines[start_idx + 1:]:
                if not line:
                    continue
                m = GROUP_POSITION_LINE_RE.match(line)
                if m and current_group:
                    result.setdefault(current_group, {})[m.group(1)] = int(m.group(2))
                elif not m:
                    if any(stop in line for stop in ("Mentions légales", "LCP", "OPEN DATA", "Assemblée nationale -")):
                        break
                    current_group = line
    except requests.RequestException as e:
        print(f"    ! scrutin {scrutin_url}: {e}", file=sys.stderr)

    _scrutin_group_cache[scrutin_url] = result
    return result


def majority_position(counts):
    """Position majoritaire d'un groupe pour un scrutin, en ignorant les
    non-votants (sauf s'il n'y a que ça)."""
    if not counts:
        return None
    substantive = {k: v for k, v in counts.items() if k != "Non votant"}
    pool = substantive if substantive else counts
    return max(pool, key=pool.get)


DATE_FR_LINE_RE = re.compile(
    r"^(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+\d{1,2}\s+"
    r"(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+\d{4}$"
)


def fetch_interventions(pa_id, max_items=2):
    """Récupère les dernières interventions vidéo d'un député (commission et
    séance publique). page=1 renvoie les plus récentes en premier (vérifié :
    la page 1 montre des dates de juillet 2026, la page 31 des dates de fin
    2024 — tri anti-chronologique confirmé)."""
    url = f"https://www.assemblee-nationale.fr/dyn/deputes/{pa_id}/interventions?page=1&limit={max_items}"
    try:
        soup = get(url)
    except requests.RequestException as e:
        print(f"    ! interventions: {e}", file=sys.stderr)
        return []

    results = []
    seen = set()
    video_links = [a for a in soup.select("a[href*='/dyn/videos/']") if "timeCode" in a.get("href", "")]
    for a in video_links:
        href = a.get("href", "")
        if href in seen:
            continue
        seen.add(href)

        block = a
        block_text = ""
        for _ in range(6):
            if block.parent is None:
                break
            block = block.parent
            block_text = block.get_text("\n", strip=True)
            if "partager" in block_text.lower():
                break

        lines = [l.strip() for l in block_text.split("\n") if l.strip()]
        date_val, titre_val = None, None
        for i, line in enumerate(lines):
            if DATE_FR_LINE_RE.match(line):
                date_val = line
                for line2 in lines[i + 1:]:
                    if line2.lower() == "partager":
                        break
                    titre_val = line2
                    break
                break

        if titre_val:
            results.append({
                "date": date_val,
                "titre": titre_val,
                "url": href if href.startswith("http") else f"https://www.assemblee-nationale.fr{href}",
            })
        if len(results) >= max_items:
            break
    return results


def fetch_votes(pa_id, groupe, max_pages=VOTES_MAX_PAGES):
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

            scrutin_url = href if href.startswith("http") else f"https://www.assemblee-nationale.fr{href}"

            # Compare le vote individuel à la position majoritaire de son groupe
            # pour ce scrutin (source : section "Votes des groupes" de la page
            # d'analyse du scrutin — un appel réseau de plus par vote, mis en
            # cache car plusieurs députés normands votent souvent sur les mêmes
            # scrutins).
            group_breakdown = fetch_scrutin_group_breakdown(scrutin_url)
            group_counts = group_breakdown.get(groupe, {})
            groupe_majorite = majority_position(group_counts)
            position = pos_m.group(1) if pos_m else None
            conforme_groupe = (position == groupe_majorite) if (position and groupe_majorite) else None

            results.append({
                "date": date_m.group(1) if date_m else None,
                "objet": scrutin_m.group(1).strip() if scrutin_m else link.get_text(strip=True),
                "position": position,
                "resultat": ("Adopté" if result_m and "a adopté" in result_m.group(1) else
                             "Rejeté" if result_m else None),
                "url": scrutin_url,
                "conforme_groupe": conforme_groupe,
                "detail_groupe": group_counts if group_counts else None,
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
            "interventions": "https://www.assemblee-nationale.fr/dyn/deputes/{PA}/interventions",
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
        votes = fetch_votes(depute["pa"], depute["groupe"])
        print(f"    {len(votes)} position(s) de vote (page la plus récente)")
        interventions = fetch_interventions(depute["pa"])
        print(f"    {len(interventions)} intervention(s) vidéo")

        output["deputes"][depute["pa"]] = {
            "nom": depute["nom"],
            "dept": depute["dept"],
            "circo": depute["circo"],
            "groupe": depute["groupe"],
            "questions": questions,
            "rapports": rapports,
            "propositions": propositions,
            "votes": votes,
            "interventions": interventions,
        }

    with open("activite-data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("\n✓ Écrit dans activite-data.json")

    if inject_into_html(output):
        print(f"✓ {HTML_FILE} mis à jour avec les nouvelles données — "
              f"il suffit de l'ouvrir (ou de rafraîchir la page si déjà ouverte).")


if __name__ == "__main__":
    main()
