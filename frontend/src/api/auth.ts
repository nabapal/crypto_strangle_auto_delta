import client from "./client";

export interface User {
  id: number;
  email: string;
  full_name?: string | null;
  is_active: boolean;
  is_superuser: boolean;
  created_at: string;
  updated_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export const login = async (email: string, password: string): Promise<AuthResponse> => {
  const formData = new URLSearchParams();
  formData.append("username", email);
  formData.append("password", password);

  const response = await client.post<AuthResponse>("/auth/login", formData, {
    headers: { "Content-Type": "application/x-www-form-urlencoded" }
  });
  return response.data;
};

export const fetchCurrentUser = async (): Promise<User> => {
  const response = await client.get<User>("/auth/me");
  return response.data;
};

export const register = async (email: string, password: string, fullName?: string | null): Promise<User> => {
  const response = await client.post<User>("/auth/register", {
    email,
    password,
    full_name: fullName
  });
  return response.data;
};
