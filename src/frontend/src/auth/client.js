import { UserManager, WebStorageStateStore } from 'oidc-client-ts'

import { buildOidcSettings } from './config.js'


let userManager
let initialization


export function getUserManager() {
  if (userManager) return userManager
  const settings = buildOidcSettings(import.meta.env, window.location)
  if (!settings) return null
  userManager = new UserManager({
    ...settings,
    userStore: new WebStorageStateStore({ store: window.localStorage }),
  })
  return userManager
}


export function initializeAuthentication() {
  if (initialization) return initialization
  initialization = (async () => {
    const manager = getUserManager()
    if (!manager) return { manager: null, user: null }

    const params = new URLSearchParams(window.location.search)
    if (params.has('code') && params.has('state')) {
      await manager.signinRedirectCallback()
      window.history.replaceState({}, document.title, window.location.pathname)
    }

    const user = await manager.getUser()
    return { manager, user: user && !user.expired ? user : null }
  })()
  return initialization
}
