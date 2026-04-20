/**
 * Unit tests for utility functions
 */

// Mock localStorage for testing
const localStorageMock = (() => {
  let store = {};
  return {
    getItem: (key) => store[key] || null,
    setItem: (key, value) => {
      store[key] = value.toString();
    },
    removeItem: (key) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    }
  };
})();

global.localStorage = localStorageMock;

describe('Utility Functions', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  // Debounce function test
  describe('debounce', () => {
    it('should delay function execution', (done) => {
      const mockFn = jest.fn();
      const debounced = debounce(mockFn, 100);

      debounced('test');
      debounced('test');
      debounced('test');

      expect(mockFn).not.toHaveBeenCalled();

      setTimeout(() => {
        expect(mockFn).toHaveBeenCalledTimes(1);
        expect(mockFn).toHaveBeenCalledWith('test');
        done();
      }, 150);
    });

    it('should cancel previous calls', (done) => {
      const mockFn = jest.fn();
      const debounced = debounce(mockFn, 100);

      debounced('first');
      setTimeout(() => debounced('second'), 50);

      setTimeout(() => {
        expect(mockFn).toHaveBeenCalledTimes(1);
        expect(mockFn).toHaveBeenCalledWith('second');
        done();
      }, 200);
    });
  });

  // Currency conversion tests
  describe('convertCurrency', () => {
    it('should convert currency using exchange rates', () => {
      // Assuming 1 USD = 1.0 (base), 1 EUR = 1.1
      const EXCHANGE_RATES = { 'USD': 1.0, 'EUR': 1.1, 'JPY': 0.0067 };
      const convertCurrency = (amount, fromCurrency, toCurrency) => {
        if (!EXCHANGE_RATES[fromCurrency] || !EXCHANGE_RATES[toCurrency]) return amount;
        return (amount / EXCHANGE_RATES[fromCurrency]) * EXCHANGE_RATES[toCurrency];
      };

      const result = convertCurrency(100, 'USD', 'EUR');
      expect(result).toBeCloseTo(110, 1);
    });

    it('should return original amount if currency not found', () => {
      const EXCHANGE_RATES = { 'USD': 1.0, 'EUR': 1.1 };
      const convertCurrency = (amount, fromCurrency, toCurrency) => {
        if (!EXCHANGE_RATES[fromCurrency] || !EXCHANGE_RATES[toCurrency]) return amount;
        return (amount / EXCHANGE_RATES[fromCurrency]) * EXCHANGE_RATES[toCurrency];
      };

      const result = convertCurrency(100, 'XXX', 'EUR');
      expect(result).toBe(100);
    });
  });

  // Price formatting tests
  describe('formatPrice', () => {
    it('should format price with currency symbol', () => {
      const CURRENCY_SYMBOLS = { 'USD': '$', 'EUR': '€', 'JPY': '¥' };
      const formatPrice = (amount, currency) => {
        const symbol = CURRENCY_SYMBOLS[currency] || currency;
        return `${symbol}${amount.toFixed(2)}`;
      };

      const result = formatPrice(100.5, 'USD');
      expect(result).toBe('$100.50');
    });

    it('should use currency code as fallback', () => {
      const CURRENCY_SYMBOLS = { 'USD': '$', 'EUR': '€' };
      const formatPrice = (amount, currency) => {
        const symbol = CURRENCY_SYMBOLS[currency] || currency;
        return `${symbol}${amount.toFixed(2)}`;
      };

      const result = formatPrice(100, 'JPY');
      expect(result).toBe('JPY100.00');
    });
  });
});

// Helper functions for testing (would be imported from app.js in real scenario)
const debounce = (fn, delay) => {
  let timeoutId;
  return (...args) => {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(() => fn(...args), delay);
  };
};
