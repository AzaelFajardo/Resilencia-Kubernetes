import { StatusBadge } from "./StatusBadge";

type ServiceTone = "success" | "error" | "warning" | "neutral" | "info";

interface ServiceCardProps {
  name: string;
  port: string;
  statusLabel: string;
  tone: ServiceTone;
  description: string;
  lastChecked: string;
  actionLabel: string;
  actionHref?: string;
}

export function ServiceCard({
  name,
  port,
  statusLabel,
  tone,
  description,
  lastChecked,
  actionLabel,
  actionHref,
}: ServiceCardProps) {
  return (
    <article className="service-card">
      <div className="service-card__top">
        <div>
          <p className="service-card__name">{name}</p>
          <p className="service-card__port">{port}</p>
        </div>
        <StatusBadge label={statusLabel} tone={tone} />
      </div>
      <p className="service-card__description">{description}</p>
      <div className="service-card__bottom">
        <span className="service-card__checked">{lastChecked}</span>
        {actionHref ? (
          <a className="button button--secondary" href={actionHref} target="_blank" rel="noreferrer">
            {actionLabel}
          </a>
        ) : (
          <button className="button button--secondary button--disabled" disabled>
            {actionLabel}
          </button>
        )}
      </div>
    </article>
  );
}
