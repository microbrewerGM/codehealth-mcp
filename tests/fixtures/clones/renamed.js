// Renamed clone: summarize/tally differ only in names and constants; render is
// structurally different code of a similar size.

function summarize(orders, limit) {
  const totals = new Map();
  for (const order of orders) {
    if (order.amount > limit) {
      totals.set(order.customer, (totals.get(order.customer) || 0) + order.amount);
    } else {
      totals.set(order.customer, (totals.get(order.customer) || 0) + 1);
    }
  }
  const ranked = [...totals.entries()].sort((a, b) => a[1] - b[1]);
  const best = ranked[ranked.length - 1];
  const worst = ranked[0];
  const label = `orders: ${ranked.length}`;
  return [best, worst, label];
}

function tally(events, cutoff) {
  const counts = new Map();
  for (const event of events) {
    if (event.size > cutoff * 2) {
      counts.set(event.owner, (counts.get(event.owner) || 0) + event.size);
    } else {
      counts.set(event.owner, (counts.get(event.owner) || 0) + 5);
    }
  }
  const ordered = [...counts.entries()].sort((x, y) => x[1] - y[1]);
  const top = ordered[ordered.length - 1];
  const bottom = ordered[0];
  const title = `events: ${ordered.length}`;
  return [top, bottom, title];
}

function render(rows, width) {
  const lines = [];
  let index = 0;
  while (index < rows.length) {
    const row = rows[index];
    let text;
    try {
      text = row.format({ width });
    } catch (err) {
      text = "?";
    }
    lines.push(text.padEnd(width));
    index += 1;
  }
  return lines.join("\n");
}
