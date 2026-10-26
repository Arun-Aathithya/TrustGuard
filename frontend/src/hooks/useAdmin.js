import { useSyncExternalStore } from "react";
import { checkAdmin, errorMessage, fetchAuthStatus, getAdminKey, setAdminKey } from "../api/client";

/**
 * Viewer / admin mode for the dashboard.
 *  - enforced === false: the server has no admin key, so every action is open; everyone is treated as admin
 *    (the security banner tells the operator to set a key).
 *  - enforced === true:  only someone who enters the correct key (verified against the server) is admin;
 *    everyone else is a read-only viewer and the edit controls are not shown.
 * The server remains the real gate: hiding buttons is only the friendly part.
 */
let state = { enforced: null, verified: false, checking: false };
const listeners = new Set();
let started = false;

function set(next) {
  state = { ...state, ...next };
  listeners.forEach((l) => l());
}

async function verify() {
  if (!getAdminKey()) { set({ verified: false, checking: false }); return; }
  set({ checking: true });
  try {
    await checkAdmin();
    set({ verified: true, checking: false });
  } catch {
    setAdminKey(""); // wrong or stale key
    set({ verified: false, checking: false });
  }
}

async function start() {
  if (started) return;
  started = true;
  try {
    const { enforced } = await fetchAuthStatus();
    set({ enforced });
    if (enforced) await verify();
  } catch {
    // Older backend without the endpoint, or unreachable: keep the old behaviour (controls visible, server decides).
    set({ enforced: false });
  }
}

export async function adminLogin(key) {
  setAdminKey(key.trim());
  try {
    await checkAdmin();
    set({ verified: true });
    return null;
  } catch (e) {
    setAdminKey("");
    set({ verified: false });
    return e?.response?.status === 401 ? "That key is not correct." : errorMessage(e);
  }
}

export function adminLogout() {
  setAdminKey("");
  set({ verified: false });
}

function subscribe(cb) {
  listeners.add(cb);
  start();
  return () => listeners.delete(cb);
}
const snapshot = () => state;

export function useAdmin() {
  const s = useSyncExternalStore(subscribe, snapshot);
  return {
    enforced: s.enforced,
    checking: s.checking,
    isAdmin: s.enforced === false || s.verified,
  };
}
