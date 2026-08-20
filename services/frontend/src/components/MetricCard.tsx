interface MetricCardProps {
  title: string;
  value: string;
  hint?: string;
}

export function MetricCard({ title, value, hint }: MetricCardProps) {
  return (
    <article className="metric-card">
      <p className="metric-card__title">{title}</p>
      <p className="metric-card__value">{value}</p>
      {hint ? <p className="metric-card__hint">{hint}</p> : null}
    </article>
  );
}
