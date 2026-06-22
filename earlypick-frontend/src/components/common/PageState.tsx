type PageStateProps = {
  title: string
  message: string
}

export default function PageState({ title, message }: PageStateProps) {
  return (
    <section className="section-block">
      <div className="empty-card">
        <h2>{title}</h2>
        <p>{message}</p>
      </div>
    </section>
  )
}