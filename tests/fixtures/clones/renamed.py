# Renamed clone: summarize/tally differ only in names and constants; render is
# structurally different code of a similar size.


def summarize(orders, limit):
    totals = {}
    for order in orders:
        if order.amount > limit:
            totals[order.customer] = totals.get(order.customer, 0) + order.amount
        else:
            totals[order.customer] = totals.get(order.customer, 0) + 1
    ranked = sorted(totals.items(), key=lambda pair: pair[1])
    best = ranked[-1]
    worst = ranked[0]
    label = "orders: " + str(len(ranked))
    return best, worst, label


def tally(events, cutoff):
    counts = {}
    for event in events:
        if event.size > cutoff * 2:
            counts[event.owner] = counts.get(event.owner, 0) + event.size
        else:
            counts[event.owner] = counts.get(event.owner, 0) + 5
    ordered = sorted(counts.items(), key=lambda item: item[1])
    top = ordered[-1]
    bottom = ordered[0]
    title = "events: " + str(len(ordered))
    return top, bottom, title


def render(rows, width):
    lines = []
    index = 0
    while index < len(rows):
        row = rows[index]
        try:
            text = row.format(width=width)
        except KeyError:
            text = "?"
        lines.append(text.ljust(width))
        index += 1
    with open("report.txt", "w") as handle:
        handle.write("\n".join(lines))
    return len(lines)
