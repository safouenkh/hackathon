"""Découpage des pages des organismes en passages (app.sources.organismes.decouper)."""
from app.sources.organismes import MIN_PASSAGE, decouper


def test_reste_minuscule_garde_avec_le_texte_precedent():
    # Cas réel : un extrait de 1501 caractères donnait un passage « . » à part.
    texte = "x" * 1500 + "."
    passages = decouper(texte, taille=1500)
    assert [p["texte"] for p in passages] == [texte]


def test_long_paragraphe_coupe_entre_deux_phrases():
    phrase = "Une phrase complète de la source. "
    texte = (phrase * 100).strip()
    passages = decouper(texte, taille=500)
    assert len(passages) > 1
    assert all(len(p["texte"]) >= MIN_PASSAGE for p in passages)
    assert all(p["texte"].endswith(".") for p in passages)
    assert " ".join(p["texte"] for p in passages) == texte


def test_petit_bloc_final_reste_dans_le_passage():
    texte = "a" * 1490 + "\n\n" + "motifs)"
    passages = decouper(texte, taille=1500)
    assert len(passages) == 1
    assert passages[0]["texte"].endswith("motifs)")


def test_titres_et_pages_conserves():
    texte = "<!-- page 3 -->\n\n# Primes\n\nPrime de 15 %.\n\n## Conditions\n\nFonds propres de 30 %."
    passages = decouper(texte)
    assert [p["section"] for p in passages] == [["Primes"], ["Primes", "Conditions"]]
    assert passages[0]["page_from"] == 3
