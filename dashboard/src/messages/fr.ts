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
      cannot_disable_self: "Vous ne pouvez pas désactiver votre propre compte.",
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
      last_enabled_operator:
        "C’est le dernier compte actif : le désactiver empêcherait toute connexion.",
      operator_exists: "Un compte d’opérateur porte déjà ce nom d’utilisateur.",
      operator_not_found: "Ce compte d’opérateur n’existe pas.",
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
      use_own_password_change:
        "Pour changer votre propre mot de passe, utilisez « Changer mon mot de passe ».",
    },
  },
  operators: {
    nav: "Opérateurs",
    title: "Opérateurs",
    intro:
      "Les comptes qui peuvent se connecter à ce tableau de bord. Chaque modification redemande votre mot de passe actuel.",
    listTitle: "Comptes",
    timeZone: "Heures de dernière connexion en {zone}.",
    empty: "Aucun compte d’opérateur.",
    columns: {
      username: "Nom d’utilisateur",
      status: "État",
      lastSignIn: "Dernière connexion",
      actions: "Actions",
    },
    you: "vous",
    enabled: "Actif",
    enabledHint: "Peut se connecter.",
    disabled: "Désactivé",
    disabledHint:
      "Ne peut plus se connecter tant que le compte n’est pas réactivé.",
    mustChangePassword: "Doit changer de mot de passe",
    mustChangePasswordHint:
      "Devra choisir un nouveau mot de passe à la prochaine connexion, avant toute autre action.",
    neverSignedIn: "jamais",
    currentPassword: "Votre mot de passe actuel",
    currentPasswordHint:
      "Confirme que c’est bien vous qui faites cette modification.",
    cancel: "Annuler",
    create: {
      title: "Créer un compte",
      note: "Le nouvel opérateur devra changer ce mot de passe à sa première connexion. Transmettez-le-lui par un canal sûr.",
      submit: "Créer le compte",
      done: "Compte {username} créé.",
    },
    reset: {
      open: "Réinitialiser le mot de passe",
      openLabel: "Réinitialiser le mot de passe de {username}",
      title: "Nouveau mot de passe pour {username}",
      description:
        "Il devra le changer à sa prochaine connexion. Ses sessions ouvertes sont fermées immédiatement.",
      submit: "Réinitialiser le mot de passe",
      done: "Le mot de passe de {username} est réinitialisé. Il devra le changer à sa prochaine connexion.",
    },
    disable: {
      open: "Désactiver",
      openLabel: "Désactiver {username}",
      title: "Désactiver {username} ?",
      description:
        "Il ne pourra plus se connecter, et ses sessions ouvertes sont fermées immédiatement. Vous pourrez réactiver le compte plus tard.",
      submit: "Désactiver le compte",
      done: "{username} est désactivé.",
    },
    enable: {
      open: "Réactiver",
      openLabel: "Réactiver {username}",
      title: "Réactiver {username}",
      description: "Il pourra de nouveau se connecter avec son mot de passe.",
      submit: "Réactiver le compte",
      done: "{username} est réactivé.",
    },
    own: {
      title: "Changer mon mot de passe",
      intro:
        "Vos autres sessions sont fermées quand le mot de passe change ; celle-ci reste ouverte.",
      submit: "Changer mon mot de passe",
      done: "Votre mot de passe est changé. Vos autres sessions sont fermées.",
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
  time: {
    zone: "Heures en {timeZone}",
    range: "Du {start} au {end}",
  },
  period: {
    label: "Période",
    "24h": "24 dernières heures",
    "7d": "7 derniers jours",
    "30d": "30 derniers jours",
  },
  filters: {
    tenant: "Tenant",
    allTenants: "Tous les tenants",
    status: "Statut",
    allStatuses: "Tous les statuts",
    alias: "Alias",
    allAliases: "Tous les alias",
    aliasSearch: "Filtre par alias",
    apply: "Appliquer",
  },
  autoRefresh: {
    updated: "Mis à jour {age}",
    paused: "Actualisation automatique en pause",
    pausedHidden:
      "Actualisation automatique en pause tant que l’onglet est masqué",
    failed: "Échec de la mise à jour",
    pause: "Pause",
    resume: "Reprendre",
    pauseLabel: "Mettre en pause l’actualisation automatique",
    resumeLabel: "Reprendre l’actualisation automatique",
  },
  statCard: {
    definitionOf: "Définition : {label}",
  },
  definitions: {
    requests:
      "Requêtes reçues sur la période, refus de quota tenant compris. Chaque requête compte une fois, quel que soit le nombre de cibles essayées.",
    errorRate:
      "Requêtes échouées / requêtes. Une requête échoue quand elle n’obtient pas de réponse à cause de la passerelle ou des fournisseurs : toutes les cibles ont échoué ou ont été ignorées (503), le délai est dépassé (504), ou un streaming a été interrompu après son premier token. Les erreurs client (requête invalide, quota du tenant, trop grande pour toutes les cibles) et les requêtes annulées ne sont pas des échecs.",
    fallbackRate:
      "Part des requêtes servies par un fournisseur (hors cache) dont la réponse vient d’une cible de repli, et non de la première cible de l’alias.",
    latency:
      "Durée des requêtes servies par un fournisseur, toutes tentatives comprises. p50 est la médiane, p95 le 95e centile.",
    timeToFirstToken:
      "Délai avant le premier contenu des réponses en streaming (stream: true). p50 est la médiane, p95 le 95e centile.",
    cacheHitLatency:
      "Durée médiane des requêtes servies par le cache (temps de recherche).",
    tokens:
      "Tokens du prompt et de la réponse des fournisseurs. Les réponses du cache ne consomment aucun token et ne sont pas comptées.",
    cost: "Coût de chaque tentative qui a un prix. Les requêtes servies par un modèle sans prix, ou sans nombre de tokens renvoyé par le fournisseur, ne sont pas incluses : elles sont comptées à part, jamais comme gratuites.",
    cacheHitRate:
      "Réponses du cache / requêtes vers un alias qui utilise le cache. 0 quand aucune requête n’a utilisé le cache.",
    cacheHits: "Requêtes servies par le cache, sans appel à un fournisseur.",
    savedTokens:
      "Tokens que les réponses du cache n’ont pas consommés : l’usage en tokens des réponses d’origine qu’elles ont rejouées.",
    savedCost:
      "Ce qu’auraient coûté les réponses du cache si un fournisseur avait répondu.",
    quotaRefusals:
      "Requêtes refusées par le quota propre du tenant (requêtes par minute ou budget quotidien de tokens) : HTTP 429.",
    targetCalls:
      "Appels réels au fournisseur sur la période. Les cibles ignorées (pause, disjoncteur, quota) et les requêtes trop grandes pour la cible ne sont pas des appels.",
    targetSuccessRate:
      "Appels réussis / appels. n.d. quand la cible n’a pas été appelée sur la période.",
    targetLatency:
      "Durée des appels réussis de cette cible. p50 est la médiane, p95 le 95e centile.",
    targetFailures:
      "Appels en échec, par motif. Après un 429, un délai dépassé, une cible indisponible ou mal configurée, la passerelle essaie la cible suivante de l’alias.",
    targetSkips:
      "Nombre de fois où la passerelle n’a pas appelé cette cible et a essayé la suivante : pause en cours, disjoncteur ouvert ou quota atteint.",
    targetRequestErrors:
      "Pas un problème de la cible : le fournisseur a refusé la requête (4xx), ou la requête était trop grande pour cette cible (vérifié avant l’appel, ou refusé par le fournisseur). Une requête trop grande est essayée sur la cible suivante.",
    cooldown:
      "Après un 429 ou une erreur de configuration, la cible est ignorée jusqu’à la fin de la pause.",
    breaker:
      "Fermé : les appels passent. Ouvert : trop d’échecs, la cible est ignorée jusqu’à la fin de l’ouverture. Semi-ouvert : un appel d’essai décide s’il se referme.",
    rpm: "Requêtes des 60 dernières secondes, comparées à la limite de requêtes par minute de la configuration.",
    tpm: "Tokens réservés ou consommés sur les 60 dernières secondes, comparés à la limite de tokens par minute de la configuration.",
    rpd: "Requêtes depuis la dernière remise à zéro quotidienne du fournisseur, comparées à la limite de requêtes par jour de la configuration.",
  },
  overview: {
    title: "Vue d’ensemble",
    titleForTenant: "Vue d’ensemble : {tenant}",
    groups: {
      traffic: "Trafic",
      speed: "Rapidité",
      cost: "Tokens et coût",
      cache: "Cache",
    },
    requests: "Requêtes",
    answered: { one: "{count} servie", other: "{count} servies" },
    errorRate: "Taux d’erreur",
    errorDetail: "{failed}. Non comptées : {clientErrors}, {cancelled}.",
    failed: { one: "{count} en échec", other: "{count} en échec" },
    clientErrors: {
      one: "{count} erreur client",
      other: "{count} erreurs client",
    },
    cancelled: { one: "{count} annulée", other: "{count} annulées" },
    fallbackRate: "Taux de repli",
    latency: "Latence p50",
    p95: "p95 : {value}",
    timeToFirstToken: "Délai du premier token p50",
    timeToFirstTokenDetail: "p95 : {value} · streaming uniquement",
    cacheHitLatency: "Latence du cache p50",
    tokens: "Tokens",
    cost: "Coût",
    unpriced: {
      one: "{count} requête sans prix, non incluse",
      other: "{count} requêtes sans prix, non incluses",
    },
    cacheHitRate: "Part servie par le cache",
    cacheHitDetail: "{hits} sur {requests}",
    hits: {
      one: "{count} réponse du cache",
      other: "{count} réponses du cache",
    },
    cachedRequests: {
      one: "{count} requête avec cache",
      other: "{count} requêtes avec cache",
    },
    savedTokens: "Tokens économisés",
    savedCost: "Coût économisé",
  },
  charts: {
    label: "Graphiques",
    title: "Évolution",
    requestsTitle: "Requêtes et requêtes en échec",
    requests: "Requêtes",
    failed: "En échec",
    costTitle: "Coût (USD)",
    cost: "Coût",
    cacheHitsTitle: "Réponses du cache",
    cacheHits: "Réponses du cache",
    hourNote: "Une barre par heure, heures en {timeZone}.",
    dayNote: "Une barre par jour UTC.",
    utcDay: "{day} (jour UTC)",
  },
  tenants: {
    title: "Tenants",
    tenant: "Tenant",
    requests: "Requêtes",
    tokens: "Tokens",
    cost: "Coût",
    costWithUnpriced: "{cost} ({count} sans prix)",
    errorRate: "Taux d’erreur",
    cacheHits: "Réponses du cache",
    savedCost: "Coût économisé",
    quotaRefusals: "Refus de quota",
    empty: "Aucun tenant pour l’instant. Créez-en un avec {command}.",
  },
  targetHealth: {
    labels: {
      healthy: "Opérationnelle",
      cooling_down: "En pause",
      breaker_open: "Disjoncteur ouvert",
      half_open: "Disjoncteur semi-ouvert",
      quota_full: "Quota atteint",
      live_unknown: "État en direct indisponible (Redis)",
      removed: "Plus configurée",
    },
    definitions: {
      healthy:
        "Pas de pause, disjoncteur fermé, quotas disponibles : la cible reçoit du trafic.",
      cooling_down:
        "Un 429 ou une erreur de configuration a lancé une pause : la cible est ignorée jusqu’à sa fin.",
      breaker_open:
        "Trop d’échecs ont ouvert le disjoncteur : la cible est ignorée jusqu’à ce qu’il passe en semi-ouvert.",
      half_open:
        "Le disjoncteur laisse passer un appel d’essai. Son résultat le referme ou le rouvre.",
      quota_full:
        "Un quota de requêtes ou de tokens est épuisé : la cible est ignorée jusqu’à ce que la fenêtre se libère.",
      live_unknown:
        "Redis est illisible : pauses, disjoncteurs et quotas consommés sont inconnus. La passerelle route sans eux (mode dégradé).",
      removed:
        "Cette cible n’est plus dans aucune route. Elle apparaît car elle a été utilisée sur la période.",
    },
  },
  providers: {
    title: "Fournisseurs et modèles",
    empty: "Aucune cible configurée : ajoutez des routes dans {file}.",
    byStatus: "Cibles par état",
    statusCount: "{status} : {count}",
    status: "État",
    statistics: "Statistiques de la période",
    calls: "Appels",
    successRate: "Taux de réussite",
    latency: "Latence p50 / p95",
    failures: "Échecs",
    rateLimited: "Limite de débit (429)",
    timeouts: "Délais dépassés",
    unavailable: "Indisponible",
    misconfigured: "Mal configurée",
    interrupted: "Streamings interrompus",
    cancelled: "Annulés par le client",
    skipped: "Cible ignorée",
    cooldown: "Pause",
    breakerOpen: "Disjoncteur ouvert",
    quotaFull: "Quota atteint",
    causedByRequest: "Dû à la requête",
    invalidRequests: "Requêtes invalides",
    tooLarge: "Trop grandes pour la cible",
    liveState: "État en direct",
    now: "Maintenant",
    removed:
      "Cette cible n’est plus dans aucune route : la passerelle ne l’utilise pas.",
    liveUnknown:
      "État en direct indisponible (Redis) : pause, disjoncteur et quotas consommés sont illisibles. Seules les limites configurées sont affichées.",
    breaker: "Disjoncteur",
    rpm: "Requêtes par minute",
    tpm: "Tokens par minute",
    rpd: "Requêtes par jour",
    dailyReset: "Remise à zéro quotidienne",
    cooldownNone: "Aucune",
    cooldownActive: "En cours",
    cooldownUntil: "En cours jusqu’au {time}",
    breakerOpenState: "Ouvert",
    breakerOpenUntil: "Ouvert jusqu’au {time}",
    halfOpenTrialRunning: "Semi-ouvert, appel d’essai en cours",
    halfOpenWaiting: "Semi-ouvert, en attente d’un appel d’essai",
    breakerClosed: "Fermé",
  },
  requestStatus: {
    labels: {
      answered: "Servie",
      failed: "En échec",
      client_error: "Erreur client",
      cancelled: "Annulée",
    },
    definitions: {
      answered: "Le client a reçu une réponse, d’un fournisseur ou du cache.",
      failed:
        "Pas de réponse à cause de la passerelle ou des fournisseurs : toutes les cibles ont échoué ou ont été ignorées (503), le délai est dépassé (504), ou un streaming a été interrompu après son premier token.",
      client_error:
        "La requête elle-même a été refusée : requête invalide (4xx du fournisseur), quota du tenant dépassé (429), ou trop grande pour toutes les cibles (400).",
      cancelled: "Le client est parti avant la fin de la réponse.",
    },
  },
  cache: {
    off: "désactivé",
    hit: "trouvé",
    miss: "absent",
    bypass: "contourné",
    unavailable: "indisponible",
  },
  requests: {
    title: "Requêtes",
    olderPage:
      "Requêtes plus anciennes : l’actualisation automatique est coupée sur cette page.",
    empty: "Aucune requête ne correspond à ces filtres sur la période.",
    columns: {
      time: "Heure",
      tenant: "Tenant",
      alias: "Alias",
      status: "Statut",
      http: "HTTP",
      answeredBy: "Servie par",
      attempts: "Tentatives",
      stream: "Streaming",
      latency: "Latence",
      cost: "Coût",
      cache: "Cache",
    },
    columnDefinitions: {
      status:
        "Servie, en échec (passerelle ou fournisseurs), erreur client (requête refusée) ou annulée (le client est parti).",
      http: "Code HTTP de la dernière cible examinée.",
      answeredBy: "Fournisseur et modèle de la réponse.",
      attempts: "Cibles examinées, cibles ignorées comprises.",
      latency: "Somme des durées des tentatives.",
      cache:
        "Ce qu’a fait le cache : trouvé, absent, contourné ou indisponible. Désactivé quand l’alias ne l’utilise pas.",
    },
    detailsOf: "Détail de la requête {id}",
    yes: "oui",
    no: "non",
    notAnswered: "sans réponse",
    pages: "Pages de requêtes",
    newest: "Requêtes les plus récentes",
    older: "Requêtes plus anciennes",
  },
  requestDetail: {
    back: "← Retour aux requêtes",
    title: "Requête {id}",
    notFound: "Aucune requête avec cet identifiant.",
    notFoundHint:
      "Vérifiez l’identifiant. Les anciennes requêtes ont pu être supprimées du journal d’usage par sa durée de conservation.",
    summary: "Résumé",
    received: "Reçue",
    tenant: "Tenant",
    alias: "Alias",
    status: "Statut",
    httpStatus: "Code HTTP",
    answeredBy: "Servie par",
    attempts: "Tentatives",
    stream: "Streaming",
    latency: "Latence",
    cost: "Coût",
    cache: "Cache",
    pathTitle: "Parcours de routage",
    pathIntro:
      "Toutes les cibles examinées par la passerelle pour cette requête, dans l’ordre.",
  },
  routingPath: {
    label: "Parcours de routage",
    step: "Étape {number}",
    noTarget: "Aucune cible examinée",
    degraded: "Mode dégradé",
    degradedDefinition:
      "La passerelle a routé sans Redis : aucun contrôle de quota, de pause ou de disjoncteur.",
    httpStatus: "Code HTTP",
    latency: "Latence",
    firstToken: "Premier token",
    tokens: "Tokens",
    promptTokens: "{tokens} prompt",
    completionTokens: "{tokens} réponse",
    estimatedTokens: "{tokens} estimés",
    cost: "Coût",
    savedCost: "Coût économisé",
    cache: "Cache",
    similarity: "Similarité",
    identical: "1 (requête identique)",
  },
  outcomes: {
    kinds: {
      success: "Réussite",
      error: "Erreur",
      skipped: "Ignorée",
      client_error: "Erreur client",
    },
    labels: {
      success: "Servie",
      cache_hit: "Servie par le cache",
      rate_limited: "Limite de débit (429)",
      unavailable: "Indisponible (5xx ou erreur réseau)",
      timeout: "Délai dépassé",
      misconfigured: "Mal configurée (401, 403 ou 404)",
      interrupted: "Streaming interrompu après le premier token",
      skipped_cooldown: "Pause en cours",
      skipped_breaker: "Disjoncteur ouvert",
      skipped_quota: "Quota atteint",
      invalid_request: "Requête invalide (4xx)",
      cancelled: "Annulée par le client",
      rejected_tenant_quota: "Quota du tenant dépassé (429)",
      context_too_large_skipped: "Trop grande pour cette cible",
      context_too_large_refused:
        "Contexte trop grand (refusé par le fournisseur)",
    },
  },
  keys: {
    title: "Clés",
    intro:
      "Gérez les clés d’API et les limites des tenants. Les passerelles voient les changements en moins de 60 secondes.",
    createHeading: "Créer une clé",
    tenantsHeading: "Tenants",
    selectTenant: "Choisissez un tenant pour voir ses limites et ses clés.",
    noTenant:
      "Aucun tenant pour l’instant : créez une clé pour créer le premier.",
    historyHeading: "Historique des actions d’administration",
    fields: {
      tenant: "Tenant",
      rpm: "Requêtes par minute",
      tokens_per_day: "Tokens par jour",
      rpmOptional: "Requêtes par minute (facultatif)",
      tokensOptional: "Tokens par jour (facultatif)",
      cacheAlias: "Alias (facultatif : tous les alias si vide)",
    },
    create: {
      submit: "Créer la clé",
      hint: "Un nouveau tenant est créé avec sa première clé. Les limites saisies deviennent les limites propres du tenant ; les champs vides gardent leur valeur.",
    },
    newKey: {
      heading: "Nouvelle clé pour le tenant {tenant}",
      warning:
        "Copiez cette clé maintenant. Elle ne sera plus jamais affichée : la passerelle n’en garde qu’une empreinte. Quitter ou recharger cette page la fait disparaître.",
      label: "Nouvelle clé d’API",
      copy: "Copier la clé",
      stored: "J’ai enregistré la clé",
      copied: "Copiée dans le presse-papiers.",
      copyFailed:
        "La copie n’est pas disponible dans ce navigateur. Sélectionnez la clé ci-dessus et copiez-la à la main (Ctrl+C ou Cmd+C).",
    },
    panel: {
      title: "Tenant {tenant}",
      limits: "Limites",
      keys: "Clés",
      cache: "Cache",
    },
    limits: {
      limit: "Limite",
      own: "Propre",
      applied: "Appliquée",
      tokensPerUtcDay: "Tokens par jour (jour UTC)",
      default: "par défaut",
      noLimit: "sans limite",
      now: "actuellement : {value}",
      nowNoLimit: "actuellement : sans limite",
      hint: "Remplissez au moins un champ. Un champ vide garde sa valeur. Les passerelles appliquent les nouvelles limites en moins de 60 secondes.",
      saved: "Limites enregistrées.",
      submit: "Enregistrer les limites",
    },
    table: {
      noKey: "Ce tenant n’a aucune clé.",
      key: "Clé",
      created: "Créée",
      lastUsed: "Dernière utilisation",
      status: "Statut",
      actions: "Actions",
      never: "jamais",
      revoked: "Révoquée le {time}",
      active: "Active",
    },
    revoke: {
      open: "Révoquer",
      openLabel: "Révoquer la clé {prefix}",
      title: "Révoquer la clé {prefix} ?",
      description:
        "Les applications qui l’utilisent seront refusées en moins de 60 secondes. Action irréversible.",
      confirm: "Révoquer la clé",
      cancel: "Annuler",
    },
    cache: {
      submit: "Vider le cache",
      removed: {
        one: "{count} réponse en cache supprimée ({scope}).",
        other: "{count} réponses en cache supprimées ({scope}).",
      },
      everyAlias: "tous les alias",
      oneAlias: "alias {alias}",
    },
    history: {
      empty: "Aucune action d’administration pour l’instant.",
      time: "Heure",
      actor: "Auteur",
      action: "Action",
      target: "Cible",
      details: "Détails",
      loading: "Chargement…",
      loadMore: "Afficher plus",
      everyTenant: "tous les tenants",
      key: "clé {id}",
      everyAlias: "tous les alias",
      actions: {
        "create-key": "Création de clé",
        "revoke-key": "Révocation de clé",
        "set-limits": "Changement de limites",
        "clear-cache": "Vidage du cache",
        "purge-usage-log": "Purge du journal d’usage",
        "create-operator": "Création d’opérateur",
        "recover-operator": "Récupération d’opérateur",
        "reset-password": "Réinitialisation de mot de passe",
        "disable-operator": "Désactivation d’opérateur",
        "enable-operator": "Réactivation d’opérateur",
        "change-own-password": "Changement de son mot de passe",
        "create-admin-key": "Création de clé d’administration",
        "revoke-admin-key": "Révocation de clé d’administration",
      },
      detailNames: {
        key_id: "id de clé",
        prefix: "préfixe",
        tenant: "tenant",
        alias: "alias",
        rpm: "requêtes/min",
        tokens_per_day: "tokens par jour",
        removed: "supprimées",
        older_than_days: "plus vieux que (jours)",
        deleted: "supprimées",
        cutoff: "date limite",
      },
    },
    problems: {
      missingTenantName: "Saisissez le nom d’un tenant.",
      noTenantSelected: "Aucun tenant n’est sélectionné.",
      noLimitGiven:
        "Indiquez au moins une limite : requêtes par minute ou tokens par jour.",
      notWholeNumber: "{field} : saisissez un nombre entier supérieur à 0.",
      tooLarge: "{field} : nombre trop grand.",
      missingKeyId:
        "Impossible de révoquer cette clé : son identifiant manque.",
      noMoreActions: "Plus aucune action à charger.",
    },
    errors: {
      refusedValues: "L’API d’administration a refusé les valeurs.",
      httpError: "L’API d’administration a renvoyé une erreur (HTTP {status}).",
    },
  },
};
