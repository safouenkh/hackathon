// Contrat de l'API /api (backend/app/processing/schemas.py : FormulairePage, EnvoiDemande, DemandeEnvoyee).

export type Categorie = 'projet' | 'contact' | 'non_enregistre' | 'reserve_afi'

export interface ChoixPage {
  valeur: string
  libelle: string | null
  traduction: string | null
}

export interface ChampPage {
  code: string
  type: string
  categorie: Categorie
  unite: string | null
  obligatoire: boolean | null
  libelle: string
  aide: string | null
  traduction: string | null
  traduction_officielle: boolean | null
  choix: ChoixPage[] | null
  valeur: string | null
  origine_valeur: string | null
  impose: boolean
}

export interface MentionPage {
  texte: string
  si_champ: string | null
  si_valeur: string | null
}

export interface SectionPage {
  code: string
  libelle: string | null
  traduction: string | null
  champs: ChampPage[]
  mentions: MentionPage[]
}

export interface Avertissement {
  code: string
  lot_id?: number | null
  zone_id?: number | null
  detail?: string | null
}

export interface Lot {
  lot_id: number
  numero: string | null
  zone_nom: string | null
  surface_m2: number | null
  statut: string
}

export interface FormulairePage {
  parcours: string
  parcours_titre: string
  service: string
  version: number
  formulaire: string
  titre_officiel: string
  langue: string
  langues: string[]
  langue_aide: string | null
  url_fichier: string | null
  url_source: string | null
  sections: SectionPage[]
  lots: Lot[]
  avertissements: Avertissement[]
  note_verification: string | null
  consentement: { version: string; texte: string }
}

export interface DemandeEnvoyee {
  reference: string
  envoyee_le: string
  depot_officiel_effectue: false
}

export type Valeurs = Record<string, string>
