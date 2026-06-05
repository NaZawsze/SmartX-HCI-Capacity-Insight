import { FormEvent, useEffect, useRef, useState } from "react";
import { KeyRound, LogOut, Save, UserRound, X } from "lucide-react";
import { v2AuthApi } from "../services/auth";

interface AccountMenuProps {
  onLogout: () => void;
}

const emptyPasswordForm = {
  current_password: "",
  new_password: "",
  confirm_password: ""
};

export function AccountMenu({ onLogout }: AccountMenuProps) {
  const [open, setOpen] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState(emptyPasswordForm);
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return undefined;
    function closeOnOutsideClick(event: PointerEvent) {
      const target = event.target;
      if (target instanceof Node && !menuRef.current?.contains(target)) {
        setOpen(false);
      }
    }
    document.addEventListener("pointerdown", closeOnOutsideClick);
    return () => document.removeEventListener("pointerdown", closeOnOutsideClick);
  }, [open]);

  function openPasswordDialog() {
    setForm(emptyPasswordForm);
    setMessage("");
    setDialogOpen(true);
    setOpen(false);
  }

  function closePasswordDialog() {
    if (saving) return;
    setDialogOpen(false);
    setForm(emptyPasswordForm);
    setMessage("");
  }

  async function submitPassword(event: FormEvent) {
    event.preventDefault();
    setMessage("");
    if (form.new_password !== form.confirm_password) {
      setMessage("两次输入的新密码不一致");
      return;
    }
    setSaving(true);
    try {
      await v2AuthApi.changePassword(form);
      setForm(emptyPasswordForm);
      setMessage("平台密码已更新");
    } catch (exc) {
      setMessage(exc instanceof Error ? exc.message : "密码更新失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="account-menu-wrap" ref={menuRef}>
        <button className="avatar-button" type="button" onClick={() => setOpen((current) => !current)} aria-haspopup="menu" aria-expanded={open} title="账号">
          <UserRound size={17} />
        </button>
        {open && (
          <div className="account-menu" role="menu">
            <button type="button" role="menuitem" onClick={openPasswordDialog}>
              <KeyRound size={15} />
              <span>设置密码</span>
            </button>
            <button type="button" role="menuitem" onClick={onLogout}>
              <LogOut size={15} />
              <span>登出</span>
            </button>
          </div>
        )}
      </div>

      {dialogOpen && (
        <div className="modal-backdrop" role="presentation" onClick={closePasswordDialog}>
          <form className="password-dialog" role="dialog" aria-modal="true" aria-labelledby="v2-password-dialog-title" onSubmit={submitPassword} onClick={(event) => event.stopPropagation()}>
            <div className="password-dialog-head">
              <div>
                <strong id="v2-password-dialog-title">设置平台密码</strong>
                <span>更新当前登录账号的密码。</span>
              </div>
              <button className="icon-button" type="button" onClick={closePasswordDialog} disabled={saving} aria-label="关闭">
                <X size={16} />
              </button>
            </div>
            <label>
              当前密码
              <input type="password" value={form.current_password} onChange={(event) => setForm({ ...form, current_password: event.target.value })} required />
            </label>
            <label>
              新密码
              <input type="password" value={form.new_password} onChange={(event) => setForm({ ...form, new_password: event.target.value })} required />
            </label>
            <label>
              确认新密码
              <input type="password" value={form.confirm_password} onChange={(event) => setForm({ ...form, confirm_password: event.target.value })} required />
            </label>
            {message && <div className="inline-message">{message}</div>}
            <div className="password-dialog-actions">
              <button className="secondary-button" type="button" onClick={closePasswordDialog} disabled={saving}>
                取消
              </button>
              <button className="primary-button" type="submit" disabled={saving}>
                <Save size={15} />
                {saving ? "保存中" : "修改密码"}
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
