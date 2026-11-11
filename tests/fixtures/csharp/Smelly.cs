// C# fixture: lizard-only language (no tree-sitter adapter).
namespace Demo
{
    public class Billing
    {
        public Billing(int repo, int mailer, int clock, int logger, int audit, int cache) { }

        public int Charge(bool a, bool b, bool c, int[] items, int retries)
        {
            int total = 0;
            if ((a && b) || c)
            {
                foreach (var item in items)
                {
                    if (item > 0)
                    {
                        while (retries > 0)
                        {
                            if (item % 2 == 0)
                            {
                                total += item;
                            }
                            retries--;
                        }
                    }
                    else if (item < 0)
                    {
                        total -= item;
                    }
                    else
                    {
                        total++;
                    }
                }
            }
            return total;
        }
    }
}
