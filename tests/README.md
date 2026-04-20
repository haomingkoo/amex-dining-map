# Test Suite

Comprehensive test coverage for the AMEX Dining Map application.

## Running Tests

### Install Dependencies
```bash
npm install
```

### Run All Tests
```bash
npm test
```

### Run Tests in Watch Mode
```bash
npm run test:watch
```

### Generate Coverage Report
```bash
npm run test:coverage
```

## Test Structure

### Unit Tests (`utils.test.js`)
Tests for utility functions in isolation:
- **Debounce function**: Verifies delayed execution and call cancellation
- **Currency conversion**: Tests exchange rate calculations and fallbacks
- **Price formatting**: Tests currency symbol insertion and localization

### Integration Tests (`integration.test.js`)
Tests for how components work together:
- **Favorites system**: Adding, retrieving, and persisting favorites across sessions
- **Trip planning**: Creating trips, adding restaurants, deleting trips
- **Filtering & Search**: Filter by country, cuisine, rating; search by name
- **Data export**: CSV export and trip itinerary export
- **Multi-language support**: Language persistence and translation lookup

### API Tests (`api.test.js`)
Tests for REST API endpoints:
- **Health check**: Verify system status and venue counts
- **Dining endpoints**: Filtering, pagination, search functionality
- **CSV export**: Format validation and special character handling
- **Statistics**: Cuisine and country distribution calculations

## Coverage Targets

| Category | Target |
|----------|--------|
| Statements | 70% |
| Branches | 60% |
| Functions | 70% |
| Lines | 70% |

## Test Naming Convention

Tests follow the pattern:
```
<describe block>(<feature or component>)
  it('<should behavior when condition>')
```

Example:
```javascript
describe('Favorites System', () => {
  it('should add and retrieve favorites', () => {
    // test code
  });
});
```

## Key Testing Patterns

### AAA Pattern (Arrange → Act → Assert)
```javascript
it('should add favorite', () => {
  // Arrange
  const favorites = new Set();
  const addFavorite = (id) => favorites.add(id);

  // Act
  addFavorite('rest-123');

  // Assert
  expect(favorites.has('rest-123')).toBe(true);
});
```

### Testing localStorage
```javascript
it('should persist data to localStorage', () => {
  localStorage.setItem('key', 'value');
  expect(localStorage.getItem('key')).toBe('value');
});
```

### Testing Async Operations
```javascript
it('should handle async operations', (done) => {
  setTimeout(() => {
    expect(result).toBe(expected);
    done();
  }, 100);
});
```

## Continuous Integration

These tests are designed to run in CI/CD pipelines:
```bash
npm test -- --coverage --watchAll=false
```

## Future Enhancements

- [ ] Add E2E tests with Cypress or Playwright
- [ ] Add performance benchmarks
- [ ] Add accessibility testing (axe-core)
- [ ] Add visual regression testing
- [ ] Add database integration tests for API server
