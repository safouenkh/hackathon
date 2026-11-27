"""Client du service « langues et voix » (Dalila_Language, rôle 4), appelé par HTTP.

Le service tourne à part (son propre environnement Python, port 7860 par défaut ; voir README) :
- détection de la langue et de l'écriture (8 langues, arabizi) : POST /understand ;
- reconnaissance vocale (Whisper, dont un modèle affiné pour le tunisien) : POST /transcribe ;
- synthèse vocale (Piper ; voix tunisienne OmniVoice si activée) : POST /speak.
Tout reste local : l'audio et le texte ne partent vers aucun service externe (BNF9).
Une panne du service ne bloque jamais la réponse écrite (BNF4) : les fonctions lèvent
ServiceLangueIndisponible, que l'API transforme en message court.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from app.config import get_settings

# Langues sans voix dédiée dans le service : lues avec une voix arabe générique, en le signalant (BF8).
DIALECTES_ARABES = {"aeb", "arq", "ayl"}
_BALISE = re.compile(r"\[\[(ZONE|LOT|CHOIX|PDF):([^\]]*)\]\]")
TAILLE_AUDIO_MAX = 20 * 1024 * 1024          # même borne que le service


class ServiceLangueIndisponible(RuntimeError):
    """Service non configuré, injoignable, en erreur ou trop lent."""


@dataclass(frozen=True)
class Langue:
    code: str                  # aeb, ar, arq, ayl, fr, en, de, tr
    ecriture: str | None       # arabic, latin, mixed…
    style: str | None          # ex. « arabizi »


def _url(chemin: str) -> str:
    base = get_settings().langue_url.rstrip("/")
    if not base:
        raise ServiceLangueIndisponible("LANGUE_URL vide : service de langue et de voix non configuré")
    return base + chemin


def _post(chemin: str, **kwargs) -> dict:
    try:
        r = httpx.post(_url(chemin), timeout=get_settings().langue_timeout_seconds, **kwargs)
    except httpx.HTTPError as exc:
        raise ServiceLangueIndisponible(type(exc).__name__) from exc
    if r.status_code != 200:
        raise ServiceLangueIndisponible(f"HTTP {r.status_code}")
    return r.json()


def etat() -> dict:
    """Disponibilité réelle des modèles (reconnaissance, voix par langue, voix tunisienne)."""
    try:
        r = httpx.get(_url("/capabilities"), timeout=5.0)
        r.raise_for_status()
    except (httpx.HTTPError, ServiceLangueIndisponible) as exc:
        return {"disponible": False, "raison": str(exc) or type(exc).__name__}
    c = r.json()
    return {"disponible": True, "version": c.get("version"), "reconnaissance": c.get("general_asr"),
            "prechauffage": c.get("asr_warmup"), "voix": c.get("neural_tts"), "voix_tunisienne": c.get("tunisian_tts"),
            "voix_de_secours": c.get("packaged_tts")}


def detecter(texte: str) -> Langue:
    """Langue et écriture d'un texte (aucune réponse du service n'est utilisée, seulement l'analyse)."""
    d = _post("/understand", json={"text": texte[:4000], "language": "auto", "history": [], "backend": "baseline",
                                    "style": "auto"})
    code = d.get("language") or "fr"
    # Mesure du 2026-11-27 : 7 phrases sur 12 en arabe standard ou en tunisien (lettres arabes) étaient
    # classées « fr ». Un texte en lettres arabes n'est jamais lu avec une voix latine : arabe par défaut.
    if code in LANGUES_LATINES and _part_arabe(texte) >= 0.5:
        code = "ar"
    return Langue(code=code, ecriture=d.get("script"), style=d.get("response_style"))


LANGUES_LATINES = {"fr", "en", "de", "tr"}
NOMS = {"aeb": "tunisien", "ar": "arabe standard", "arq": "algérien", "ayl": "libyen", "fr": "français",
        "en": "anglais", "de": "allemand", "tr": "turc"}
# Arabizi : chiffres utilisés comme lettres dans un mot (n7eb, 3andi, 9addech, a5tar)
_ARABIZI = re.compile(r"(?i)\b[a-z]+[235789][a-z]+\b|\b[235789][a-z]{2,}\b")   # pas « m2 » ni « 3000 »
_LETTRES = {"tr": " avec les lettres turques (ç, ğ, ı, İ, ö, ş, ü)", "de": " avec ä, ö, ü et ß"}


