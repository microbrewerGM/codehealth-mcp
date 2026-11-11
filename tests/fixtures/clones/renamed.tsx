// Renamed clone: OrderList/EventList differ only in names and constants;
// Pager is structurally different code of a similar size.

type Row = { id: number; label: string; score: number };

export function OrderList(orders: Row[], limit: number) {
  const items = [];
  for (const order of orders) {
    if (order.score > limit) {
      items.push(<li key={order.id} className="high">{order.label}</li>);
    } else {
      items.push(<li key={order.id}>{order.label}</li>);
    }
  }
  const first = items[0];
  const rest = items.slice(1);
  const title = "Orders";
  return (
    <section>
      <h2>{title}</h2>
      <ul>{first}{rest}</ul>
    </section>
  );
}

export function EventList(events: Row[], cutoff: number) {
  const entries = [];
  for (const event of events) {
    if (event.score > cutoff) {
      entries.push(<li key={event.id} className="hot">{event.label}</li>);
    } else {
      entries.push(<li key={event.id}>{event.label}</li>);
    }
  }
  const head = entries[0];
  const tail = entries.slice(1);
  const heading = "Events";
  return (
    <section>
      <h2>{heading}</h2>
      <ul>{head}{tail}</ul>
    </section>
  );
}

export function Pager(page: number, pages: number, onChange: (n: number) => void) {
  let start = Math.max(1, page - 2);
  const end = Math.min(pages, start + 4);
  start = Math.max(1, end - 4);
  const buttons = [];
  while (start <= end) {
    const n = start;
    buttons.push(<button key={n} disabled={n === page} onClick={() => onChange(n)}>{n}</button>);
    start += 1;
  }
  return (
    <nav aria-label="pages">
      {page > 1 ? <button onClick={() => onChange(page - 1)}>prev</button> : null}
      {buttons}
    </nav>
  );
}
