export interface V2LoginResponse {
  access_token: string;
  token_type: "bearer";
  username: string;
}

export interface V2CurrentUser {
  username: string;
  is_admin: boolean;
}

export interface V2PasswordChangePayload {
  current_password: string;
  new_password: string;
  confirm_password: string;
}

const TOKEN_KEY = "smartx-v2-token";
export const V2_AUTH_CHANGED_EVENT = "smartx-v2-auth-changed";

export function getV2Token(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setV2Token(token: string | null): void {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
  window.dispatchEvent(new Event(V2_AUTH_CHANGED_EVENT));
}

async function v2Request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  const token = getV2Token();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    if (response.status === 401) setV2Token(null);
    throw new Error(payload.detail || response.statusText);
  }
  return response.json() as Promise<T>;
}

export const v2AuthApi = {
  login(username: string, password: string): Promise<V2LoginResponse> {
    return v2Request<V2LoginResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password })
    });
  },
  me(): Promise<V2CurrentUser> {
    return v2Request<V2CurrentUser>("/api/me");
  },
  changePassword(payload: V2PasswordChangePayload): Promise<{ ok: boolean }> {
    return v2Request<{ ok: boolean }>("/api/me/password", {
      method: "PUT",
      body: JSON.stringify(payload)
    });
  }
};