def consigne_langue(texte: str, service: bool = True) -> tuple[str, str]:
    """(code, consigne) pour que la réponse suive la langue ET l'écriture du message (BF3).

    Écriture mesurée ici (lettres arabes / latines, chiffres de l'arabizi) ; langue donnée par le service
    Dalila_Language quand il répond, sinon déduite de l'écriture seule.
    """
    arabe = _part_arabe(texte) >= 0.5
    arabizi = not arabe and len(_ARABIZI.findall(texte)) >= 1
    code = None
    if service:
        try:
            code = detecter(texte).code
        except ServiceLangueIndisponible:
            code = None
    if arabe and code not in DIALECTES_ARABES | {"ar"}:
        code = "ar"
    if arabizi:
        code = code if code in DIALECTES_ARABES else "aeb"
    code = code or ("ar" if arabe else "fr")
    if arabizi:
        ecrit = f"{NOMS[code]} en arabizi (lettres latines et chiffres 3, 7, 9, 5, 2) : réponds en arabizi {NOMS[code]}"
    elif arabe:
        ecrit = (f"{NOMS[code]} en lettres arabes : réponds en {NOMS[code]} avec des lettres arabes, jamais en "
                 "arabizi ni en français")
    else:
        ecrit = f"{NOMS[code]} : rédige toute la réponse en {NOMS[code]}{_LETTRES.get(code, '')}"
    return code, (f"[Langue du message de l'utilisateur : {ecrit}. Seuls les noms propres et les balises [[...]] "
                  "restent tels quels ; pas de lien ni de code interne dans la réponse.]")


def _part_arabe(texte: str) -> float:
    lettres = [c for c in texte if c.isalpha()]
    return sum("؀" <= c <= "ۿ" for c in lettres) / len(lettres) if lettres else 0.0


def transcrire(audio: bytes, type_media: str, langue: str = "auto") -> dict:
    """Texte reconnu (BF7). L'audio n'est jamais gardé : ni ici, ni par le service (fichier temporaire)."""
    if not audio:
        raise ValueError("audio vide")
    if len(audio) > TAILLE_AUDIO_MAX:
        raise ValueError("audio trop long (20 Mo au plus)")
    d = _post("/transcribe", files={"file": ("audio", audio, type_media or "application/octet-stream")},
              data={"language": langue, "model": "auto"})
    return {"texte": (d.get("text") or "").strip(), "langue": d.get("language_hint") or d.get("asr_language"),
            "modele": d.get("model"), "duree_s": d.get("total_s"), "modele_de_secours": bool(d.get("fallback"))}


# Unités prononcées dans la langue de lecture (BF8 : chiffres prononcés correctement).
_UNITES = {
    "fr": {"dt_m2": "dinars le mètre carré", "mdt": "millions de dinars", "dt": "dinars", "m2": "mètres carrés",
           "km": "kilomètres", "pct": "pour cent"},
    "en": {"dt_m2": "dinars per square metre", "mdt": "million dinars", "dt": "dinars", "m2": "square metres",
           "km": "kilometres", "pct": "percent"},
    "de": {"dt_m2": "Dinar pro Quadratmeter", "mdt": "Millionen Dinar", "dt": "Dinar", "m2": "Quadratmeter",
           "km": "Kilometer", "pct": "Prozent"},
    "tr": {"dt_m2": "dinar metrekare başına", "mdt": "milyon dinar", "dt": "dinar", "m2": "metrekare",
           "km": "kilometre", "pct": None},
    "ar": {"dt_m2": "دينار للمتر المربع", "mdt": "مليون دينار", "dt": "دينار", "m2": "متر مربع",
           "km": "كيلومتر", "pct": "بالمائة"},
}
_NOMBRE = r"(\d[\d\s.,]*\d|\d)"


def _unites(t: str, code: str) -> str:
    u = _UNITES.get("ar" if code in DIALECTES_ARABES else code, _UNITES["fr"])
    t = re.sub(r"(?i)\b(?:dt|dinars?)\s*/\s*m(?:²|2)\b", u["dt_m2"], t)
    t = re.sub(r"(?i)(?<=\d)\s*MDT\b", " " + u["mdt"], t)
    t = re.sub(r"(?i)(?<=\d)\s*(?:DT|TND)\b", " " + u["dt"], t)
    t = re.sub(r"(?i)\b(mille|millions?|milliards?|alf|ألف|مليون)(\s+(?:de\s+)?)(?:DT|TND)\b", r"\1\2" + u["dt"], t)
    t = re.sub(r"(?<=\d)\s*m(?:²|2)\b", " " + u["m2"], t)
    t = re.sub(r"(?<=\d)\s*km\b", " " + u["km"], t)
    if u["pct"]:
        t = re.sub(r"(?<=\d)\s*%", " " + u["pct"], t)
    else:                                         # turc : « %20 » ou « 20 % » -> « yüzde 20 »
        t = re.sub(r"%\s*" + _NOMBRE, r"yüzde \1", t)
        t = re.sub(_NOMBRE + r"\s*%", r"yüzde \1", t)
    return t


