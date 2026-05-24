import { LogIn } from "lucide-react";
import { FormEvent, useState } from "react";
import { api, setToken } from "../services/api";

interface LoginPageProps {
  onLoggedIn: () => void;
}

export function LoginPage({ onLoggedIn }: LoginPageProps) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const result = await api.login(username, password);
      setToken(result.access_token);
      onLoggedIn();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "登录失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">
          <div className="brand-mark large" />
          <div>
            <strong>SmartX</strong>
            <span>Storage Forecast</span>
          </div>
        </div>
        <label>
          用户名
          <input value={username} onChange={(event) => setUsername(event.target.value)} />
        </label>
        <label>
          密码
          <input value={password} type="password" onChange={(event) => setPassword(event.target.value)} />
        </label>
        {error && <div className="form-error">{error}</div>}
        <button className="primary-button" type="submit" disabled={loading}>
          <LogIn size={17} />
          {loading ? "登录中" : "登录"}
        </button>
      </form>
    </div>
  );
}

