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
import unicodedata
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
REQUEST_DELAY = 1.5       # secondes entre deux requêtes (politesse envers le serveur de l'AN —
                          # relevé de 1.0 à 1.5 après des 503 "Backend fetch failed" en rafale
                          # constatés sur un run réel une fois un certain volume de requêtes atteint)

DATE_RE = re.compile(
    r"(\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|"
    r"septembre|octobre|novembre|décembre)\s+\d{4})"
)


def get(url, max_retries=3):
    """GET avec réessais en cas d'erreur transitoire (503 "Backend fetch
    failed", timeout, etc.). Constaté en usage réel (tâche planifiée
    GitHub Actions) : au-delà d'un certain volume de requêtes rapprochées,
    le site de l'Assemblée nationale se met à renvoyer des 503 pour TOUTES
    les requêtes suivantes pendant un moment — sans réessai, ça vide
    complètement les données des derniers députés traités (questions,
    votes, tout). On réessaie donc avec un délai croissant avant
    d'abandonner pour de bon sur cette URL précise."""
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as e:
            last_error = e
            is_5xx = getattr(e, "response", None) is not None and 500 <= e.response.status_code < 600
            is_transient = is_5xx or isinstance(e, (requests.ConnectionError, requests.Timeout))
            if attempt < max_retries and is_transient:
                wait = 5 * attempt
                print(f"    ! {url} : {e} — nouvel essai dans {wait}s ({attempt}/{max_retries})",
                      file=sys.stderr)
                time.sleep(wait)
                continue
            raise
    raise last_error


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
            # On remonte jusqu'à trouver rubrique + titre + statut. S'arrêter
            # dès rubrique+titre trouvés (sans attendre le statut) coupe le
            # texte juste avant la ligne "Question sans réponse" / "Réponse
            # publiée le ..." qui se trouve un niveau plus haut dans le DOM
            # de la page AN — d'où un statut toujours vide. On continue donc
            # à remonter tant que le statut n'est pas trouvé, jusqu'à 8
            # niveaux (au-delà, on garde le dernier texte obtenu de toute
            # façon, avec rubrique/titre déjà acquis).
            best_text = ""
            for _ in range(8):
                if block.parent is None:
                    break
                block = block.parent
                text = block.get_text("\n", strip=True)
                has_rubrique_titre = RUBRIQUE_RE.search(text) and TITRE_RE.search(text)
                if has_rubrique_titre:
                    best_text = text
                    if STATUT_Q_RE.search(text):
                        break
            text = best_text or text
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

# Un vrai titre descriptif fait toujours au moins ~45-50 caractères en
# pratique ("Proposition de loi visant à ..."). Une référence courte, quelle
# que soit sa formulation exacte ("Rapport n°704", "Rapport d'information
# n°3020", "Proposition de loi, n° 3042", "Rapport d'enquête n°..."), reste
# toujours en dessous. Un seuil de longueur est plus robuste qu'une liste de
# formulations possibles, forcément incomplète.
SHORT_REF_MAX_LEN = 45


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
            if len(titre_complet.strip()) < SHORT_REF_MAX_LEN:
                theme = fetch_document_theme(doc_url)
                # N'enrichit que si le thème trouvé est vraiment plus complet
                # que la référence courte déjà en main — sinon (le document
                # lui-même n'a pas plus d'info, souvent le cas pour un texte
                # très récemment déposé) on garde la référence courte telle
                # quelle plutôt que de l'afficher deux fois pour rien.
                if theme and len(theme) > len(titre_complet) + 10:
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
_scrutin_detail_cache = {}

GROUP_POSITION_LINE_RE = re.compile(r"^(Pour|Contre|Abstention|Non votant)\s*:\s*(\d+)$")
GROUP_HEADING_RE = re.compile(r"^(.+?)\(\s*\d+\s*membres?\s*\)$")


