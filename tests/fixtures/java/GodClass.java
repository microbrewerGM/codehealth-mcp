package demo;

/** Fixture: PMD GodClass (WMC >= 47, ATFD > 5, TCC < 1/3). */
public class Ledger {
    private int f0;
    private int f1;
    private int f2;
    private int f3;
    private int f4;
    private int f5;
    private int f6;
    private int f7;

    public int settle0(Account a, Order o, Customer c) {
        int x = 0;
        if (a.getBalance() > 0) { x += a.getBalance(); }
        if (o.getTotal() > 0) { x += o.getTotal(); }
        if (c.getLimit() > 0) { x += c.getLimit(); }
        if (a.getOwner() != null && o.getId() > 0) { x++; }
        for (int k = 0; k < c.getCount(); k++) { x += k; }
        f0 = x;
        return f0;
    }

    public int settle1(Account a, Order o, Customer c) {
        int x = 0;
        if (a.getBalance() > 1) { x += a.getBalance(); }
        if (o.getTotal() > 1) { x += o.getTotal(); }
        if (c.getLimit() > 1) { x += c.getLimit(); }
        if (a.getOwner() != null && o.getId() > 0) { x++; }
        for (int k = 0; k < c.getCount(); k++) { x += k; }
        f1 = x;
        return f1;
    }

    public int settle2(Account a, Order o, Customer c) {
        int x = 0;
        if (a.getBalance() > 2) { x += a.getBalance(); }
        if (o.getTotal() > 2) { x += o.getTotal(); }
        if (c.getLimit() > 2) { x += c.getLimit(); }
        if (a.getOwner() != null && o.getId() > 0) { x++; }
        for (int k = 0; k < c.getCount(); k++) { x += k; }
        f2 = x;
        return f2;
    }

    public int settle3(Account a, Order o, Customer c) {
        int x = 0;
        if (a.getBalance() > 3) { x += a.getBalance(); }
        if (o.getTotal() > 3) { x += o.getTotal(); }
        if (c.getLimit() > 3) { x += c.getLimit(); }
        if (a.getOwner() != null && o.getId() > 0) { x++; }
        for (int k = 0; k < c.getCount(); k++) { x += k; }
        f3 = x;
        return f3;
    }

    public int settle4(Account a, Order o, Customer c) {
        int x = 0;
        if (a.getBalance() > 4) { x += a.getBalance(); }
        if (o.getTotal() > 4) { x += o.getTotal(); }
        if (c.getLimit() > 4) { x += c.getLimit(); }
        if (a.getOwner() != null && o.getId() > 0) { x++; }
        for (int k = 0; k < c.getCount(); k++) { x += k; }
        f4 = x;
        return f4;
    }

    public int settle5(Account a, Order o, Customer c) {
        int x = 0;
        if (a.getBalance() > 5) { x += a.getBalance(); }
        if (o.getTotal() > 5) { x += o.getTotal(); }
        if (c.getLimit() > 5) { x += c.getLimit(); }
        if (a.getOwner() != null && o.getId() > 0) { x++; }
        for (int k = 0; k < c.getCount(); k++) { x += k; }
        f5 = x;
        return f5;
    }

    public int settle6(Account a, Order o, Customer c) {
        int x = 0;
        if (a.getBalance() > 6) { x += a.getBalance(); }
        if (o.getTotal() > 6) { x += o.getTotal(); }
        if (c.getLimit() > 6) { x += c.getLimit(); }
        if (a.getOwner() != null && o.getId() > 0) { x++; }
        for (int k = 0; k < c.getCount(); k++) { x += k; }
        f6 = x;
        return f6;
    }

    public int settle7(Account a, Order o, Customer c) {
        int x = 0;
        if (a.getBalance() > 7) { x += a.getBalance(); }
        if (o.getTotal() > 7) { x += o.getTotal(); }
        if (c.getLimit() > 7) { x += c.getLimit(); }
        if (a.getOwner() != null && o.getId() > 0) { x++; }
        for (int k = 0; k < c.getCount(); k++) { x += k; }
        f7 = x;
        return f7;
    }

}

interface Account { int getBalance(); Object getOwner(); }
interface Order { int getTotal(); int getId(); }
interface Customer { int getLimit(); int getCount(); }
