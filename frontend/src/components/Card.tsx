import type { ReactNode } from "react";

interface CardProps {
  title?: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Card({ title, subtitle, action, children, className = "" }: CardProps) {
  return (
    <section className={`card ${className}`.trim()}>
      {(title || action) && (
        <div className="card-head">
          {title && (
            <div className="card-title">
              <h2>{title}</h2>
              {subtitle && <span>{subtitle}</span>}
            </div>
          )}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}