def fetch_scrutin_detail(scrutin_url):
    """Récupère, pour un scrutin donné, à la fois le décompte Pour/Contre/
    Abstention par groupe politique ET la position individuelle de CHAQUE
    député nommément cité sur la page (tous groupes confondus), en un seul
    passage sur la section "Votes des groupes" de la page d'analyse du
    scrutin. Résultat mis en cache pour ne pas refetcher deux fois le même
    scrutin.

    La page liste, pour chaque groupe, ses membres classés par catégorie de
    vote ("Pour : N", "Contre : N", ...) suivie de leurs noms — cette liste
    nominative permet de savoir QUELS députés normands ont pris part à un
    scrutin donné, même quand ce scrutin ne figure pas parmi les votes
    personnels les plus récents de tel ou tel député (cf. note sur
    VOTES_MAX_PAGES) : un scrutin découvert via l'historique d'UN seul
    député normand peut ainsi être complété avec tous les autres députés
    normands qui y ont eux aussi pris part.

    Retourne (group_counts, votes_by_name) :
      - group_counts  : {nom_du_groupe: {"Pour": N, "Contre": N, ...}}
      - votes_by_name : {nom_normalisé_du_député: "Pour"|"Contre"|"Abstention"|"Non votant"}
    """
    if scrutin_url in _scrutin_detail_cache:
        return _scrutin_detail_cache[scrutin_url]

    group_counts = {}
    votes_by_name = {}
    try:
        soup = get(scrutin_url)
        text = soup.get_text("\n")
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        start_idx = next((i for i, l in enumerate(lines) if l == "Votes des groupes"), None)
        if start_idx is not None:
            current_group = None
            current_position = None
            for line in lines[start_idx + 1:]:
                if any(stop in line for stop in ("Mentions légales", "LCP", "OPEN DATA", "Assemblée nationale -")):
                    break
                heading_m = GROUP_HEADING_RE.match(line)
                if heading_m:
                    current_group = heading_m.group(1).strip()
                    current_position = None
                    continue
                label_m = GROUP_POSITION_LINE_RE.match(line)
                if label_m:
                    current_position = label_m.group(1)
                    if current_group:
                        group_counts.setdefault(current_group, {})[current_position] = int(label_m.group(2))
                    continue
                # Ni un titre de groupe, ni un label de catégorie : c'est le
                # nom d'un député nommément cité dans la catégorie en cours.
                if current_position and current_group:
                    key = normalize_name(line)
                    if key:
                        votes_by_name[key] = current_position
    except requests.RequestException as e:
        print(f"    ! scrutin {scrutin_url}: {e}", file=sys.stderr)

    _scrutin_detail_cache[scrutin_url] = (group_counts, votes_by_name)
    # Politesse envers le serveur de l'AN : un scrutin peut être découvert
    # jusqu'à 10 fois par député (une fois par vote de sa page personnelle),
    # donc potentiellement beaucoup de requêtes rapprochées avant que le
    # cache ne joue pleinement — d'où une pause ici aussi, pas seulement
    # entre deux pages de la liste des votes d'un même député.
    time.sleep(REQUEST_DELAY)
    return group_counts, votes_by_name


def fetch_scrutin_group_breakdown(scrutin_url):
    """Compatibilité : ne renvoie que le décompte par groupe politique (voir
    fetch_scrutin_detail, qui récupère en un seul passage les positions
    nominatives également)."""
    group_counts, _ = fetch_scrutin_detail(scrutin_url)
    return group_counts


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


def fetch_votes(pa_id, groupe, nom, max_pages=VOTES_MAX_PAGES):
    results = []
    nom_key = normalize_name(nom)
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

            # Position : on privilégie la liste nominative de la page du
            # scrutin lui-même (section "Votes des groupes" — chaque groupe y
            # liste ses membres par catégorie de vote), plus fiable que
            # l'extraction heuristique depuis la page personnelle du député
            # (texte libre, remontée d'ancêtres DOM). On ne retombe sur cette
            # dernière (pos_m) que si le député n'est pas retrouvé nommément
            # sur la page du scrutin. Un seul appel réseau supplémentaire par
            # scrutin, mis en cache car plusieurs députés normands votent
            # souvent sur les mêmes scrutins.
            group_counts_all, votes_by_name = fetch_scrutin_detail(scrutin_url)
            group_counts = group_counts_all.get(groupe, {})
            groupe_majorite = majority_position(group_counts)
            position = votes_by_name.get(nom_key) or (pos_m.group(1) if pos_m else None)
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
# ---------- Indice d'activité (NosDéputés.fr) ----------
#
# ATTENTION — nommage trompeur assumé par NosDéputés.fr eux-mêmes (voir leur
# FAQ : https://www.nosdeputes.fr/faq#post_27) : leur indicateur historique
# "semaines de présence" ne mesure PAS une présence physique brute (chose non
# mesurable de façon fiable et publique) mais un ensemble de marqueurs
# d'activité concrète : interventions en hémicycle/commission, questions
# écrites, amendements signés, votes, rapports... On le récupère et on
# l'affiche donc sous le nom "indice d'activité", jamais comme un taux de
# présence/absence au sens littéral, pour ne pas induire la rédaction en
# erreur sur ce que la donnée représente vraiment.
#
# Source : API ouverte de Regards Citoyens (licence ODbL), un point d'accès,
# toutes les données de synthèse de la législature en cours en une requête :
# https://www.nosdeputes.fr/synthese/data/json

