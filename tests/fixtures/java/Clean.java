// A small, healthy class.
public class Clean {
    private int count;

    public int increment(int step) {
        count += step;
        return count;
    }

    public void reset() {
        count = 0;
    }

    public static String greet(String name) {
        if (name == null) {
            return "Hello, stranger";
        }
        return "Hello, " + name;
    }
}
