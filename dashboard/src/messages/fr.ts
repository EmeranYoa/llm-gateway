import type { Messages } from "./types";

/**
 * French texts of the dashboard. Same keys as `en.ts` (checked by the
 * compiler), translated into natural, short French.
 *
 * French typography: a non-breaking space (` `) before `:`, `?`, `!`, `%`
 * and between a number and its unit, and the typographic apostrophe (`’`).
 */
export const fr: Messages = {
  app: {
    title: "Administration de LLM Gateway",
    description: "Usage, coûts et clés de la passerelle LLM.",
  },
  nav: {
    label: "Navigation principale",
    overview: "Vue d’ensemble",
    tenants: "Tenants",
    providers: "Fournisseurs",
    requests: "Requêtes",
    keys: "Clés",
    signOut: "Se déconnecter",
  },
  language: {
    label: "Langue",
  },
  session: {
    expired:
      "Votre session a pris fin : la clé d’administration a été refusée. Reconnectez-vous.",
  },
  apiError: {
    title: "L’API d’administration a renvoyé une erreur.",
    generic: "L’API d’administration n’a pas pu traiter la demande.",
    englishDetail: "Détail (en anglais) : {detail}",
    codes: {
      admin_api_unreachable:
        "L’API d’administration est injoignable. Vérifiez qu’elle est démarrée.",
      authentication_unavailable:
        "Impossible de vérifier la clé d’administration pour l’instant. Réessayez plus tard.",
      database_unavailable:
        "La base de données est indisponible. Réessayez plus tard.",
      invalid_api_key: "Clé d’administration absente ou invalide.",
      invalid_credentials: "Identifiants incorrects.",
      invalid_cursor:
        "Cette page de résultats n’est plus valide. Revenez à la première page.",
      invalid_session: "Votre session n’est plus valide. Reconnectez-vous.",
      invalid_setup_token: "Ce lien de configuration est invalide ou a expiré.",
      key_already_revoked: "Cette clé d’API est déjà révoquée.",
      key_not_found: "Cette clé d’API n’existe pas.",
      password_change_required: "Changez votre mot de passe pour continuer.",
      redis_unavailable: "Redis est indisponible. Réessayez plus tard.",
      request_not_found: "Aucune requête avec cet identifiant.",
      setup_closed:
        "La configuration initiale est déjà faite. Connectez-vous plutôt.",
      tenant_not_found: "Ce tenant n’existe pas.",
    },
  },
  format: {
    noValue: "n.d.",
    unknown: "inconnu",
    noLimit: "sans limite",
    quota: "{used} / {limit}",
    lessThan: "< {amount}",
    milliseconds: "{value} ms",
    seconds: "{value} s",
    minutes: "{value} min",
    minutesSeconds: "{minutes} min {seconds} s",
    hours: "{value} h",
    ago: "il y a {duration}",
  },
};
