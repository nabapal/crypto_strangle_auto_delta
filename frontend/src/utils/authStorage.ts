const TOKEN_KEY = "delta-strangle-token";

const isBrowser = () => typeof window !== "undefined" && typeof window.localStorage !== "undefined";

export const getToken = (): string | null => {
  if (!isBrowser()) {
    return null;
  }
  return window.localStorage.getItem(TOKEN_KEY);
};

export const setToken = (token: string): void => {
  if (!isBrowser()) {
    return;
  }
  window.localStorage.setItem(TOKEN_KEY, token);
};

export const clearToken = (): void => {
  if (!isBrowser()) {
    return;
  }
  window.localStorage.removeItem(TOKEN_KEY);
};