NOSDEPUTES_SYNTHESE_URL = "https://www.nosdeputes.fr/synthese/data/json"

# Clés candidates pour le score d'activité selon les versions de l'API —
# on prend la première trouvée. Si aucune ne matche (l'API a changé de
# nommage), le script log les clés réellement présentes pour ajustement.
ASSIDUITE_CANDIDATE_KEYS = [
    "semaines_presence",
    "semaines_activite",
    "nb_semaines_presence",
    "semaine_presence",
]

# Repli manuel pour des députés dont la fiche NosDéputés.fr existe bel et
# bien (vérifié à la main, une par une) mais que la correspondance par nom
# dans le flux de synthèse en masse ne retrouve pas — sans doute une entrée
# de nom (nom d'usage / nom de famille) qui diffère dans ce flux précis.
# Pour ceux-là uniquement, on interroge directement leur fiche individuelle
# par son identifiant d'URL ("slug") plutôt que de dépendre du matching par
# nom. Toute autre absence (député non présent dans cette liste ET introuvable
# dans le flux de synthèse) est un vrai manque de couverture chez NosDéputés.fr,
# pas un bug de correspondance — rien à corriger côté script dans ce cas.
ASSIDUITE_SLUG_OVERRIDES = {
    "PA717161": "elisabeth-borne",       # Élisabeth Borne
    "PA796106": "edouard-benard",        # Édouard Bénard
    "PA267780": "agnes-firmin-le-bodo",  # Agnès Firmin Le Bodo
}


def fetch_assiduite_by_slug(slug):
    """Repli pour un député listé dans ASSIDUITE_SLUG_OVERRIDES : interroge
    directement sa fiche individuelle NosDéputés.fr par son slug d'URL,
    plutôt que de dépendre de la correspondance par nom dans le flux de
    synthèse en masse (voir ASSIDUITE_SLUG_OVERRIDES)."""
    url = f"https://www.nosdeputes.fr/{slug}/json"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        row = resp.json()
    except Exception as e:
        print(f"    ! Repli par slug échoué pour {slug} : {e}", file=sys.stderr)
        return None
    if isinstance(row, dict) and isinstance(row.get("depute"), dict):
        row = row["depute"]
    return row if isinstance(row, dict) else None


