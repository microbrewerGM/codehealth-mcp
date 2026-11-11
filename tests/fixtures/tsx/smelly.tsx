// Smelly fixture: every smell below is asserted in the tests.
type Item = { id: number; done: boolean; urgent: boolean; owner?: string };

export function TaskList(items: Item[], filter: string, user: string, compact: boolean, limit: number) {
  const rows = [];
  for (const item of items) {
    if (item.done && filter === "open" || item.urgent && !compact) {
      continue;
    }
    if (item.owner) {
      if (item.owner === user) {
        while (rows.length < limit) {
          if (item.urgent) {
            rows.push(<li key={item.id}>urgent</li>);
          }
          break;
        }
      }
    }
  }
  return <ul>{rows}</ul>;
}
