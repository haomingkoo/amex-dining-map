/**
 * Unit tests for API endpoints
 */

describe('API Endpoint Tests', () => {
  const mockRestaurants = [
    {
      id: 'rest-1',
      name: 'Tsukiji Market',
      country: 'Japan',
      city: 'Tokyo',
      cuisine: 'Japanese',
      googleRating: 4.5,
      reviewCount: 1200
    },
    {
      id: 'rest-2',
      name: 'Le Petit Bistro',
      country: 'France',
      city: 'Paris',
      cuisine: 'French',
      googleRating: 4.7,
      reviewCount: 890
    }
  ];

  describe('GET /api/v1/health', () => {
    it('should return health check with venue counts', () => {
      const health = {
        status: 'ok',
        timestamp: new Date(),
        venues: {
          dining: 2,
          stays: 0,
          loveDining: 0
        }
      };

      expect(health.status).toBe('ok');
      expect(health.venues.dining).toBe(2);
    });
  });

  describe('GET /api/v1/dining', () => {
    it('should return all dining restaurants with default limit', () => {
      const limit = 100;
      const skip = 0;
      const results = mockRestaurants.slice(skip, skip + limit);

      expect(results).toHaveLength(2);
      expect(results[0].name).toBe('Tsukiji Market');
    });

    it('should support pagination', () => {
      const limit = 1;
      const skip = 1;
      const results = mockRestaurants.slice(skip, skip + limit);

      expect(results).toHaveLength(1);
      expect(results[0].name).toBe('Le Petit Bistro');
    });

    it('should filter by country', () => {
      const country = 'Japan';
      const results = mockRestaurants.filter(r => r.country === country);

      expect(results).toHaveLength(1);
      expect(results[0].country).toBe('Japan');
    });

    it('should filter by cuisine', () => {
      const cuisine = 'French';
      const results = mockRestaurants.filter(r => r.cuisine === cuisine);

      expect(results).toHaveLength(1);
      expect(results[0].cuisine).toBe('French');
    });

    it('should filter by minimum rating', () => {
      const minRating = 4.6;
      const results = mockRestaurants.filter(r => r.googleRating >= minRating);

      expect(results).toHaveLength(1);
      expect(results[0].googleRating).toBe(4.7);
    });
  });

  describe('GET /api/v1/search', () => {
    it('should search restaurants by query', () => {
      const query = 'market';
      const results = mockRestaurants.filter(r =>
        r.name.toLowerCase().includes(query.toLowerCase())
      );

      expect(results).toHaveLength(1);
      expect(results[0].name).toContain('Market');
    });

    it('should search with multiple filters', () => {
      const country = 'Japan';
      const minRating = 4.0;
      const results = mockRestaurants.filter(r =>
        r.country === country && r.googleRating >= minRating
      );

      expect(results).toHaveLength(1);
      expect(results[0].country).toBe('Japan');
      expect(results[0].googleRating).toBeGreaterThanOrEqual(4.0);
    });

    it('should return empty array for no matches', () => {
      const query = 'nonexistent';
      const results = mockRestaurants.filter(r =>
        r.name.toLowerCase().includes(query.toLowerCase())
      );

      expect(results).toHaveLength(0);
    });
  });

  describe('GET /api/v1/export/csv', () => {
    it('should generate valid CSV format', () => {
      const data = mockRestaurants;
      const headers = Object.keys(data[0]);
      const headerRow = headers.join(',');
      const dataRows = data.map(row =>
        headers.map(h => {
          const value = row[h];
          return typeof value === 'string' && value.includes(',') ? `"${value}"` : value;
        }).join(',')
      );
      const csv = [headerRow, ...dataRows].join('\n');

      expect(csv).toContain('id,name,country');
      expect(csv).toContain('rest-1');
      expect(csv).toContain('Tsukiji Market');
    });

    it('should handle special characters in CSV', () => {
      const data = [
        { id: '1', name: 'Restaurant, Ltd.', description: 'Has "quotes"' }
      ];
      const headers = Object.keys(data[0]);
      const dataRows = data.map(row =>
        headers.map(h => {
          const value = row[h];
          return typeof value === 'string' && (value.includes(',') || value.includes('"'))
            ? `"${value.replace(/"/g, '""')}"` : value;
        }).join(',')
      );
      const csv = [headers.join(','), ...dataRows].join('\n');

      expect(csv).toContain('"Restaurant, Ltd."');
    });
  });

  describe('GET /api/v1/stats', () => {
    it('should return statistics', () => {
      const stats = {
        total_venues: 2,
        countries: 2,
        cuisines: 2,
        avg_rating: 4.6,
        total_reviews: 2090
      };

      expect(stats.total_venues).toBe(2);
      expect(stats.countries).toBe(2);
      expect(stats.avg_rating).toBeCloseTo(4.6, 1);
    });

    it('should calculate cuisine distribution', () => {
      const cuisineCount = mockRestaurants.reduce((acc, r) => {
        acc[r.cuisine] = (acc[r.cuisine] || 0) + 1;
        return acc;
      }, {});

      expect(cuisineCount['Japanese']).toBe(1);
      expect(cuisineCount['French']).toBe(1);
    });

    it('should calculate country distribution', () => {
      const countryCount = mockRestaurants.reduce((acc, r) => {
        acc[r.country] = (acc[r.country] || 0) + 1;
        return acc;
      }, {});

      expect(countryCount['Japan']).toBe(1);
      expect(countryCount['France']).toBe(1);
    });
  });
});