def texte_a_lire(reponse: str, langue: str | None = None) -> str:
    """Texte prononçable : balises -> libellés ([[LOT:12:Lot 7]] -> « Lot 7 »), sans liens, adresses, codes
    internes ni mise en forme ; avec `langue`, unités en toutes lettres et gloses latines retirées de l'arabe."""
    def libelle(m: re.Match) -> str:
        type_, contenu = m.group(1), m.group(2)
        if type_ == "PDF":
            return contenu.rsplit(":", 1)[-1] if ":" in contenu else ""
        if type_ == "CHOIX":
            return contenu
        return contenu.split(":", 1)[1] if ":" in contenu else contenu
    t = _BALISE.sub(libelle, reponse or "")
    t = re.sub(r"\[([^\]]+)\]\((?:https?://|/)[^)]*\)", r"\1", t)    # [texte](lien) -> texte
    t = re.sub(r"(?:https?://|www\.)\S+", "", t)                      # les liens se lisent à l'écran
    t = re.sub(r"\b\w+_\w+\b", "", t)                                  # codes internes (regime_ancien…)
    t = re.sub(r"[*#`|>_]+", " ", t)
    if langue in DIALECTES_ARABES | {"ar"}:
        t = re.sub(r"\(\s*[^()؀-ۿ]*[A-Za-z][^()؀-ۿ]*\)", "", t)  # gloses en français
        t = re.sub(r"«[^»؀-ۿ]*[A-Za-z][^»؀-ۿ]*»", "", t)        # citations en français
    if langue:
        t = _unites(t, langue)
    t = re.sub(r"\(\s*[\s.,;:«»\"']*\)", "", t)                       # parenthèses vidées
    t = re.sub(r"\s+([.,;:!?،؟)])", r"\1", t)
    t = re.sub(r"[:;,،]\s*([.!?؟])", r"\1", t)                         # « : . » laissé par une citation retirée
    return re.sub(r"\s+", " ", t).strip()


def lire(texte: str, langue: str | None = None) -> dict:
    """Audio WAV (base64) de la réponse, dans la langue du visiteur (BF8)."""
    brut = texte_a_lire(texte)
    if not brut:
        raise ValueError("rien à lire")
    code = langue or detecter(brut).code
    a_lire = texte_a_lire(texte, code)[:TEXTE_LU_MAX]
    morceaux = [_post("/speak", json={"text": m, "language": code}) for m in _morceaux(a_lire)]
    d = morceaux[0]
    # dialect_authentic : le service dit lui-même si la voix est propre au dialecte (OmniVoice « aeb »)
    generique = code in DIALECTES_ARABES and not all(m.get("dialect_authentic") for m in morceaux)
    return {"audio_base64": _assembler_wav([m["audio_base64"] for m in morceaux]), "texte_lu": a_lire,
            "langue": code, "moteur": d.get("engine"), "voix": d.get("voice"),
            "duree_generation_s": round(sum(m.get("generation_s") or 0 for m in morceaux), 2),
            "voix_arabe_generique": generique}


TEXTE_LU_MAX = 4000
MORCEAU_MAX = 1100          # le service refuse plus de 1200 caractères par synthèse (engines.speak)


def _morceaux(texte: str, taille: int = MORCEAU_MAX) -> list[str]:
    """Morceaux de phrases complètes, chacun sous la limite du service."""
    phrases = re.split(r"(?<=[.!?؟;])\s+", texte)
    res, courant = [], ""
    for p in phrases:
        while len(p) > taille:                    # phrase très longue : coupée à un espace
            coupe = p.rfind(" ", 0, taille)
            coupe = coupe if coupe > taille // 2 else taille
            if courant:
                res.append(courant); courant = ""
            res.append(p[:coupe].strip()); p = p[coupe:].strip()
        if courant and len(courant) + 1 + len(p) > taille:
            res.append(courant); courant = p
        else:
            courant = f"{courant} {p}".strip()
    if courant:
        res.append(courant)
    return [m for m in res if m]


def _assembler_wav(parties_b64: list[str]) -> str:
    """Un seul WAV à partir de plusieurs (même voix, donc même format)."""
    import base64
    import io
    import wave

    if len(parties_b64) == 1:
        return parties_b64[0]
    sortie = io.BytesIO()
    with wave.open(sortie, "wb") as w:
        for i, b in enumerate(parties_b64):
            with wave.open(io.BytesIO(base64.b64decode(b)), "rb") as r:
                if i == 0:
                    w.setparams(r.getparams())
                w.writeframes(r.readframes(r.getnframes()))
    return base64.b64encode(sortie.getvalue()).decode()
