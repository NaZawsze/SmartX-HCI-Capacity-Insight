export type V2TaskStatus = "pending" | "running" | "success" | "failed" | "cancelled";

export type V2TaskType = "report" | "migration_export" | "migration_import" | "upgrade" | "cleanup" | "collection";

export interface V2ErrorSnapshot {
  code: string;
  message: string;
}

export interface V2TaskSnapshot {
  id: string;
  type: V2TaskType;
  status: V2TaskStatus;
  title: string;
  progress: number;
  message?: string | null;
  error?: V2ErrorSnapshot | null;
}
