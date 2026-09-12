import { LOCAL_STORAGE_PREFIX } from '../storage/userDataNamespace';

const COLORBLIND_STORAGE_KEY = `${LOCAL_STORAGE_PREFIX}:colorblind-colors`;

export function readColorblindPreference(): boolean {
  try {
    return window.localStorage.getItem(COLORBLIND_STORAGE_KEY) === 'true';
  } catch {
    return false;
  }
}

export function saveColorblindPreference(enabled: boolean): boolean {
  try {
    window.localStorage.setItem(COLORBLIND_STORAGE_KEY, String(enabled));
    return true;
  } catch {
    return false;
  }
}
