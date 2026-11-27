import type { FormulairePage, MentionPage, Valeurs } from './types'
import { sens } from './textes'

/** Mention affichée si elle est générale, ou si elle concerne le choix fait (ex. pièces du document n° 3). */
export function mentionVisible(m: MentionPage, valeurs: Valeurs): boolean {
  return !m.si_champ || (valeurs[m.si_champ] ?? '').split(',').includes(m.si_valeur ?? '')
}

/**
 * Version imprimable : reprend le formulaire officiel (titres, libellés, mentions) dans sa langue.
 * Les champs vides, la CIN, le passeport, la signature et les cases de l'AFI restent des lignes à remplir
 * à la main. Rien n'est envoyé : l'impression se fait dans le navigateur.
 */
export function Impression({ page, valeurs }: { page: FormulairePage; valeurs: Valeurs }) {
  return (
    <article className="impression" lang={page.langue} dir={sens(page.langue)} aria-hidden="true">
      <h1>{page.titre_officiel}</h1>
      {page.sections.map((s) => (
        <section key={s.code}>
          {s.libelle && <h2>{s.libelle}</h2>}
          {s.champs.map((ch) => {
            const v = ch.categorie === 'projet' || ch.categorie === 'contact' ? valeurs[ch.code] ?? '' : ''
            return (
              <div className="ligne" key={ch.code}>
                <span className="lib">
                  {ch.libelle}
                  {ch.unite ? ` (${ch.unite})` : ''}
                  {ch.aide ? ` ${ch.aide}` : ''} :
                </span>
                {ch.choix ? (
                  <span className="cases">
                    {ch.choix.map((c) => (
                      <span key={c.valeur} className="case">
                        {v.split(',').includes(c.valeur) ? '☒' : '☐'} {c.libelle ?? c.valeur}
                      </span>
                    ))}
                  </span>
                ) : (
                  <span className={v ? 'val' : 'pointilles'}>{v}</span>
                )}
              </div>
            )
          })}
          {s.mentions.filter((m) => mentionVisible(m, valeurs)).map((m, i) => (
            <p className="mention" key={i}>{m.texte}</p>
          ))}
        </section>
      ))}
    </article>
  )
}
