import type { ChampPage } from './types'
import type { Textes } from './textes'

interface Props {
  champ: ChampPage
  valeur: string
  onChange: (code: string, valeur: string) => void
  t: Textes
}

const LONGUEUR = { texte: 200, texte_long: 2000, nombre: 30, montant: 30 } as Record<string, number>

function Libelle({ champ, t, pour }: { champ: ChampPage; t: Textes; pour?: string }) {
  const Balise = pour ? 'label' : 'span'
  return (
    <Balise className="libelle" {...(pour ? { htmlFor: pour } : {})}>
      <span className="officiel">{champ.libelle}</span>
      {champ.unite && <span className="unite"> ({champ.unite})</span>}
      {champ.aide && <span className="aide-officielle"> {champ.aide}</span>}
      {champ.traduction && (
        <span className="traduction">
          {champ.traduction}
          {champ.traduction_officielle === false && <em> — {t.traductionNonOfficielle}</em>}
        </span>
      )}
    </Balise>
  )
}

function Etiquette({ champ, t }: { champ: ChampPage; t: Textes }) {
  if (champ.impose) return <span className="etiquette fixe">{t.impose}</span>
  if (champ.categorie === 'contact') return <span className="etiquette contact">{t.saisieIci}</span>
  if (champ.origine_valeur) return <span className="etiquette prerempli">{t.prerempli}</span>
  return null
}

/** Un champ du formulaire officiel, à l'écran. CIN, passeport et signature n'ont jamais de zone de saisie. */
export function Champ({ champ, valeur, onChange, t }: Props) {
  const id = `champ-${champ.code}`
  if (champ.categorie === 'non_enregistre') {
    return (
      <div className="champ main">
        <Libelle champ={champ} t={t} />
        <span className="note-main">{t.nonEnregistre}</span>
      </div>
    )
  }
  if (champ.categorie === 'reserve_afi') {
    return (
      <div className="champ reserve">
        <Libelle champ={champ} t={t} />
        <span className="note-main">{t.reserveAfi}</span>
      </div>
    )
  }

  const modifier = (v: string) => onChange(champ.code, v)
  let saisie
  if (champ.choix && champ.type === 'choix_unique') {
    saisie = (
      <div className="choix" role="radiogroup" aria-labelledby={`${id}-l`}>
        {champ.choix.map((c) => (
          <label key={c.valeur} className="option">
            <input type="radio" name={id} value={c.valeur} checked={valeur === c.valeur}
                   disabled={champ.impose} onChange={() => modifier(c.valeur)} />
            <span>{c.libelle ?? c.valeur}</span>
            {c.traduction && <span className="traduction"> {c.traduction}</span>}
          </label>
        ))}
      </div>
    )
    return (
      <div className="champ">
        <span id={`${id}-l`}><Libelle champ={champ} t={t} /></span>
        <Etiquette champ={champ} t={t} />
        {saisie}
      </div>
    )
  }
  if (champ.choix && champ.type === 'choix_multiple') {
    const choisis = new Set(valeur ? valeur.split(',') : [])
    const basculer = (v: string) => {
      choisis.has(v) ? choisis.delete(v) : choisis.add(v)
      modifier([...choisis].join(','))
    }
    return (
      <fieldset className="champ">
        <legend><Libelle champ={champ} t={t} /></legend>
        {champ.choix.map((c) => (
          <label key={c.valeur} className="option">
            <input type="checkbox" checked={choisis.has(c.valeur)} disabled={champ.impose}
                   onChange={() => basculer(c.valeur)} />
            <span>{c.libelle ?? c.valeur}</span>
          </label>
        ))}
      </fieldset>
    )
  }
  if (champ.type === 'texte_long') {
    saisie = <textarea id={id} value={valeur} maxLength={LONGUEUR.texte_long} rows={3}
                       readOnly={champ.impose} onChange={(e) => modifier(e.target.value)} />
  } else {
    const nombre = champ.type === 'nombre' || champ.type === 'montant'
    saisie = (
      <input id={id} type={champ.type === 'date' ? 'date' : 'text'} value={valeur}
             inputMode={nombre ? 'decimal' : undefined} maxLength={LONGUEUR[champ.type] ?? 200}
             autoComplete={champ.categorie === 'contact' ? 'on' : 'off'} readOnly={champ.impose}
             onChange={(e) => modifier(e.target.value)} />
    )
  }
  return (
    <div className="champ">
      <Libelle champ={champ} t={t} pour={id} />
      <Etiquette champ={champ} t={t} />
      {saisie}
    </div>
  )
}
