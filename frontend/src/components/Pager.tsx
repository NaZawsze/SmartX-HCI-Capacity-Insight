import { ChevronLeft, ChevronRight } from "lucide-react";

interface PagerProps {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  label?: string;
  unit?: string;
}

export function Pager({ page, pageSize, total, onPageChange, label = "分页", unit = "条" }: PagerProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  if (total <= 0) return null;
  return (
    <div className="pager" aria-label={label}>
      <span className="pager-total">
        共 {total} {unit}
      </span>
      <button type="button" className="pager-button" disabled={page <= 1} onClick={() => onPageChange(page - 1)} aria-label="上一页">
        <ChevronLeft size={14} />
      </button>
      <span className="pager-status">
        第 {page} / {totalPages} 页
      </span>
      <button type="button" className="pager-button" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)} aria-label="下一页">
        <ChevronRight size={14} />
      </button>
    </div>
  );
}
