import type { ReactNode } from "react";

interface CardProps {
  title?: string;
  subtitle?: string;
  notice?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Card({ title, subtitle, notice, action, children, className = "" }: CardProps) {
  return (
    <section className={`card ${className}`.trim()}>
      {(title || action) && (
        <div className="card-head">
          {title && (
            <div className="card-title">
              <h2>
                {title}
                {notice}
              </h2>
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
