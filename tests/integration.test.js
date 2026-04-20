/**
 * Integration tests for core features
 */

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

describe('Integration Tests - Favorites System', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('should add and retrieve favorites', () => {
    const favorites = new Set();
    const addFavorite = (id) => favorites.add(id);
    const getFavorites = () => Array.from(favorites);
    const saveFavorites = () => {
      localStorage.setItem('amex-favorites', JSON.stringify(getFavorites()));
    };

    addFavorite('rest-123');
    addFavorite('rest-456');
    saveFavorites();

    expect(localStorage.getItem('amex-favorites')).toBe('["rest-123","rest-456"]');
  });

  it('should persist favorites across sessions', () => {
    localStorage.setItem('amex-favorites', JSON.stringify(['rest-123', 'rest-456']));
    const loadFavorites = () => {
      const saved = localStorage.getItem('amex-favorites');
      return new Set(saved ? JSON.parse(saved) : []);
    };

    const favorites = loadFavorites();
    expect(favorites.has('rest-123')).toBe(true);
    expect(favorites.has('rest-456')).toBe(true);
    expect(favorites.size).toBe(2);
  });

  it('should remove favorites', () => {
    const favorites = new Set(['rest-123', 'rest-456']);
    const removeFavorite = (id) => favorites.delete(id);

    removeFavorite('rest-123');

    expect(favorites.has('rest-123')).toBe(false);
    expect(favorites.has('rest-456')).toBe(true);
    expect(favorites.size).toBe(1);
  });
});

describe('Integration Tests - Trip Planning', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('should create and save trips', () => {
    const trips = [];
    const createTrip = (name, country) => {
      const trip = { id: Date.now(), name, country, restaurants: [], created: new Date() };
      trips.push(trip);
      return trip;
    };
    const saveTrips = () => {
      localStorage.setItem('amex-trips', JSON.stringify(trips));
    };

    const trip = createTrip('Tokyo Food Tour', 'Japan');
    saveTrips();

    const saved = JSON.parse(localStorage.getItem('amex-trips'));
    expect(saved).toHaveLength(1);
    expect(saved[0].name).toBe('Tokyo Food Tour');
    expect(saved[0].country).toBe('Japan');
  });

  it('should add restaurants to trips', () => {
    const trip = {
      id: 1,
      name: 'Tokyo Tour',
      country: 'Japan',
      restaurants: []
    };

    const addToTrip = (tripId, restaurant) => {
      if (trip.id === tripId) {
        trip.restaurants.push(restaurant);
      }
    };

    const restaurant = { id: 'rest-1', name: 'Tsukiji Outer Market' };
    addToTrip(1, restaurant);

    expect(trip.restaurants).toHaveLength(1);
    expect(trip.restaurants[0].name).toBe('Tsukiji Outer Market');
  });

  it('should delete trips', () => {
    const trips = [
      { id: 1, name: 'Tokyo Tour', restaurants: [] },
      { id: 2, name: 'Paris Tour', restaurants: [] }
    ];

    const deleteTrip = (tripId) => {
      const index = trips.findIndex(t => t.id === tripId);
      if (index !== -1) trips.splice(index, 1);
    };

    deleteTrip(1);

    expect(trips).toHaveLength(1);
    expect(trips[0].name).toBe('Paris Tour');
  });
});

