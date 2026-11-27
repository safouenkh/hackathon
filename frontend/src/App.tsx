import { useEffect, useMemo, useState } from 'react'
import { chargerFormulaire, envoyerDemande, ErreurApi } from './api'
import { Champ } from './Champ'
import { Impression, mentionVisible } from './Impression'
import { langueInterface, sens, textes, type Textes } from './textes'
import type { Avertissement, ChampPage, DemandeEnvoyee, FormulairePage, Valeurs } from './types'

type Etape = 'remplir' | 'relire' | 'envoye'
// Avertissements utiles sur cette page (les prix ne figurent pas sur le formulaire).
const AVERTISSEMENTS_PAGE = new Set(['point_a_verifier', 'lot_non_disponible', 'lot_introuvable', 'donnee_non_fraiche',
  'valeur_non_preremplie', 'gouvernorat_non_reconnu', 'lot_orphelin', 'statut_inconnu'])

export default function App() {
  const params = useMemo(() => new URLSearchParams(window.location.search), [])
  const ui = langueInterface(params)
  const t = textes(ui)
  const chemin = window.location.pathname.match(/^\/formulaire\/([a-z][a-z0-9_-]*)\/?$/)
  return (
    <div className="app" lang={ui} dir={sens(ui)}>
      <header className="entete">
        <span className="marque">Dalila · AFI</span>
      </header>
      {chemin ? <PageFormulaire parcours={chemin[1]} params={params} ui={ui} t={t} />
              : <p className="message">{t.pasDeParcours}</p>}
    </div>
  )
}

function champs(page: FormulairePage): ChampPage[] {
  return page.sections.flatMap((s) => s.champs)
}

function PageFormulaire({ parcours, params, ui, t }: { parcours: string; params: URLSearchParams; ui: string; t: Textes }) {
  const [page, setPage] = useState<FormulairePage | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [langue, setLangue] = useState<string | null>(params.get('langue'))
  const [valeurs, setValeurs] = useState<Valeurs>({})
  const [etape, setEtape] = useState<Etape>('remplir')

  useEffect(() => {
    const p = new URLSearchParams(params)
    p.set('aide', ui)
    if (langue) p.set('langue', langue)
    else p.delete('langue')
    let actif = true
    setErreur(null)
    chargerFormulaire(parcours, p)
      .then((pg) => {
        if (!actif) return
        setPage(pg)
        // Les valeurs déjà saisies sont gardées ; le préremplissage complète seulement les champs vides.
        setValeurs((avant) => {
          const v = { ...avant }
          for (const ch of champs(pg)) if (ch.valeur && (ch.impose || !v[ch.code])) v[ch.code] = ch.valeur
          return v
        })
      })
      .catch((e) => actif && setErreur(e instanceof ErreurApi && e.statut === 404 ? t.introuvable : t.erreurChargement))
    return () => { actif = false }
  }, [parcours, params, ui, langue, t])

  if (erreur) return <p className="message erreur" role="alert">{erreur}</p>
  if (!page) return <p className="message" aria-live="polite">{t.chargement}</p>

  const changer = (code: string, v: string) => setValeurs((avant) => ({ ...avant, [code]: v }))
  const changerLangue = (l: string) => {
    const url = new URL(window.location.href)
    url.searchParams.set('langue', l)
    window.history.replaceState(null, '', url)
    setLangue(l)
  }

  return (
    <main className="page">
      <p className="bandeau" role="note">{t.bandeau}</p>
      <ol className="etapes" aria-label="étapes">
        {t.etapes.map((e, i) => (
          <li key={e} aria-current={['remplir', 'relire', 'envoye'][i] === etape ? 'step' : undefined}>{e}</li>
        ))}
      </ol>
      <div className="titre" lang={page.langue} dir={sens(page.langue)}>
        <h1>{page.titre_officiel}</h1>
        <p className="sous-titre">{page.parcours_titre}</p>
      </div>
      <Liens page={page} t={t} />
      <Avertissements page={page} t={t} />
      {page.langues.length > 1 && etape === 'remplir' && (
        <div className="langues" role="group" aria-label={t.langueFormulaire}>
          <span>{t.langueFormulaire} :</span>
          {page.langues.map((l) => (
            <button key={l} type="button" className={l === page.langue ? 'actif' : ''} aria-pressed={l === page.langue}
                    onClick={() => changerLangue(l)}>{l === 'ar' ? 'العربية' : l === 'fr' ? 'Français' : l}</button>
          ))}
        </div>
      )}
      {etape === 'remplir' && <Remplir page={page} valeurs={valeurs} changer={changer} t={t}
                                        suivant={() => { setEtape('relire'); window.scrollTo(0, 0) }} />}
      {etape !== 'remplir' && <Relire page={page} valeurs={valeurs} t={t} ui={ui}
                                      retour={() => setEtape('remplir')} envoye={() => setEtape('envoye')} />}
      <Impression page={page} valeurs={valeurs} />
    </main>
  )
}

function Liens({ page, t }: { page: FormulairePage; t: Textes }) {
  return (
    <p className="liens">
      {page.url_source && <a href={page.url_source} target="_blank" rel="noopener noreferrer">{t.sourceService}</a>}
      {page.url_fichier && <a href={page.url_fichier} target="_blank" rel="noopener noreferrer">{t.pdfVierge}</a>}
    </p>
  )
}

