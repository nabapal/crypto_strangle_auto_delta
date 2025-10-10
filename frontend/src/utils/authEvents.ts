const LOGOUT_EVENT = "delta-strangle-auth-logout";

const isBrowser = () => typeof window !== "undefined";

export const emitLogout = (): void => {
  if (!isBrowser()) {
    return;
  }
  window.dispatchEvent(new CustomEvent(LOGOUT_EVENT));
};

export const onLogout = (handler: () => void): (() => void) => {
  if (!isBrowser()) {
    return () => undefined;
  }
  const listener = () => handler();
  window.addEventListener(LOGOUT_EVENT, listener);
  return () => window.removeEventListener(LOGOUT_EVENT, listener);
};
