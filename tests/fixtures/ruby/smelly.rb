# Ruby fixture: lizard-only language (no tree-sitter adapter).
class Billing
  def initialize(repo, mailer, clock, logger, audit, cache)
    @repo = repo
    @mailer = mailer
    @clock = clock
    @logger = logger
    @audit = audit
    @cache = cache
  end

  def charge(account, amount, currency, note, retries)
    total = 0
    if account && amount > 0 || note
      retries.times do |i|
        if i.even?
          total += amount
        elsif i > 3
          total -= 1
        else
          total += 2
        end
        while total > 100
          total -= 10
        end
        total += 1 if currency == "EUR"
        total += 2 if currency == "USD"
        total += 3 if currency == "GBP"
      end
    end
    total
  end
end