def normalize_name(s):
    """Normalise un nom pour le matching : minuscules, sans accents, sans
    ponctuation, espaces uniques."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z]+", " ", s)
    return " ".join(s.split())


def fetch_assiduite():
    """Récupère l'indice d'activité NosDéputés.fr pour les 28 députés
    normands, en une seule requête, avec correspondance par nom normalisé.

    Ce point d'accès renvoie les données de synthèse pour l'ensemble des
    parlementaires en mandat en une seule réponse : plus lourd et plus lent
    qu'un simple appel API classique, d'où un délai large et 2 tentatives
    avant d'abandonner (une requête isolée un peu lente ne doit pas priver
    tout l'onglet Assiduité de données)."""
    result = {}
    payload = None
    last_error = None
    for attempt in range(1, 3):
        try:
            resp = requests.get(NOSDEPUTES_SYNTHESE_URL, headers=HEADERS, timeout=60)
            resp.raise_for_status()
            payload = resp.json()
            break
        except Exception as e:
            last_error = e
            if attempt < 2:
                print(f"  ! Tentative {attempt} échouée ({e}) — nouvel essai...", file=sys.stderr)
                time.sleep(3)
    if payload is None:
        print(f"  ! Impossible de récupérer https://www.nosdeputes.fr/synthese/data/json après 2 essais : "
              f"{last_error} — l'onglet Assiduité restera vide pour cette extraction, le reste du script "
              f"continue normalement.", file=sys.stderr)
        return result

    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("deputes") or payload.get("synthese") or payload.get("data") or []
    else:
        rows = []

    # Selon le format, chaque ligne peut être enveloppée sous une clé
    # "depute" (comme pour /deputes/json) — on déroule ça si besoin.
    flat_rows = []
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("depute"), dict):
            flat_rows.append(row["depute"])
        else:
            flat_rows.append(row)
    rows = flat_rows

    if not rows:
        print("  ! Réponse NosDéputés.fr inattendue (aucune ligne exploitable) — "
              "à vérifier manuellement sur https://www.nosdeputes.fr/synthese/data/json",
              file=sys.stderr)
        return result

    by_name = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        nom_complet = row.get("nom") or f"{row.get('prenom', '')} {row.get('nom_de_famille', '')}".strip()
        if not nom_complet:
            continue
        by_name[normalize_name(nom_complet)] = row

    debug_printed = False
    for depute in DEPUTES:
        row = by_name.get(normalize_name(depute["nom"]))
        if row is None:
            continue
        valeur = None
        champ_source = None
        for ck in ASSIDUITE_CANDIDATE_KEYS:
            if row.get(ck) not in (None, ""):
                valeur = row[ck]
                champ_source = ck
                break
        if not debug_printed:
            print(f"  (debug) champs disponibles chez NosDéputés.fr pour {depute['nom']} : "
                  f"{sorted(row.keys())}")
            debug_printed = True
        result[depute["pa"]] = {
            "valeur": valeur,
            "champ_source": champ_source,
            "slug": row.get("slug"),
        }

    # Repli par slug pour les cas connus où le nom ne matche pas dans le flux
    # de synthèse en masse malgré une fiche NosDéputés.fr bien réelle (voir
    # ASSIDUITE_SLUG_OVERRIDES).
    for depute in DEPUTES:
        if depute["pa"] in result:
            continue
        slug = ASSIDUITE_SLUG_OVERRIDES.get(depute["pa"])
        if not slug:
            continue
        row = fetch_assiduite_by_slug(slug)
        if not row:
            continue
        valeur = None
        champ_source = None
        for ck in ASSIDUITE_CANDIDATE_KEYS:
            if row.get(ck) not in (None, ""):
                valeur = row[ck]
                champ_source = ck
                break
        result[depute["pa"]] = {
            "valeur": valeur,
            "champ_source": champ_source,
            "slug": row.get("slug", slug),
        }
        print(f"    + {depute['nom']} retrouvé via repli direct (slug={slug}, absent du flux de synthèse en masse)")

    matched = len(result)
    print(f"  → {matched}/{len(DEPUTES)} député(s) normand(s) retrouvé(s) sur NosDéputés.fr")
    manques = [d["nom"] for d in DEPUTES if d["pa"] not in result]
    if manques:
        print(f"  ! Non retrouvés par correspondance de nom (à vérifier) : {', '.join(manques)}")
    return result


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
            "assiduite": "https://www.nosdeputes.fr/synthese/data/json",
        },
        "deputes": {},
    }

    print("→ Indice d'activité (NosDéputés.fr, une requête pour les 28 députés)")
    assiduite_par_pa = fetch_assiduite()

    for depute in DEPUTES:
        print(f"→ {depute['nom']} ({depute['circo']})")
        questions = fetch_questions(depute["pa"])
        print(f"    {len(questions)} question(s) écrite(s)")
        rapports = fetch_documents(depute["pa"], "rapport")
        print(f"    {len(rapports)} rapport(s)")
        propositions = fetch_documents(depute["pa"], "proposition")
        print(f"    {len(propositions)} proposition(s)")
        votes = fetch_votes(depute["pa"], depute["groupe"], depute["nom"])
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
            "assiduite": assiduite_par_pa.get(depute["pa"]),
        }

    # ---- Complétion croisée des scrutins partagés entre députés normands ----
    #
    # Chaque député n'apporte, via sa propre page "positions de vote", QUE
    # ses 10 votes les plus récents (VOTES_MAX_PAGES). Un même scrutin
    # (ex. n°7987 du 7 juillet 2026) peut donc apparaître dans l'historique
    # personnel d'un seul député normand — parce que d'autres votes plus
    # récents l'ont fait sortir de la fenêtre des 10 chez les autres — alors
    # qu'en réalité plusieurs députés normands y ont pris part. Résultat
    # remonté par la rédaction : le scrutin n°7987 n'affichait que le vote
    # d'Anna Pic dans "Résultats de vote".
    #
    # Pour chaque scrutin découvert (peu importe via quel député), on va
    # donc chercher sur la page du scrutin lui-même la liste nominative de
    # TOUS les votants, et on complète le dossier de chaque député normand
    # qui y figure mais dont ce scrutin n'était pas dans son propre top 10.
    print("\n→ Complétion croisée des scrutins partagés entre députés normands")
    scrutin_urls = sorted({
        v["url"]
        for depute in DEPUTES
        for v in output["deputes"][depute["pa"]]["votes"]
    })
    ajouts = 0
    for url in scrutin_urls:
        group_counts, votes_by_name = fetch_scrutin_detail(url)
        if not votes_by_name:
            continue
        ref = next(
            (v for depute in DEPUTES for v in output["deputes"][depute["pa"]]["votes"] if v["url"] == url),
            None,
        )
        for depute in DEPUTES:
            dvotes = output["deputes"][depute["pa"]]["votes"]
            if any(v["url"] == url for v in dvotes):
                continue  # déjà présent via son propre historique
            position = votes_by_name.get(normalize_name(depute["nom"]))
            if not position or position == "Non votant":
                continue
            groupe_majorite = majority_position(group_counts.get(depute["groupe"], {}))
            dvotes.append({
                "date": ref["date"] if ref else None,
                "objet": ref["objet"] if ref else None,
                "position": position,
                "resultat": ref["resultat"] if ref else None,
                "url": url,
                "conforme_groupe": (position == groupe_majorite) if groupe_majorite else None,
                "detail_groupe": group_counts.get(depute["groupe"]) or None,
            })
            ajouts += 1
            print(f"    + {depute['nom']} ajouté au scrutin {url} (absent de son historique perso)")
    print(f"    {ajouts} vote(s) complété(s) au total")

    with open("activite-data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("\n✓ Écrit dans activite-data.json")

    if inject_into_html(output):
        print(f"✓ {HTML_FILE} mis à jour avec les nouvelles données — "
              f"il suffit de l'ouvrir (ou de rafraîchir la page si déjà ouverte).")


def debug_scrutin(scrutin_url):
    """Diagnostic ciblé sur un seul scrutin, sans relancer tout le scraping.

    Usage : python3 fetch_activite_deputes.py --debug-scrutin <url>

    Affiche exactement ce que fetch_scrutin_detail() a réussi à extraire de
    la page du scrutin : le décompte par groupe (pour vérifier que la
    section "Votes des groupes" a bien été repérée) et, pour CHACUN des 28
    députés normands, s'il a été retrouvé nommément sur la page et avec
    quelle position. Sert à distinguer un vrai bug de parsing (0 groupe /
    0 député retrouvé du tout) d'un cas où le député n'a simplement pas
    pris part à ce scrutin précis."""
    print(f"→ Diagnostic du scrutin : {scrutin_url}\n")
    group_counts, votes_by_name = fetch_scrutin_detail(scrutin_url)

    print(f"Groupes politiques détectés : {len(group_counts)}")
    if not group_counts:
        print("  ! Aucun groupe détecté — la section \"Votes des groupes\" n'a "
              "probablement pas été repérée sur cette page (page indisponible, "
              "structure différente de celle attendue, ou scrutin sans détail "
              "public). C'est le signe d'un vrai bug de récupération, pas d'un "
              "simple cas de non-participation.")
    for groupe, counts in group_counts.items():
        print(f"  - {groupe} : {counts}")

    print(f"\nDéputés nommément retrouvés sur la page, tous groupes confondus : {len(votes_by_name)}")
    print("\nDétail pour les 28 députés normands :")
    for depute in DEPUTES:
        position = votes_by_name.get(normalize_name(depute["nom"]))
        marque = f"✓ {position}" if position else "✗ non retrouvé nommément sur la page"
        print(f"  {marque:<45} {depute['nom']} ({depute['circo']})")


def dump_scrutin_text(scrutin_url, context_lines=200):
    """Diagnostic brut : affiche le texte RÉEL de la page, ligne par ligne,
    à partir de la première ligne contenant "vote" (insensible à la casse
    et aux accents). Contrairement à fetch_scrutin_detail (qui suppose une
    structure précise), ceci n'interprète rien — sert à examiner la
    structure exacte de la page quand cette hypothèse de structure s'avère
    fausse (ex. "Groupes politiques détectés : 0"), pour corriger le motif
    de reconnaissance sur des données réelles plutôt que des suppositions.

    Usage : python3 fetch_activite_deputes.py --dump-scrutin <url>
    """
    try:
        soup = get(scrutin_url)
    except requests.RequestException as e:
        print(f"! Échec de récupération de la page : {e}", file=sys.stderr)
        return
    lines = [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]
    print(f"→ {len(lines)} lignes de texte non vides au total sur la page\n")
    start = next((i for i, l in enumerate(lines) if "vote" in normalize_name(l)), 0)
    end = min(len(lines), start + context_lines)
    print(f"--- Lignes {start} à {end - 1} (sur {len(lines)}) ---")
    for i in range(start, end):
        print(f"{i:4d}: {lines[i]!r}")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--debug-scrutin":
        debug_scrutin(sys.argv[2])
    elif len(sys.argv) >= 3 and sys.argv[1] == "--dump-scrutin":
        dump_scrutin_text(sys.argv[2])
    else:
        main()
