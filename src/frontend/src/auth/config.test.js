import assert from 'node:assert/strict'
import test from 'node:test'

import { buildOidcSettings, businessRoleLabel, identityInitial } from './config.js'

test('buildOidcSettings configures authorization code flow without a secret', () => {
  const settings = buildOidcSettings({
    VITE_KEYCLOAK_AUTHORITY: 'http://localhost:8080/realms/trusted-rag/',
    VITE_KEYCLOAK_CLIENT_ID: 'trusted-rag-web',
  }, { origin: 'http://localhost:5173' })

  assert.equal(settings.authority, 'http://localhost:8080/realms/trusted-rag')
  assert.equal(settings.client_id, 'trusted-rag-web')
  assert.equal(settings.response_type, 'code')
  assert.equal(settings.redirect_uri, 'http://localhost:5173/')
  assert.equal('client_secret' in settings, false)
})

test('identity helpers use approved business role labels', () => {
  assert.equal(businessRoleLabel('member'), '企业成员')
  assert.equal(businessRoleLabel('knowledge_maintainer'), '知识库维护者')
  assert.equal(identityInitial({ display_name: '林然' }), '林')
})
