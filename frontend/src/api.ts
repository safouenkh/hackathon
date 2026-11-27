import type { DemandeEnvoyee, FormulairePage, Valeurs } from './types'

export class ErreurApi extends Error {
  constructor(public statut: number, public code: string, public champ: string | null = null) {
    super(code)
  }
}

async function lireErreur(r: Response): Promise<ErreurApi> {
  try {
    const corps = await r.json()
    const d = corps?.detail
    return new ErreurApi(r.status, typeof d?.code === 'string' ? d.code : 'inconnu', d?.champ ?? null)
  } catch {
    return new ErreurApi(r.status, 'inconnu')
  }
}

/** Les paramètres du lien (langue, lots, données du projet) sont transmis tels quels ; jamais de contact. */
export async function chargerFormulaire(parcours: string, params: URLSearchParams): Promise<FormulairePage> {
  const r = await fetch(`/api/formulaires/${encodeURIComponent(parcours)}?${params.toString()}`)
  if (!r.ok) throw await lireErreur(r)
  return r.json()
}

export interface Envoi {
  parcours: string
  langue: string
  lot_ids: number[]
  valeurs: Valeurs
  contact: Valeurs
  consentement: boolean
  consentement_version: string
  langue_aide: string | null
}

export async function envoyerDemande(envoi: Envoi): Promise<DemandeEnvoyee> {
  const r = await fetch('/api/demandes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(envoi),
  })
  if (!r.ok) throw await lireErreur(r)
  return r.json()
}
