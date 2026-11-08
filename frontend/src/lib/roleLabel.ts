// Libellés des rôles dans la langue du profil. Le `label` DB des rôles SYSTÈME est
// figé au seed (en français) : on le remplace par la traduction i18n, clé stable
// `iam.role_labels.<role_key>`. Un rôle personnalisé garde le label saisi par l'admin.
const SYSTEM_ROLE_KEYS = new Set([
  'CMS_SUPER_ADMIN',
  'CMS_ORG_ADMIN',
  'CMS_CAMPAIGN_MANAGER',
  'CMS_DESIGNER',
  'CMS_SCHEDULER',
  'CMS_APPROVER',
  'CMS_REPORT_VIEWER',
  'CMS_VIEWER',
  'CMS_STORE_OPERATOR',
  'CMS_GOVERNANCE_MANAGER',
  'CMS_SITE_PROGRAMMER',
  // Rôles scopés gouvernance ajoutés par la migr 0111 (G4). Absents d'ici, ils
  // afficheraient le `label` figé de la base au lieu de la langue du profil.
  'CMS_GOVERNANCE_EDITOR',
  'CMS_GOVERNANCE_APPROVER',
  'CMS_API_USER',
  'CMS_PLAYER',
  'CMS_ADVERTISER',
])

export function roleLabel(
  role: { role_key: string; label: string },
  t: (key: string) => string
): string {
  return SYSTEM_ROLE_KEYS.has(role.role_key)
    ? t(`iam.role_labels.${role.role_key}`)
    : role.label
}
