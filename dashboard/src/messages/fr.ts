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
    saveFailed: "Impossible d’enregistrer la langue dans votre compte.",
  },
  session: {
    expired: "Votre session a pris fin. Reconnectez-vous.",
  },
  auth: {
    username: "Nom d’utilisateur",
    password: "Mot de passe",
    passwordAgain: "Mot de passe (confirmation)",
    currentPassword: "Mot de passe actuel",
    newPassword: "Nouveau mot de passe",
    newPasswordAgain: "Nouveau mot de passe (confirmation)",
    passwordRule: "12 caractères au moins, différent du nom d’utilisateur.",
    tokenHint: "Affiché dans les logs de l’API d’administration :",
    problems: {
      missingFields: "Remplissez tous les champs.",
      passwordsDiffer: "Les deux mots de passe sont différents.",
      passwordTooShort: "Le mot de passe doit contenir au moins 12 caractères.",
    },
    tooManyAttemptsWait:
      "Trop de tentatives de connexion. Réessayez dans {wait}.",
  },
  signIn: {
    title: "Connexion",
    intro: "Connectez-vous avec votre compte d’opérateur.",
    submit: "Se connecter",
    recoveryLink: "Tous les mots de passe sont perdus ? Récupérer un compte",
  },
  setup: {
    title: "Créer le premier compte",
    intro:
      "Aucun compte d’opérateur n’existe encore. Créez le premier avec le jeton de configuration.",
    token: "Jeton de configuration",
    submit: "Créer le compte",
  },
  changePassword: {
    title: "Changez votre mot de passe",
    required: "Choisissez un nouveau mot de passe pour continuer.",
    submit: "Changer le mot de passe",
  },
  recovery: {
    title: "Récupérer un compte",
    intro:
      "Définissez un nouveau mot de passe pour un compte grâce au jeton de récupération. Vous en choisirez un autre à la connexion.",
    token: "Jeton de récupération",
    submit: "Définir le nouveau mot de passe",
    done: "Le mot de passe de {username} est défini. Connectez-vous avec : vous en choisirez ensuite un autre.",
    signInLink: "Aller à la connexion",
    banner:
      "La récupération de compte est activée. Une fois reconnecté, retirez OPERATOR_RECOVERY des réglages de l’API d’administration, puis redémarrez-la.",
  },
  apiError: {
    title: "L’API d’administration a renvoyé une erreur.",
    generic: "L’API d’administration n’a pas pu traiter la demande.",
    englishDetail: "Détail (en anglais) : {detail}",
    codes: {
      admin_api_unreachable:
        "L’API d’administration est injoignable. Vérifiez qu’elle est démarrée.",
      authentication_unavailable:
        "Impossible de vérifier la connexion pour l’instant. Réessayez plus tard.",
      database_unavailable:
        "La base de données est indisponible. Réessayez plus tard.",
      invalid_credentials: "Nom d’utilisateur ou mot de passe incorrect.",
      invalid_cursor:
        "Cette page de résultats n’est plus valide. Revenez à la première page.",
      invalid_password:
        "Ce mot de passe est refusé : 12 caractères au moins, différent du nom d’utilisateur.",
      invalid_recovery_token:
        "Jeton de récupération incorrect. Recopiez-le depuis les logs de l’API d’administration.",
      invalid_session: "Votre session n’est plus valide. Reconnectez-vous.",
      invalid_setup_token:
        "Jeton de configuration incorrect. Recopiez-le depuis les logs de l’API d’administration.",
      key_already_revoked: "Cette clé d’API est déjà révoquée.",
      key_not_found: "Cette clé d’API n’existe pas.",
      operator_not_found: "Aucun compte d’opérateur n’a ce nom d’utilisateur.",
      password_change_required: "Changez votre mot de passe pour continuer.",
      reauthentication_failed: "Le mot de passe actuel est incorrect.",
      recovery_disabled:
        "La récupération de compte est désactivée. Démarrez l’API d’administration avec OPERATOR_RECOVERY=true pour l’utiliser.",
      recovery_used:
        "Le jeton de récupération a déjà servi. Redémarrez l’API d’administration pour en obtenir un nouveau.",
      redis_unavailable: "Redis est indisponible. Réessayez plus tard.",
      request_not_found: "Aucune requête avec cet identifiant.",
      setup_closed: "Le premier compte existe déjà. Connectez-vous plutôt.",
      tenant_not_found: "Ce tenant n’existe pas.",
      too_many_attempts:
        "Trop de tentatives de connexion. Réessayez plus tard.",
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
