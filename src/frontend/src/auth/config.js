export function buildOidcSettings(env, location) {
  const authority = env.VITE_KEYCLOAK_AUTHORITY
  const clientId = env.VITE_KEYCLOAK_CLIENT_ID
  if (!authority || !clientId) return null

  return {
    authority: authority.replace(/\/$/, ''),
    client_id: clientId,
    redirect_uri: `${location.origin}/`,
    post_logout_redirect_uri: `${location.origin}/`,
    response_type: 'code',
    scope: 'openid profile email',
    automaticSilentRenew: true,
  }
}

export function businessRoleLabel(role) {
  return role === 'knowledge_maintainer' ? '知识库维护者' : '企业成员'
}

export function identityInitial(identity) {
  return (identity?.display_name || identity?.username || '企').slice(0, 1)
}
