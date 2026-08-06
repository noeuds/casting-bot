"""
Vérifie les nouveaux posts sur des pages Facebook publiques
et envoie une notification Telegram pour chaque nouveau post.

Conçu pour tourner via GitHub Actions (cron toutes les 15 min).
L'état (derniers posts vus) est stocké dans state/last_posts.json,
committé automatiquement par le workflow après chaque exécution.
"""

import os
import json
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# --- Configuration -----------------------------------------------------

PAGES = {
    "CastingQuarters": "https://mbasic.facebook.com/CastingQuarters",
    "MFK - Les filles du Casting": "https://mbasic.facebook.com/profile.php?id=61577135076908",
}

STATE_FILE = Path("state/last_posts.json")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

MAX_POSTS_PER_CHECK = 5

# --- Fonctions -----------------------------------------------------------

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def send_telegram_message(text: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": False,
    }
    resp = requests.post(url, data=payload, timeout=15)
    if not resp.ok:
        print(f"⚠️ Échec envoi Telegram: {resp.status_code} {resp.text}", file=sys.stderr)


def fetch_latest_posts(page_name: str, url: str, limit: int = MAX_POSTS_PER_CHECK):
    """
    Récupère les derniers posts visibles sur la version mbasic
    (mobile allégée) d'une page Facebook publique.

    Retourne une liste de dicts: {"id": str, "text": str, "link": str}
    Retourne [] en cas d'échec (page bloquée, structure changée, etc.)
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"⚠️ Erreur réseau pour {page_name}: {exc}", file=sys.stderr)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    posts = []

    # Structure mbasic.facebook.com : chaque post est dans un <article>.
    # Cette structure peut changer côté Facebook sans préavis.
    for article in soup.find_all("article")[:limit]:
        link_tag = article.find(
            "a", href=re.compile(r"/story\.php|/permalink\.php|/posts/")
        )
        if not link_tag:
            continue

        href = link_tag.get("href", "")
        id_match = re.search(r"(story_fbid|id)=(\d+)", href)
        post_id = id_match.group(2) if id_match else href

        text = article.get_text(separator=" ", strip=True)
        full_link = "https://www.facebook.com" + href.split("&refid")[0]

        posts.append({"id": post_id, "text": text[:500], "link": full_link})

    if not posts:
        print(
            f"ℹ️ Aucun post détecté pour {page_name} — "
            f"la page a peut-être changé de structure ou bloque l'accès."
        )

    return posts


def main() -> None:
    state = load_state()
    any_new = False

    for page_name, url in PAGES.items():
        posts = fetch_latest_posts(page_name, url)
        if not posts:
            continue

        seen_ids = set(state.get(page_name, []))

        # Premier passage sur cette page : on enregistre l'état
        # sans notifier, pour éviter un déluge de vieux posts.
        if page_name not in state:
            state[page_name] = [p["id"] for p in posts]
            print(f"ℹ️ Initialisation de l'état pour {page_name} (pas de notification).")
            continue

        new_posts = [p for p in posts if p["id"] not in seen_ids]

        for post in reversed(new_posts):  # du plus ancien au plus récent
            message = f"🎬 Nouveau post — {page_name}\n\n{post['text']}\n\n{post['link']}"
            send_telegram_message(message)
            any_new = True

        state[page_name] = [p["id"] for p in posts]

    save_state(state)
    print("✅ Notifications envoyées." if any_new else "ℹ️ Rien de nouveau cette fois.")


if __name__ == "__main__":
    main()