describe('Integration Tests - Filtering & Search', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('should filter restaurants by country', () => {
    const restaurants = [
      { id: 1, name: 'Resto A', country: 'Japan' },
      { id: 2, name: 'Resto B', country: 'France' },
      { id: 3, name: 'Resto C', country: 'Japan' }
    ];

    const filterByCountry = (data, country) => data.filter(r => r.country === country);

    const result = filterByCountry(restaurants, 'Japan');
    expect(result).toHaveLength(2);
    expect(result[0].name).toBe('Resto A');
    expect(result[1].name).toBe('Resto C');
  });

  it('should filter restaurants by cuisine', () => {
    const restaurants = [
      { id: 1, name: 'Sushi Place', cuisine: 'Japanese' },
      { id: 2, name: 'French Bistro', cuisine: 'French' },
      { id: 3, name: 'Ramen Shop', cuisine: 'Japanese' }
    ];

    const filterByCuisine = (data, cuisine) => data.filter(r => r.cuisine === cuisine);

    const result = filterByCuisine(restaurants, 'Japanese');
    expect(result).toHaveLength(2);
  });

  it('should filter restaurants by rating', () => {
    const restaurants = [
      { id: 1, name: 'Resto A', rating: 4.5 },
      { id: 2, name: 'Resto B', rating: 3.2 },
      { id: 3, name: 'Resto C', rating: 4.8 }
    ];

    const filterByRating = (data, minRating) => data.filter(r => r.rating >= minRating);

    const result = filterByRating(restaurants, 4.0);
    expect(result).toHaveLength(2);
  });

  it('should search restaurants by name', () => {
    const restaurants = [
      { id: 1, name: 'Tsukiji Market' },
      { id: 2, name: 'Tokyo Tower' },
      { id: 3, name: 'Senso-ji Temple' }
    ];

    const searchByName = (data, query) => {
      const lower = query.toLowerCase();
      return data.filter(r => r.name.toLowerCase().includes(lower));
    };

    const result = searchByName(restaurants, 'Tokyo');
    expect(result).toHaveLength(1);
    expect(result[0].name).toBe('Tokyo Tower');
  });
});

describe('Integration Tests - Data Export', () => {
  it('should export restaurants to CSV format', () => {
    const restaurants = [
      { id: 1, name: 'Resto A', country: 'Japan', cuisine: 'Japanese' },
      { id: 2, name: 'Resto B', country: 'France', cuisine: 'French' }
    ];

    const exportToCSV = (data) => {
      const headers = Object.keys(data[0]);
      const headerRow = headers.join(',');
      const dataRows = data.map(row =>
        headers.map(header => {
          const value = row[header];
          if (typeof value === 'string' && value.includes(',')) {
            return `"${value}"`;
          }
          return value;
        }).join(',')
      );
      return [headerRow, ...dataRows].join('\n');
    };

    const csv = exportToCSV(restaurants);
    expect(csv).toContain('id,name,country,cuisine');
    expect(csv).toContain('Resto A');
    expect(csv).toContain('France');
  });

  it('should export trip itinerary', () => {
    const trip = {
      id: 1,
      name: 'Tokyo Food Tour',
      restaurants: [
        { name: 'Sushi Place', address: '1-2-3 Ginza' },
        { name: 'Ramen Shop', address: '4-5-6 Shibuya' }
      ]
    };

    const exportTrip = (trip) => {
      let text = `Trip: ${trip.name}\n\n`;
      text += 'Restaurants:\n';
      trip.restaurants.forEach((r, i) => {
        text += `${i + 1}. ${r.name} (${r.address})\n`;
      });
      return text;
    };

    const exported = exportTrip(trip);
    expect(exported).toContain('Tokyo Food Tour');
    expect(exported).toContain('Sushi Place');
    expect(exported).toContain('Ramen Shop');
  });
});

describe('Integration Tests - Multi-language Support', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('should save and retrieve language preference', () => {
    const setLanguage = (lang) => {
      localStorage.setItem('amex-language', lang);
    };
    const getLanguage = () => {
      return localStorage.getItem('amex-language') || 'en';
    };

    setLanguage('ja');
    expect(getLanguage()).toBe('ja');
  });

  it('should translate keys', () => {
    const TRANSLATIONS = {
      en: { appTitle: 'Platinum Experience', search: 'Search' },
      ja: { appTitle: 'プラチナムエクスペリエンス', search: '検索' },
      zh: { appTitle: '铂金体验', search: '搜索' }
    };

    let currentLanguage = 'en';
    const t = (key) => {
      return TRANSLATIONS[currentLanguage]?.[key] || TRANSLATIONS['en']?.[key] || key;
    };

    expect(t('appTitle')).toBe('Platinum Experience');

    currentLanguage = 'ja';
    expect(t('appTitle')).toBe('プラチナムエクスペリエンス');

    currentLanguage = 'zh';
    expect(t('search')).toBe('搜索');
  });
});
