// Smelly fixture: every smell below is asserted in the tests.
public class Smelly {
    private int a;
    private int b;
    private int x;
    private int y;

    public int process(boolean p, boolean q, boolean r, int[] d, int e) {
        int total = 0;
        if (p && q || r) {
            for (int item : d) {
                if (item > 0) {
                    while (e > 0) {
                        if (item % 2 == 0) {
                            total += item;
                        }
                        e -= 1;
                    }
                } else if (item < 0) {
                    total -= item;
                } else {
                    total += 1;
                }
            }
        }
        return total;
    }

    public int bumpy(int x0, int y0) {
        if (x0 > 0) {
            if (y0 > 0) {
                x0 += 1;
            }
        }
        y0 = x0 * 2;
        for (int i = 0; i < y0; i++) {
            if (i % 3 == 0) {
                x0 += i;
            }
        }
        return x0;
    }

    public void incA() {
        a += 1;
    }

    public void incB() {
        b += a;
    }

    public void incX() {
        this.x += 1;
    }

    public void incY() {
        y += x;
    }
}