function Avertissements({ page, t }: { page: FormulairePage; t: Textes }) {
  const libelles = Object.fromEntries(champs(page).map((c) => [c.code, c.traduction ?? c.libelle]))
  const vus = new Set<string>()
  const lignes = page.avertissements.filter((a: Avertissement) => AVERTISSEMENTS_PAGE.has(a.code)).flatMap((a) => {
    const lot = a.lot_id ? page.lots.find((l) => l.lot_id === a.lot_id) : undefined
    const quoi = lot ? ` — lot ${lot.numero ?? lot.lot_id}${lot.zone_nom ? `, ${lot.zone_nom}` : ''}` : ''
    const detail = a.code === 'valeur_non_preremplie' ? ` : ${libelles[a.detail ?? ''] ?? a.detail}`
      : a.code === 'point_a_verifier' && a.detail ? ` : ${a.detail}` : ''
    const texte = `${t.avert[a.code] ?? a.code}${quoi}${detail}`
    if (vus.has(texte)) return []
    vus.add(texte)
    return [texte]
  })
  if (!lignes.length) return null
  return (
    <aside className="avertissements" aria-label={t.avertissements}>
      <h2>{t.avertissements}</h2>
      <ul>{lignes.map((l) => <li key={l}>{l}</li>)}</ul>
    </aside>
  )
}

function Remplir({ page, valeurs, changer, suivant, t }: {
  page: FormulairePage; valeurs: Valeurs; changer: (c: string, v: string) => void; suivant: () => void; t: Textes
}) {
  return (
    <form className="formulaire" lang={page.langue} dir={sens(page.langue)}
          onSubmit={(e) => { e.preventDefault(); suivant() }}>
      {page.sections.map((s) => (
        <section key={s.code} className={`section ${s.champs.every((c) => c.categorie === 'reserve_afi') ? 'reserve' : ''}`}>
          {(s.libelle || s.traduction) && (
            <h2>{s.libelle}{s.traduction && <span className="traduction">{s.traduction}</span>}</h2>
          )}
          {s.champs.map((ch) => (
            <Champ key={ch.code} champ={ch} valeur={valeurs[ch.code] ?? ''} onChange={changer} t={t} />
          ))}
          {s.mentions.filter((m) => mentionVisible(m, valeurs)).map((m, i) => (
            <p key={i} className="mention">{m.texte}</p>
          ))}
        </section>
      ))}
      <div className="actions">
        <button type="submit" className="principal">{t.relire}</button>
      </div>
    </form>
  )
}

function Relire({ page, valeurs, retour, envoye, t, ui }: {
  page: FormulairePage; valeurs: Valeurs; retour: () => void; envoye: () => void; t: Textes; ui: string
}) {
  const [accord, setAccord] = useState(false)
  const [envoi, setEnvoi] = useState<'non' | 'encours'>('non')
  const [resultat, setResultat] = useState<DemandeEnvoyee | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const tous = champs(page)
  const garder = (cat: string) => Object.fromEntries(tous
    .filter((c) => c.categorie === cat && (valeurs[c.code] ?? '').trim())
    .map((c) => [c.code, valeurs[c.code].trim()]))
  const projet = garder('projet')
  const contact = garder('contact')
  const libelle = (c: ChampPage, v: string) => c.choix?.find((x) => x.valeur === v)?.libelle ?? v

  const envoyer = async () => {
    setEnvoi('encours')
    setErreur(null)
    try {
      const r = await envoyerDemande({
        parcours: page.parcours, langue: page.langue, lot_ids: page.lots.map((l) => l.lot_id), valeurs: projet,
        contact, consentement: accord, consentement_version: page.consentement.version, langue_aide: ui,
      })
      setResultat(r)
      envoye()
    } catch (e) {
      setErreur(t.erreurs[e instanceof ErreurApi ? e.code : 'inconnu'] ?? t.erreurs.inconnu)
      setEnvoi('non')
    }
  }

  if (resultat) {
    return (
      <section className="envoye" role="status">
        <h2>{t.envoyeTitre}</h2>
        <p className="reference">{t.reference} : <strong dir="ltr">{resultat.reference}</strong></p>
        <p>{t.rappelDepot}</p>
        <button type="button" onClick={() => window.print()}>{t.imprimer}</button>
        <p className="aide">{t.imprimerAide}</p>
      </section>
    )
  }

  const bloc = (titre: string, cat: string) => (
    <section className="recap">
      <h2>{titre}</h2>
      <dl lang={page.langue} dir={sens(page.langue)}>
        {tous.filter((c) => c.categorie === cat).map((c) => (
          <div key={c.code} className={valeurs[c.code]?.trim() ? '' : 'vide'}>
            <dt>{c.libelle}</dt>
            <dd>{valeurs[c.code]?.trim() ? libelle(c, valeurs[c.code].trim()) : t.vide}</dd>
          </div>
        ))}
      </dl>
    </section>
  )

  return (
    <div className="relecture">
      {bloc(t.projet, 'projet')}
      {bloc(t.contact, 'contact')}
      <div className="actions">
        <button type="button" onClick={retour}>{t.modifier}</button>
        <button type="button" onClick={() => window.print()}>{t.imprimer}</button>
      </div>
      <p className="aide">{t.imprimerAide}</p>
      <div className="accord">
        <label>
          <input type="checkbox" checked={accord} onChange={(e) => setAccord(e.target.checked)} />
          <span>{page.consentement.texte}</span>
        </label>
      </div>
      {!Object.keys(contact).length && <p className="aide">{t.aucunContact}</p>}
      {erreur && <p className="erreur" role="alert">{erreur}</p>}
      <div className="actions">
        <button type="button" className="principal" onClick={envoyer}
                disabled={!accord || !Object.keys(contact).length || envoi === 'encours'}>
          {envoi === 'encours' ? t.envoiEnCours : t.envoyer}
        </button>
      </div>
    </div>
  )
}
