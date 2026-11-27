"""Masquage des données personnelles avant l'envoi au LLM (BNF9) : cas réels de l'essai du 27/11/2026."""
import pytest

from app.processing.confidentialite import masquer


@pytest.mark.parametrize("texte, attendu, types", [
    ("esmi Ahmed Test, CIN 01234567, tel 99 000 000, 7adherli el talab mta3 acquisition",
     "esmi [nom masqué], CIN [n° d'identité masqué], tel [téléphone masqué], 7adherli el talab mta3 acquisition",
     ("identite", "telephone", "nom")),
    ("ma CIN est 12345678 et mon mail ahmed.test@gmail.com",
     "ma CIN est [n° d'identité masqué] et mon mail [e-mail masqué]", ("email", "identite")),
    ("appelez moi au +216 71 124 260", "appelez moi au [téléphone masqué]", ("telephone",)),
    ("mon numéro 20123456", "mon numéro [téléphone masqué]", ("telephone",)),
    ("je m'appelle Ahmed Ben Ali et je cherche un lot", "je m'appelle [nom masqué] et je cherche un lot", ("nom",)),
    ("esmi ahmed w nheb lot", "esmi [nom masqué] w nheb lot", ("nom",)),
    ("اسمي أحمد بن علي ورقم بطاقة التعريف 01234567", "اسمي [nom masqué] ورقم بطاقة التعريف [n° d'identité masqué]",
     ("identite", "nom")),
    ("passeport N1234567 svp", "passeport [n° d'identité masqué] svp", ("identite",)),
])
def test_donnees_personnelles_masquees(texte, attendu, types):
    m = masquer(texte)
    assert m.texte == attendu and set(m.types) == set(types) and m.modifie


@pytest.mark.parametrize("texte", [
    "budget 20 000 000 DT", "budget 30000000", "investissement 12 000 000", "3000 m2 w budget 300 alf dinar",
    "nheb lot 7079 fel zone 932119", "lot 9302051", "218 540 DT", "je suis industriel textile", "esmi",
    "nheb 3 jours passeport", "Donnees du 13/11/2026",
])
def test_une_question_normale_n_est_pas_modifiee(texte):
    m = masquer(texte)
    assert m.texte == texte and not m.modifie and m.types == ()


def test_une_marque_n_est_jamais_relue_comme_une_donnee():
    """La marque « n° d'identité masqué » contient le mot « identité » : elle ne doit pas faire masquer ce qui suit."""
    m = masquer("CIN 01234567, tel 99 000 000")
    assert m.texte == "CIN [n° d'identité masqué], tel [téléphone masqué]"
