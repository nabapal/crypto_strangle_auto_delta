import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";

import type { AuthResponse, User } from "../api/auth";
import { fetchCurrentUser, login as loginRequest } from "../api/auth";
import logger from "../utils/logger";
import { clearToken, getToken, setToken } from "../utils/authStorage";
import { emitLogout, onLogout } from "../utils/authEvents";

interface AuthContextValue {
  user: User | null;
  isAuthenticated: boolean;
  initializing: boolean;
  login: (email: string, password: string) => Promise<AuthResponse>;
  logout: () => void;
  refreshUser: () => Promise<User | null>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [user, setUser] = useState<User | null>(null);
  const [initializing, setInitializing] = useState(true);

  const bootstrap = useCallback(async () => {
    const token = getToken();
    if (!token) {
      setUser(null);
      setInitializing(false);
      return;
    }

    try {
      const profile = await fetchCurrentUser();
      setUser(profile);
    } catch (caughtError) {
      clearToken();
      setUser(null);
      logger.warn("Failed to fetch current user; clearing session", {
        event: "auth_bootstrap_failed",
        error: caughtError instanceof Error ? caughtError.message : caughtError
      });
    } finally {
      setInitializing(false);
    }
  }, []);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    const unsubscribe = onLogout(() => {
      clearToken();
      setUser(null);
    });
    return unsubscribe;
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const response = await loginRequest(email, password);
    setToken(response.access_token);
    setUser(response.user);
    logger.info("User authenticated", {
      event: "auth_login_success",
      email: response.user.email
    });
    return response;
  }, []);

  const logout = useCallback(() => {
    clearToken();
    setUser(null);
    emitLogout();
    logger.info("User logged out", {
      event: "auth_logout"
    });
  }, []);

  const refreshUser = useCallback(async () => {
    try {
      const profile = await fetchCurrentUser();
      setUser(profile);
      return profile;
  } catch (error) {
      logger.warn("Failed to refresh user", {
        event: "auth_refresh_failed",
        error
      });
      clearToken();
      setUser(null);
      return null;
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isAuthenticated: Boolean(user),
      initializing,
      login,
      logout,
      refreshUser
    }),
    [initializing, login, logout, refreshUser, user]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = (): AuthContextValue => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};
