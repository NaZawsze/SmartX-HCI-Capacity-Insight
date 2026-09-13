import { RefreshCw, Server } from "lucide-react";
import { useState } from "react";
import { api } from "../../services/api";
import { PageHeader, serviceItems } from "./shared";

interface RestartSectionProps {
  active: boolean;
}

export function RestartSection({ active }: RestartSectionProps) {
  const [restartBusy, setRestartBusy] = useState(false);
  const [restartMessage, setRestartMessage] = useState("");

  async function restartServices() {
    setRestartMessage("");
    setRestartBusy(true);
    try {
      const result = await api.restartSystemServices();
      setRestartMessage(result.message);
    } catch (exc) {
      setRestartMessage(exc instanceof Error ? exc.message : "重启失败");
    } finally {
      setRestartBusy(false);
    }
  }

  if (!active) return null;

  return (
    <>
      <PageHeader eyebrow="系统运维" title="服务重启" />
      <div className="service-operation-card">
        <div className="service-operation-head">
          <div>
            <strong>数据服务</strong>
            <span>导入迁移包后可手动重启，使业务库和历史指标完全生效。</span>
          </div>
          <button className="primary-button" type="button" onClick={restartServices} disabled={restartBusy}>
            <RefreshCw size={16} />
            {restartBusy ? "正在提交" : "重启数据服务"}
          </button>
        </div>
        <div className="service-runtime-list">
          {serviceItems.map((item) => (
            <div className="service-runtime-item" key={item.name}>
              <Server size={18} />
              <div>
                <strong>{item.name}</strong>
                <span>{item.description}</span>
              </div>
            </div>
          ))}
        </div>
        {restartMessage && <div className="inline-message">{restartMessage}</div>}
      </div>
    </>
  );
}
